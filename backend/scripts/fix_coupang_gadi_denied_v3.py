"""가디 계정 쿠팡 DENIED 상품 재등록 v3 — R2 이미지 정규화 포함.

- cloudflare_r2 설정에서 R2 클라이언트 직접 초기화
- 이미지 다운로드(타임아웃 3초) → PIL 리사이즈(500~5000px) → R2 업로드
- 접근 불가 URL은 3초 후 skip (원본 유지)
- 한도 초과 시 즉시 중단
"""

import asyncio
import io
import json
import hashlib
import asyncpg
import httpx
from backend.core.config import settings
from backend.domain.samba.proxy.coupang import CoupangClient

ACCOUNT_ID = "ma_01KNZV0ZWXW52W0G4TYG3AJH9Q"
LOTTE_CODE = "HYUNDAI"
_SERVER_KEYS = {
    "sellerProductId", "productId", "approvalStatus", "statusName",
    "exposedStatusName", "createdAt", "updatedAt",
}
_ITEM_SERVER_KEYS = {"vendorItemId", "itemId"}
IMG_MIN = 500
IMG_MAX = 5000
IMG_TIMEOUT = 3.0  # 접근 불가 URL 빠른 스킵


async def get_pg():
    return await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name,
        ssl="require" if settings.use_db_ssl else None,
    )


async def get_r2_config(conn) -> dict:
    row = await conn.fetchrow("SELECT value FROM samba_settings WHERE key='cloudflare_r2' LIMIT 1")
    if not row:
        return {}
    v = row["value"]
    return json.loads(v) if isinstance(v, str) else (v or {})


def make_r2_client(cfg: dict):
    import boto3
    endpoint = cfg.get("endpoint", "")
    access_key = cfg.get("accessKey", "")
    secret_key = cfg.get("secretKey", "")
    if not all([endpoint, access_key, secret_key]):
        return None, "", ""
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    return client, cfg.get("bucketName", ""), cfg.get("publicUrl", "")


async def normalize_url(url: str, r2_client, bucket: str, public_url: str) -> str:
    """이미지 다운로드 → 리사이즈 → R2 업로드 → 새 URL 반환. 실패 시 원본 반환."""
    url = url.strip()
    if not url:
        return url
    if not r2_client:
        return url

    try:
        from PIL import Image

        async with httpx.AsyncClient(timeout=IMG_TIMEOUT, follow_redirects=True) as c:
            resp = await c.get(url)
            if resp.status_code != 200:
                return url
            data = resp.content

        img = Image.open(io.BytesIO(data))
        w, h = img.size
        needs_resize = (w < IMG_MIN or h < IMG_MIN or w > IMG_MAX or h > IMG_MAX)
        if not needs_resize:
            return url  # 규격 OK, 원본 사용

        # 리사이즈: 최소 500 보장, 최대 5000
        scale = max(IMG_MIN / w, IMG_MIN / h)
        if scale < 1.0:
            scale = 1.0
        nw, nh = int(w * scale), int(h * scale)
        if nw > IMG_MAX:
            nw = IMG_MAX
        if nh > IMG_MAX:
            nh = IMG_MAX
        img = img.resize((nw, nh), Image.LANCZOS)

        # JPEG 변환
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        buf.seek(0)

        # R2 키 생성 (URL 해시)
        key = f"coupang/gadi/{hashlib.md5(url.encode()).hexdigest()}.jpg"
        import functools
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                functools.partial(
                    r2_client.put_object,
                    Bucket=bucket,
                    Key=key,
                    Body=buf.getvalue(),
                    ContentType="image/jpeg",
                    ContentDisposition="inline",
                    CacheControl="public, max-age=31536000",
                )
            ),
            timeout=15.0,
        )
        new_url = f"https://api.samba-wave.co.kr/images/{key}"
        print(f"    R2 미러: {w}x{h} → {nw}x{nh} → {new_url[:60]}")
        return new_url

    except Exception as e:
        print(f"    이미지 처리 실패(원본유지): {e}")
        return url


async def normalize_items_images(items: list, r2_client, bucket: str, public_url: str) -> list:
    new_items = []
    for item in items:
        if not isinstance(item, dict):
            new_items.append(item)
            continue
        item = dict(item)
        imgs = item.get("images") or []
        new_imgs = []
        for img in imgs:
            if not isinstance(img, dict):
                new_imgs.append(img)
                continue
            img = dict(img)
            new_url = await normalize_url(img.get("vendorPath", ""), r2_client, bucket, public_url)
            img["vendorPath"] = new_url
            new_imgs.append(img)
        item["images"] = new_imgs
        new_items.append(item)
    return new_items


def strip_server_ids(data: dict) -> dict:
    data = {k: v for k, v in data.items() if k not in _SERVER_KEYS}
    items = data.get("items")
    if isinstance(items, list):
        data["items"] = [
            {k: v for k, v in it.items() if k not in _ITEM_SERVER_KEYS}
            if isinstance(it, dict) else it
            for it in items
        ]
    return data


def inject_model_no(data: dict, style_code: str) -> dict:
    items = data.get("items")
    if not isinstance(items, list):
        return data
    new_items = []
    for item in items:
        if not isinstance(item, dict):
            new_items.append(item)
            continue
        item = dict(item)
        if style_code:
            item["modelNo"] = style_code[:50]
        barcode = item.get("barcode") or ""
        item["barcode"] = barcode
        item["emptyBarcode"] = not barcode
        if item["emptyBarcode"]:
            item["emptyBarcodeReason"] = "품번(MPN)으로 대체" if style_code else "바코드 없음"
        new_items.append(item)
    data["items"] = new_items
    return data


