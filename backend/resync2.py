import asyncio
import sys

sys.path.insert(0, ".")


async def main():
    import backend.main  # noqa: F401
    from sqlalchemy import text as t
    from backend.db.orm import get_write_session
    from backend.api.v1.routers.samba.order import (
        sync_orders_from_markets,
        SyncOrdersRequest,
    )

    async with get_write_session() as session:
        await sync_orders_from_markets(
            body=SyncOrdersRequest(days=7, account_id="ma_01KWVPQYKN4RRMVRKBF4DYV069"),
            session=session,
            tenant_id="tn_01KRX6H1Q97JGPXRPB011985QT",
        )
        r = await session.execute(
            t(
                "SELECT order_number, ship_by_at, estimated_delivery_at, shipping_service_code "
                "FROM samba_order WHERE source='ebay' ORDER BY created_at DESC LIMIT 10"
            )
        )
        for row in r.fetchall():
            print(row)


asyncio.run(main())
