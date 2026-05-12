"""이종영 주문 발주확인 호출 — placeOrderStatus NOT_YET → OK 전이로 lastChanged 이벤트 갱신."""

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session
from backend.domain.samba.proxy.smartstore import SmartStoreClient


TARGET = "2026051197491491"


async def main():
    async with get_read_session() as session:
        row = await session.execute(
            text(
                """
                SELECT additional_fields->>'clientId' AS cid,
                       additional_fields->>'clientSecret' AS csec
                FROM samba_market_account
                WHERE market_type='smartstore' AND seller_id='enclehhg@naver.com'
                """
            )
        )
        cid, csec = row.fetchone()

    client = SmartStoreClient(cid, csec)

    print(f"발주확인 호출: productOrderId={TARGET}")
    try:
        result = await client.confirm_product_orders([TARGET])
        import json
        print("응답:")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:2000])
    except Exception as e:
        print(f"ERROR: {e}")
        return

    # 발주확인 후 placeOrderStatus 재확인
    print("\n발주확인 후 상태 재조회:")
    raws = await client.get_product_orders_by_ids([TARGET])
    if raws:
        po = raws[0].get("productOrder", raws[0])
        print(f"  placeOrderStatus: {po.get('placeOrderStatus')}")
        print(f"  productOrderStatus: {po.get('productOrderStatus')}")


asyncio.run(main())
