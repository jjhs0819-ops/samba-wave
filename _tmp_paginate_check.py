"""새 페이지네이션 코드가 이종영을 잡는지 검증 — SmartStoreClient.get_orders 직접 실행."""

import asyncio
import sys
sys.path.insert(0, "/app/backend")

from sqlalchemy import text
from backend.db.orm import get_read_session
from backend.domain.samba.proxy.smartstore import SmartStoreClient


TARGET = "2026051197491491"


async def main():
    async with get_read_session() as session:
        a = await session.execute(text("""
            SELECT additional_fields->>'clientId' AS cid,
                   additional_fields->>'clientSecret' AS csec
            FROM samba_market_account
            WHERE market_type='smartstore' AND seller_id='enclehhg@naver.com'
        """))
        cid, csec = a.fetchone()

    client = SmartStoreClient(cid, csec)

    print("=== get_orders(days=1) — 1일 윈도우 ===")
    orders_1d = await client.get_orders(days=1)
    ids_1d = []
    for o in orders_1d:
        po = o.get("productOrder", o) if isinstance(o, dict) else o
        pid = po.get("productOrderId")
        if pid:
            ids_1d.append(pid)
    print(f"총 {len(orders_1d)}건, 이종영 포함={TARGET in ids_1d}")
    print(f"productOrderIds: {ids_1d}")

    print("\n=== get_orders(days=5) — 5일 윈도우 ===")
    orders_5d = await client.get_orders(days=5)
    ids_5d = []
    for o in orders_5d:
        po = o.get("productOrder", o) if isinstance(o, dict) else o
        pid = po.get("productOrderId")
        if pid:
            ids_5d.append(pid)
    print(f"총 {len(orders_5d)}건, 이종영 포함={TARGET in ids_5d}")
    print(f"productOrderIds: {ids_5d}")


asyncio.run(main())
