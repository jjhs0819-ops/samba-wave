"""GSShop 1112115252 상품의 last_sent_data 등 확인"""

import asyncio
import asyncpg
import json
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    # site_product_id로 검색
    rows = await conn.fetch(
        """
        SELECT id, source_site, site_product_id, name, sale_status,
               registered_accounts, market_product_nos, last_sent_data,
               sale_price, cost, price_changed_at
        FROM samba_collected_product
        WHERE site_product_id = $1 AND source_site = 'GSShop'
        LIMIT 5
        """,
        "1112115252",
    )
    for r in rows:
        print(
            f"id={r['id']} site_product_id={r['site_product_id']} name={r['name'][:40]}"
        )
        print(
            f"  sale_status={r['sale_status']} sale_price={r['sale_price']} cost={r['cost']}"
        )
        print(f"  registered_accounts={r['registered_accounts']}")
        print(f"  market_product_nos={r['market_product_nos']}")
        lsd = r["last_sent_data"]
        if isinstance(lsd, str):
            try:
                lsd = json.loads(lsd)
            except Exception:
                pass
        print(
            f"  last_sent_data keys={list(lsd.keys()) if isinstance(lsd, dict) else lsd}"
        )
        if isinstance(lsd, dict):
            for k, v in lsd.items():
                if isinstance(v, dict):
                    print(
                        f"    {k}: sale_price={v.get('sale_price')} cost={v.get('cost')} sent_at={v.get('sent_at')} failed_at={v.get('failed_at')}"
                    )
                else:
                    print(f"    {k}: {v}")
        print(f"  price_changed_at={r['price_changed_at']}")

    # 추가로 다른 GSShop 0원 변동 상품 5건 확인
    print("\n=== 최근 GSShop price_changed 이벤트 (warroom monitor_event) ===")
    events = await conn.fetch(
        """
        SELECT created_at, product_id, summary, detail
        FROM samba_monitor_event
        WHERE source_site = 'GSShop' AND event_type = 'price_changed'
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    for e in events:
        d = e["detail"]
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except Exception:
                pass
        print(
            f"{e['created_at']} pid={e['product_id']} old={d.get('old_price') if isinstance(d, dict) else None} new={d.get('new_price') if isinstance(d, dict) else None}"
        )

    await conn.close()


asyncio.run(main())
