"""가디 계정 쿠팡 DENIED 상품 우선 처리.

전략: DENIED 목록 먼저 조회 → 삼바 DB에서 style_code/brand 보강 → 재등록.
- deliveryCompanyCode = HYUNDAI (롯데택배)
- modelNo = style_code (품번 의무화)
- brandId 검색 주입
- emptyBarcode = True
- requested = True (임시저장 방지)
- 서버 ID 제거 (sellerProductId, vendorItemId 등)
- 한도 초과 시 즉시 중단 (DELETE 후 재등록 실패 방지)
"""

import asyncio
import json
import asyncpg
from backend.core.config import settings

ACCOUNT_ID = "ma_01KNZV0ZWXW52W0G4TYG3AJH9Q"
LOTTE_CODE = "HYUNDAI"
_SERVER_KEYS = {
    "sellerProductId",
    "productId",
    "approvalStatus",
    "statusName",
    "exposedStatusName",
    "createdAt",
    "updatedAt",
}
_ITEM_SERVER_KEYS = {"vendorItemId", "itemId"}


async def get_db_conn():
    return await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl="require" if settings.use_db_ssl else None,
    )


def strip_server_ids(data: dict) -> dict:
    data = {k: v for k, v in data.items() if k not in _SERVER_KEYS}
    items = data.get("items")
    if isinstance(items, list):
        data["items"] = [
            {k: v for k, v in it.items() if k not in _ITEM_SERVER_KEYS}
            if isinstance(it, dict)
            else it
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
            item["emptyBarcodeReason"] = (
                "품번(MPN)으로 대체" if style_code else "바코드 없음"
            )
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
        ACCOUNT_ID,
        new_spid,
        old_spid,
    )
    return int(result.split()[-1]) if result else 0


async def main() -> None:
    conn = await get_db_conn()
    acct = await conn.fetchrow(
        "SELECT account_label, additional_fields FROM samba_market_account WHERE id = $1",
        ACCOUNT_ID,
    )
    await conn.close()

    if not acct:
        print(f"계정 없음: {ACCOUNT_ID}")
        return

    label = acct["account_label"]
    raw = acct["additional_fields"] or {}
    extras = json.loads(raw) if isinstance(raw, str) else (raw or {})
    access_key = extras.get("accessKey") or ""
    secret_key = extras.get("secretKey") or ""
    vendor_id = extras.get("vendorId") or ""

    if not access_key or not secret_key or not vendor_id:
        print("인증정보 누락")
        return

    print(f"▶ 계정: {label} ({ACCOUNT_ID})")

    from backend.domain.samba.proxy.coupang import CoupangClient

    client = CoupangClient(access_key, secret_key, vendor_id)

    # DENIED 목록 조회
    print("DENIED 상품 목록 조회 중...")
    denied = await client.list_seller_products(status="DENIED")
    print(f"DENIED: {len(denied):,}개")

    # 삼바 DB에서 spid → (style_code, brand) 일괄 조회
    spid_list = [d["seller_product_id"] for d in denied]
    conn = await get_db_conn()
    samba_map: dict[str, tuple[str, str]] = {}
    for i in range(0, len(spid_list), 100):
        batch = spid_list[i : i + 100]
        rows = await conn.fetch(
            """
            SELECT market_product_nos ->> $1 AS spid, style_code, brand
            FROM samba_collected_product
            WHERE market_product_nos ->> $1 = ANY($2)
            """,
            ACCOUNT_ID,
            batch,
        )
        for r in rows:
            samba_map[r["spid"]] = (
                (r["style_code"] or "").strip(),
                (r["brand"] or "").strip(),
            )
    await conn.close()
    print(f"삼바 DB 매핑: {len(samba_map):,}개")

    ok, fail, skip = 0, 0, 0
    fail_log = []

    for i, item in enumerate(denied, 1):
        spid = item["seller_product_id"]
        name = item["product_name"][:40]
        style_code, brand = samba_map.get(spid, ("", ""))

        try:
            # GET
            resp = await client.get_product(spid)
            data = (
                resp.get("data", resp)
                if isinstance(resp, dict) and "data" in resp
                else resp
            )
            if not isinstance(data, dict):
                fail += 1
                fail_log.append(f"{spid}: get_product 오류")
                continue

            current_code = data.get("deliveryCompanyCode", "")

            # 서버 ID 제거 + 필드 보강
            post_data = strip_server_ids(data)
            post_data["deliveryCompanyCode"] = LOTTE_CODE
            post_data["vendorId"] = vendor_id
            post_data["vendorUserId"] = vendor_id
            post_data["requested"] = True

            # 품번 주입
            post_data = inject_model_no(post_data, style_code)

            # brandId 검색
            brand_name = brand or (data.get("brand") or "")
            if brand_name and not post_data.get("brandId"):
                try:
                    bid = await client.search_brand_id(brand_name)
                    if bid:
                        post_data["brandId"] = bid
                except Exception:
                    pass

            # DELETE
            await client.delete_product(spid)
            await asyncio.sleep(0.3)

            # POST
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
                print(f"  ✗ {spid} ({name}) 재등록실패: {err}")
                # 한도 초과 → 즉시 중단
                if "초과하였습니다" in err or "오늘 등록할 수 있는" in err:
                    print(f"\n  ⚠️  일일 한도 초과. 중단. 성공:{ok:,} 실패:{fail:,}")
                    break
                continue

            # DB 업데이트
            conn2 = await get_db_conn()
            updated = await update_db(conn2, spid, new_spid)
            await conn2.close()

            ok += 1
            db_mark = f"DB:{updated}" if updated else "DB:미매핑"
            print(
                f"  ✓ [{i:,}/{len(denied):,}] {spid}→{new_spid} [{current_code}→{LOTTE_CODE}] [{db_mark}] ({name[:30]})"
            )
            await asyncio.sleep(0.5)

        except Exception as e:
            fail += 1
            fail_log.append(f"{spid}: {e}")
            print(f"  ✗ {spid} — {e}")

        if i % 50 == 0:
            print(f"  [{i:,}/{len(denied):,}] ok={ok:,} fail={fail:,}")

    print("\n  ═══════════════════════════════════════")
    print(f"  완료: 성공 {ok:,} / 실패 {fail:,} / skip {skip:,}")
    if fail_log:
        print(f"\n  실패 ({len(fail_log)}개):")
        for f in fail_log[:20]:
            print(f"    {f}")
        if len(fail_log) > 20:
            print(f"    ... 외 {len(fail_log) - 20}개")


if __name__ == "__main__":
    asyncio.run(main())