async def update_db(conn, old_spid: str, new_spid: str) -> int:
    result = await conn.execute(
        """
        UPDATE samba_collected_product
        SET market_product_nos = jsonb_set(
            COALESCE(market_product_nos, '{}'),
            ARRAY[$1],
            to_jsonb(CAST($2 AS text))
        )
        WHERE market_product_nos ->> $1 = $3
        """,
        ACCOUNT_ID, new_spid, old_spid,
    )
    return int(result.split()[-1]) if result else 0


async def main() -> None:
    pg = await get_pg()
    acct = await pg.fetchrow(
        "SELECT account_label, additional_fields FROM samba_market_account WHERE id = $1",
        ACCOUNT_ID,
    )
    r2_cfg = await get_r2_config(pg)

    raw = acct["additional_fields"] or {}
    extras = json.loads(raw) if isinstance(raw, str) else (raw or {})
    access_key = extras.get("accessKey") or ""
    secret_key = extras.get("secretKey") or ""
    vendor_id = extras.get("vendorId") or ""
    print(f"▶ 계정: {acct['account_label']}")

    r2_client, bucket, pub_url = make_r2_client(r2_cfg)
    print(f"R2: {'OK' if r2_client else '없음'} bucket={bucket}")

    client = CoupangClient(access_key, secret_key, vendor_id)

    print("DENIED 목록 조회 중...")
    denied = await client.list_seller_products(status="DENIED")
    print(f"DENIED: {len(denied):,}개")

    spid_list = [d["seller_product_id"] for d in denied]
    samba_map: dict[str, tuple[str, str]] = {}
    for i in range(0, len(spid_list), 100):
        batch = spid_list[i:i+100]
        rows = await pg.fetch(
            "SELECT market_product_nos ->> $1 AS spid, style_code, brand "
            "FROM samba_collected_product WHERE market_product_nos ->> $1 = ANY($2)",
            ACCOUNT_ID, batch,
        )
        for r in rows:
            samba_map[r["spid"]] = (
                (r["style_code"] or "").strip(),
                (r["brand"] or "").strip(),
            )
    await pg.close()
    print(f"삼바 DB 매핑: {len(samba_map):,}개")

    ok, fail = 0, 0
    fail_log = []

    for i, item in enumerate(denied, 1):
        spid = item["seller_product_id"]
        name = item["product_name"][:40]
        style_code, brand = samba_map.get(spid, ("", ""))

        try:
            resp = await client.get_product(spid)
            data = resp.get("data", resp) if isinstance(resp, dict) and "data" in resp else resp
            if not isinstance(data, dict):
                fail += 1
                continue

            current_code = data.get("deliveryCompanyCode", "")

            post_data = strip_server_ids(data)
            post_data["deliveryCompanyCode"] = LOTTE_CODE
            post_data["vendorId"] = vendor_id
            post_data["vendorUserId"] = vendor_id
            post_data["requested"] = True
            post_data = inject_model_no(post_data, style_code)

            # 이미지 정규화 (R2)
            post_data["items"] = await normalize_items_images(
                post_data.get("items") or [], r2_client, bucket, pub_url
            )

            # brandId
            brand_name = brand or (data.get("brand") or "")
            if brand_name and not post_data.get("brandId"):
                try:
                    bid = await client.search_brand_id(brand_name)
                    if bid:
                        post_data["brandId"] = bid
                except Exception:
                    pass

            await client.delete_product(spid)
            await asyncio.sleep(0.3)

            reg = await client.register_product(post_data)
            new_spid = ""
            if isinstance(reg, dict):
                inner = reg.get("data", {})
                if isinstance(inner, dict):
                    new_spid = str(inner.get("data", "") or "")
                elif inner:
                    new_spid = str(inner)

            if not new_spid or not new_spid.isdigit():
                err = str(reg)[:150]
                fail += 1
                fail_log.append(f"{spid}: {err}")
                print(f"  ✗ {spid} 재등록실패: {err}")
                if "초과하였습니다" in err or "오늘 등록할 수 있는" in err:
                    print(f"\n  ⚠️  한도 초과. 중단. 성공:{ok:,} 실패:{fail:,}")
                    break
                continue

            pg2 = await get_pg()
            updated = await update_db(pg2, spid, new_spid)
            await pg2.close()

            ok += 1
            print(f"  ✓ [{i:,}/{len(denied):,}] {spid}→{new_spid} [{current_code}→{LOTTE_CODE}] DB:{updated} ({name[:30]})")
            await asyncio.sleep(0.5)

        except Exception as e:
            fail += 1
            fail_log.append(f"{spid}: {e}")
            print(f"  ✗ {spid} — {e}")

        if i % 50 == 0:
            print(f"  [{i:,}/{len(denied):,}] ok={ok:,} fail={fail:,}")

    print(f"\n  ═══════════════════════════════════════")
    print(f"  완료: 성공 {ok:,} / 실패 {fail:,}")
    if fail_log:
        print(f"\n  실패 ({len(fail_log)}개):")
        for f in fail_log[:20]:
            print(f"    {f}")


if __name__ == "__main__":
    asyncio.run(main())
