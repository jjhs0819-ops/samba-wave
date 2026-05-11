"""드릴다운 느린 쿼리 진단"""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )

    print("=== 현재 active 쿼리 ===")
    rows = await conn.fetch("""
        SELECT pid,
               extract(epoch from now() - query_start)::int as dur_sec,
               wait_event_type, wait_event,
               left(query, 300) as q
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND state = 'active'
          AND pid != pg_backend_pid()
        ORDER BY dur_sec DESC NULLS LAST
        LIMIT 15
    """)
    for r in rows:
        print(
            f"  pid={r['pid']} dur={r['dur_sec']}s wait={r['wait_event_type']}/{r['wait_event']}"
        )
        print(f"    {r['q']}")

    print("\n=== 연결 상태 요약 ===")
    rows2 = await conn.fetch("""
        SELECT state, count(*) cnt
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid != pg_backend_pid()
        GROUP BY state ORDER BY cnt DESC
    """)
    for r in rows2:
        print(f"  {r['state']}: {r['cnt']}")

    print("\n=== filters/tree 관련 인덱스 사용 확인 ===")
    # tags GIN 인덱스가 제대로 만들어졌는지 확인
    idx = await conn.fetch("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'samba_collected_product'
          AND indexname IN ('ix_scp_tags_gin', 'ix_scp_registered_accounts_gin',
                           'ix_samba_collected_product_is_unregistered')
    """)
    for r in idx:
        print(f"  {r['indexname']}: {r['indexdef'][:80]}")

    # EXPLAIN 드릴다운 쿼리 시뮬레이션
    print("\n=== EXPLAIN: tags GIN 인덱스 사용 여부 ===")
    plan = await conn.fetch("""
        EXPLAIN (FORMAT TEXT, ANALYZE FALSE)
        SELECT
            source_site,
            BTRIM(brand) AS effective_brand,
            COUNT(*) AS cnt,
            COUNT(*) FILTER (WHERE is_unregistered = FALSE) AS registered_cnt,
            COUNT(*) FILTER (WHERE sale_status = 'sold_out') AS sold_out_cnt,
            COUNT(*) FILTER (
                WHERE tags @> '["__ai_tagged__"]'::jsonb
            ) AS ai_tagged_cnt
        FROM samba_collected_product
        WHERE tags IS NOT NULL
          AND jsonb_array_length(tags) > 0
        GROUP BY source_site, BTRIM(brand)
        ORDER BY source_site, cnt DESC
    """)
    for r in plan:
        print(f"  {r[0]}")

    await conn.close()


asyncio.run(main())
