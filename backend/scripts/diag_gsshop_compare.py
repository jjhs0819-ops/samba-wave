"""GSShop vs 다른 소싱처 sale_status / 이벤트 분포 비교."""

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
        print("[1] 소싱처별 sale_status 분포 (현재 DB 스냅샷):")
        rows = await conn.fetch(
            """
            SELECT source_site, sale_status, COUNT(*) AS cnt
            FROM samba_collected_product
            WHERE source_site IS NOT NULL
            GROUP BY source_site, sale_status
            ORDER BY source_site, cnt DESC
            """
        )
        cur = None
        for r in rows:
            if r['source_site'] != cur:
                print(f"\n  [{r['source_site']}]")
                cur = r['source_site']
            print(f"    {r['sale_status']}: {r['cnt']:,}")

        print("\n[2] 소싱처별 최근 7일 이벤트 타입 분포:")
        rows = await conn.fetch(
            """
            SELECT source_site, event_type, COUNT(*) AS cnt
            FROM samba_monitor_event
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND event_type IN ('price_changed', 'sold_out', 'restock')
              AND source_site IS NOT NULL
            GROUP BY source_site, event_type
            ORDER BY source_site, event_type
            """
        )
        cur = None
        for r in rows:
            if r['source_site'] != cur:
                print(f"\n  [{r['source_site']}]")
                cur = r['source_site']
            print(f"    {r['event_type']}: {r['cnt']:,}")

        print("\n[3] GSShop 영구 삭제(deleted_from_source) 사례 흔적 — detail.reason='source_deleted' 이벤트:")
        rows = await conn.fetch(
            """
            SELECT COUNT(*) AS cnt
            FROM samba_monitor_event
            WHERE source_site = 'GSShop'
              AND event_type = 'sold_out'
              AND detail->>'reason' = 'source_deleted'
            """
        )
        for r in rows:
            print(f"    GSShop source_deleted 이벤트: {r['cnt']:,}")

        print("\n[4] GSShop last_refreshed_at 분포 (오토튠 갱신 활성도):")
        rows = await conn.fetch(
            """
            SELECT
              COUNT(*) FILTER (WHERE last_refreshed_at >= NOW() - INTERVAL '24 hours') AS r_24h,
              COUNT(*) FILTER (WHERE last_refreshed_at >= NOW() - INTERVAL '7 days') AS r_7d,
              COUNT(*) FILTER (WHERE last_refreshed_at IS NULL) AS r_null,
              COUNT(*) AS total
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            """
        )
        for r in rows:
            print(f"    24h 갱신: {r['r_24h']:,} / 7d 갱신: {r['r_7d']:,} / null: {r['r_null']:,} / 전체: {r['total']:,}")

        print("\n[5] GSShop scheduler_tick의 summary(소싱처삭제/품절 카운트)에서 sold_out 카운트 합산:")
        rows = await conn.fetch(
            """
            SELECT
              COALESCE(SUM((detail->>'sold_out')::int), 0) AS sum_so,
              COALESCE(SUM((detail->>'success')::int), 0) AS sum_ok,
              COALESCE(SUM((detail->>'fail')::int), 0) AS sum_fail,
              COUNT(*) AS tick_count
            FROM samba_monitor_event
            WHERE source_site = 'GSShop'
              AND event_type = 'scheduler_tick'
              AND created_at >= NOW() - INTERVAL '7 days'
            """
        )
        for r in rows:
            print(f"    최근 7일 GSShop tick={r['tick_count']:,}, sold_out 합계={r['sum_so']:,}, success={r['sum_ok']:,}, fail={r['sum_fail']:,}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
