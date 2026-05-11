"""GSShop 재고 이벤트 진단 — sold_out/restock 발생 여부 확인."""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )
    try:
        # 1. GSShop 상품의 sale_status 분포
        rows = await conn.fetch(
            """
            SELECT sale_status, COUNT(*) AS cnt
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            GROUP BY sale_status
            """
        )
        print("[1] GSShop sale_status 분포:")
        for r in rows:
            print(f"  {r['sale_status']}: {r['cnt']:,}")

        # 2. 최근 24h GSShop 이벤트 type별 분포
        rows = await conn.fetch(
            """
            SELECT event_type, COUNT(*) AS cnt
            FROM samba_monitor_event
            WHERE source_site = 'GSShop'
              AND created_at >= NOW() - INTERVAL '24 hours'
            GROUP BY event_type
            ORDER BY cnt DESC
            """
        )
        print("\n[2] 최근 24h GSShop 이벤트(source_site='GSShop') 분포:")
        for r in rows:
            print(f"  {r['event_type']}: {r['cnt']:,}")

        # 3. source_site 값이 GSSHOP 외 다른 표기로 저장됐는지
        rows = await conn.fetch(
            """
            SELECT DISTINCT source_site
            FROM samba_monitor_event
            WHERE source_site ILIKE '%gs%'
              AND created_at >= NOW() - INTERVAL '7 days'
            """
        )
        print("\n[3] 최근 7일 monitor_event에 저장된 GS 관련 source_site 표기:")
        for r in rows:
            print(f"  '{r['source_site']}'")

        # 4. 전체 7일 GSShop 이벤트 타입별 (sold_out / restock이 한 번이라도 있었는지)
        rows = await conn.fetch(
            """
            SELECT event_type, COUNT(*) AS cnt, MAX(created_at) AS last_at
            FROM samba_monitor_event
            WHERE source_site = 'GSShop'
              AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY event_type
            ORDER BY cnt DESC
            """
        )
        print("\n[4] 최근 7일 GSShop 이벤트 타입별:")
        for r in rows:
            print(f"  {r['event_type']}: {r['cnt']:,}건 (최근: {r['last_at']})")

        # 5. 최근 GSShop sold_out 이벤트 샘플 5건
        rows = await conn.fetch(
            """
            SELECT id, event_type, summary, source_site, created_at, detail
            FROM samba_monitor_event
            WHERE source_site = 'GSShop'
              AND event_type IN ('sold_out', 'restock')
            ORDER BY created_at DESC
            LIMIT 5
            """
        )
        print("\n[5] GSShop sold_out/restock 최근 5건:")
        for r in rows:
            print(
                f"  {r['created_at']} | {r['event_type']} | {r['summary'][:60] if r['summary'] else ''}"
            )

        # 6. GSShop scheduler_tick의 stock_changed_items 샘플
        rows = await conn.fetch(
            """
            SELECT created_at, detail
            FROM samba_monitor_event
            WHERE source_site = 'GSShop'
              AND event_type = 'scheduler_tick'
              AND created_at >= NOW() - INTERVAL '12 hours'
            ORDER BY created_at DESC
            LIMIT 3
            """
        )
        print("\n[6] GSShop 최근 scheduler_tick의 stock_changed_items:")
        for r in rows:
            d = r["detail"] or {}
            items = d.get("stock_changed_items") or []
            print(f"  {r['created_at']} stock_items={len(items)} sample={items[:2]}")

        # 7. GSShop 품절 상품의 options 구조 샘플
        rows = await conn.fetch(
            """
            SELECT id, site_product_id, sale_status, options
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
              AND sale_status = 'sold_out'
            LIMIT 3
            """
        )
        print("\n[7] GSShop sold_out 상품 옵션 샘플:")
        for r in rows:
            opts = r["options"] or []
            print(
                f"  {r['site_product_id']} sale_status={r['sale_status']} options_len={len(opts)} first={opts[:1] if opts else 'EMPTY'}"
            )

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
