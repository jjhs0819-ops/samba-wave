"""prdSaleSt='N'인데 DB에 in_stock으로 박힌 7개 상품 추적."""

import asyncio
import asyncpg
from backend.core.config import settings


TARGET_SIDS = ["1112110383", "1087855260", "1114487228", "1109469662", "1093609852"]


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2", port=5432,
        user=settings.read_db_user, password=settings.read_db_password,
        database=settings.read_db_name, ssl=False,
    )
    try:
        print(f"[추적] {len(TARGET_SIDS)}개 prdSaleSt='N' 상품의 DB 상태")
        rows = await conn.fetch(
            """
            SELECT site_product_id, name, sale_status, last_refreshed_at, created_at,
                   sale_price, cost,
                   registered_accounts, monitor_priority
            FROM samba_collected_product
            WHERE source_site='GSShop' AND site_product_id = ANY($1::text[])
            """,
            TARGET_SIDS,
        )
        for r in rows:
            print(f"\n  sid={r['site_product_id']}")
            print(f"    name: {(r['name'] or '')[:50]!r}")
            print(f"    sale_status: {r['sale_status']}")
            print(f"    last_refreshed_at: {r['last_refreshed_at']}")
            print(f"    created_at: {r['created_at']}")
            print(f"    sale_price={r['sale_price']} cost={r['cost']}")
            print(f"    monitor_priority: {r['monitor_priority']}")
            print(f"    registered_accounts(json): {str(r['registered_accounts'])[:80]}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
