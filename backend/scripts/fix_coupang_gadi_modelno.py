"""가디 계정 쿠팡 APPROVED 상품 중 품번(modelNo) 누락된 것 PUT 수정.

- APPROVED 상품은 PUT으로 수정 가능 (DELETE 불필요)
- items[*].modelNo 가 없거나 빈 것 → 삼바 DB style_code로 주입
- emptyBarcode = True 처리
- brandId 없으면 검색해서 주입
- requested = True 포함
"""

import asyncio
import json
import asyncpg
from backend.core.config import settings

ACCOUNT_ID = "ma_01KNZV0ZWXW52W0G4TYG3AJH9Q"
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


def needs_update(data: dict) -> bool:
    """modelNo 누락 또는 emptyBarcode 미처리 시 True."""
    items = data.get("items") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("modelNo"):
            return True
        if not item.get("emptyBarcode") and not item.get("barcode"):
            return True
    return False


def inject_fields(data: dict, style_code: str, vendor_id: str) -> dict:
    data = {k: v for k, v in data.items() if k not in _SERVER_KEYS}
    items = data.get("items") or []
    new_items = []
    for item in items:
        if not isinstance(item, dict):
            new_items.append(item)
            continue
        item = {k: v for k, v in item.items() if k not in _ITEM_SERVER_KEYS}
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
    data["vendorId"] = vendor_id
    data["vendorUserId"] = vendor_id
    data["requested"] = True
    return data


async def main() -> None:
    conn = await get_db_conn()
    acct = await conn.fetchrow(
        "SELECT account_label, additional_fields FROM samba_market_account WHERE id = $1",
        ACCOUNT_ID,
    )
    await conn.close()

    if not acct:
        print("계정 없음")
        return

    label = acct["account_label"]
    raw = acct["additional_fields"] or {}
    extras = json.loads(raw) if isinstance(raw, str) else (raw or {})
    access_key = extras.get("accessKey") or ""
    secret_key = extras.get("secretKey") or ""
    vendor_id = extras.get("vendorId") or ""

    print(f"▶ 계정: {label}")

    from backend.domain.samba.proxy.coupang import CoupangClient

    client = CoupangClient(access_key, secret_key, vendor_id)

    # APPROVED 목록 조회
    print("APPROVED 상품 조회 중...")
    approved = await client.list_seller_products(status="APPROVED")
    print(f"APPROVED: {len(approved):,}개")

    # 삼바 DB에서 style_code, brand 일괄 조회
    spid_list = [a["seller_product_id"] for a in approved]
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

    for i, item in enumerate(approved, 1):
        spid = item["seller_product_id"]
        name = item["product_name"][:35]
        style_code, brand = samba_map.get(spid, ("", ""))

        try:
            resp = await client.get_product(spid)
            data = (
                resp.get("data", resp)
                if isinstance(resp, dict) and "data" in resp
                else resp
            )
            if not isinstance(data, dict):
                fail += 1
                continue

            # 이미 modelNo 있으면 skip
            if not needs_update(data):
                skip += 1
                if i % 200 == 0:
                    print(
                        f"  [{i:,}/{len(approved):,}] ok={ok:,} skip={skip:,} fail={fail:,}"
                    )
                continue

            # 필드 주입
            put_data = inject_fields(data, style_code, vendor_id)

            # brandId 보강
            brand_name = brand or (data.get("brand") or "")
            if brand_name and not put_data.get("brandId"):
                try:
                    bid = await client.search_brand_id(brand_name)
                    if bid:
                        put_data["brandId"] = bid
                except Exception:
                    pass

            # PUT 수정
            await client.update_product(spid, put_data)
            ok += 1
            print(
                f"  ✓ [{i:,}/{len(approved):,}] {spid} modelNo={style_code or '없음'} ({name})"
            )
            await asyncio.sleep(0.4)

        except Exception as e:
            fail += 1
            print(f"  ✗ {spid} — {e}")

        if i % 100 == 0:
            print(f"  [{i:,}/{len(approved):,}] ok={ok:,} skip={skip:,} fail={fail:,}")

    print("\n  ═══════════════════════════════════════")
    print(f"  완료: 수정 {ok:,} / skip {skip:,} / 실패 {fail:,}")


if __name__ == "__main__":
    asyncio.run(main())
