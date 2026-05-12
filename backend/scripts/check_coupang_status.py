"""쿠팡 상품 상태 점검 — sellerProductId 기준으로 statusName, items 옵션 status 확인."""

import asyncio
import json
import sys

import asyncpg

sys.path.insert(0, "/app/backend")

from backend.core.config import settings  # noqa: E402
from backend.domain.samba.proxy.coupang import CoupangClient  # noqa: E402


SELLER_PRODUCT_ID = "16200437246"


async def main() -> None:
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    rows = await conn.fetch(
        """
        SELECT id, account_label, api_key, api_secret, seller_id, additional_fields
        FROM samba_market_account
        WHERE market_type = 'coupang' AND is_active = true
        ORDER BY created_at ASC
        """
    )
    await conn.close()

    if not rows:
        print("쿠팡 활성 계정 없음")
        return

    for row in rows:
        label = row["account_label"]
        extras = row["additional_fields"] or {}
        if isinstance(extras, str):
            try:
                extras = json.loads(extras)
            except Exception:
                extras = {}
        access_key = extras.get("accessKey") or row["api_key"]
        secret_key = extras.get("secretKey") or row["api_secret"]
        vendor_id = extras.get("vendorId") or row["seller_id"]
        if not (access_key and secret_key and vendor_id):
            print(f"[{label}] 인증정보 누락 skip")
            continue

        client = CoupangClient(access_key, secret_key, vendor_id)
        try:
            resp = await client.get_product(SELLER_PRODUCT_ID)
        except Exception as e:
            print(f"[{label}] 에러: {e}")
            continue

        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        status_name = data.get("statusName") if isinstance(data, dict) else None
        items = data.get("items") if isinstance(data, dict) else []
        print(f"\n===== 계정: {label} (vendor={vendor_id}) =====")
        print(f"statusName: {status_name}")
        print(f"items count: {len(items) if items else 0}")
        if items:
            for it in items:
                print(
                    f"  vendorItemId={it.get('vendorItemId')} "
                    f"itemName={it.get('itemName')} "
                    f"statusName={it.get('statusName')} "
                    f"salesStatus={it.get('salesStatus')} "
                    f"price={it.get('salePrice')}"
                )
        if status_name is not None or items:
            return

    print("\n어떤 계정에서도 해당 sellerProductId를 찾지 못했음")


if __name__ == "__main__":
    asyncio.run(main())
