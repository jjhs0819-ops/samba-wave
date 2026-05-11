"""GSShop 오토튠 활성도 진단 — 왜 갱신이 거의 안 일어나는지."""

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
        print("[1] 소싱처별 최근 1시간 갱신 활성도 (last_refreshed_at):")
        rows = await conn.fetch(
            """
            SELECT
              source_site,
              COUNT(*) FILTER (WHERE last_refreshed_at >= NOW() - INTERVAL '1 hour') AS r_1h,
              COUNT(*) FILTER (WHERE last_refreshed_at >= NOW() - INTERVAL '24 hours') AS r_24h,
              COUNT(*) FILTER (WHERE last_refreshed_at IS NULL) AS r_null,
              COUNT(*) AS total
            FROM samba_collected_product
            WHERE source_site IS NOT NULL
            GROUP BY source_site
            ORDER BY total DESC
            """
        )
        print(
            f"  {'소싱처':<15} {'1h 갱신':>10} {'24h 갱신':>10} {'NULL':>10} {'전체':>10}"
        )
        for r in rows:
            print(
                f"  {r['source_site']:<15} {r['r_1h']:>10,} {r['r_24h']:>10,} {r['r_null']:>10,} {r['total']:>10,}"
            )

        print("\n[2] GSShop scheduler_tick 최근 1시간 detail (대상 / 성공 / 실패):")
        rows = await conn.fetch(
            """
            SELECT created_at, detail
            FROM samba_monitor_event
            WHERE source_site = 'GSShop' AND event_type = 'scheduler_tick'
              AND created_at >= NOW() - INTERVAL '1 hour'
            ORDER BY created_at DESC
            LIMIT 5
            """
        )
        for r in rows:
            d = r["detail"] or {}
            print(
                f"  {r['created_at']} 대상={d.get('total', '?')} 성공={d.get('success', '?')} 실패={d.get('fail', '?')} 품절={d.get('sold_out', '?')}"
            )

        print("\n[3] GSShop 갱신 후보 (오토튠이 picks up 하는 조건):")
        # 등록된 상품 우선 갱신 — registered_accounts 비어있는지가 핵심
        rows = await conn.fetch(
            """
            SELECT
              COUNT(*) FILTER (WHERE jsonb_array_length(registered_accounts)=0) AS no_reg,
              COUNT(*) FILTER (WHERE jsonb_array_length(registered_accounts)>0) AS has_reg,
              COUNT(*) FILTER (WHERE monitor_priority IS NULL OR monitor_priority='') AS prio_null,
              COUNT(*) AS total
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            """
        )
        for r in rows:
            print(f"  registered_accounts 비어있음: {r['no_reg']:,}")
            print(f"  registered_accounts 있음(등록상품): {r['has_reg']:,}")
            print(f"  monitor_priority null: {r['prio_null']:,}")
            print(f"  전체: {r['total']:,}")

        print("\n[4] GSShop monitor_priority 분포 (오토튠 hot/warm/cold 분류):")
        rows = await conn.fetch(
            """
            SELECT monitor_priority, COUNT(*) AS cnt
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            GROUP BY monitor_priority
            ORDER BY cnt DESC
            """
        )
        for r in rows:
            print(f"  {r['monitor_priority']!r}: {r['cnt']:,}")

        print("\n[5] GSShop이 오토튠 사이클에 포함되는지 (잡 큐):")
        rows = await conn.fetch(
            """
            SELECT type, status, COUNT(*) AS cnt, MAX(created_at) AS last_at
            FROM samba_job
            WHERE source_site = 'GSShop'
              AND created_at >= NOW() - INTERVAL '24 hours'
            GROUP BY type, status
            ORDER BY type, status
            """
        )
        for r in rows:
            print(
                f"  type={r['type']} status={r['status']} cnt={r['cnt']:,} last={r['last_at']}"
            )

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
