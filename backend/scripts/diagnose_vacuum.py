"""autovacuum 진행 상태 + 영향 쿼리 확인"""
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

    # autovacuum 진행 상태
    print("=== autovacuum 진행 상태 ===")
    vac = await conn.fetchrow("""
        SELECT pid,
               phase,
               heap_blks_total,
               heap_blks_scanned,
               heap_blks_vacuumed,
               index_vacuum_count,
               num_dead_tuples,
               max_dead_tuples
        FROM pg_stat_progress_vacuum
        WHERE relid = 'samba_collected_product'::regclass
    """)
    if vac:
        pct = round(vac['heap_blks_scanned'] / max(vac['heap_blks_total'], 1) * 100, 1)
        print(f"  pid={vac['pid']} phase={vac['phase']}")
        print(f"  블록: scanned={vac['heap_blks_scanned']}/{vac['heap_blks_total']} ({pct}%)")
        print(f"  dead_tuples: {vac['num_dead_tuples']}/{vac['max_dead_tuples']}")
        print(f"  index_vacuum_count: {vac['index_vacuum_count']}")
    else:
        print("  autovacuum 종료됨 (현재 실행 중 아님)")

    # 현재 테이블 bloat
    print("\n=== 테이블 dead tuple 현황 ===")
    stats = await conn.fetchrow("""
        SELECT n_live_tup, n_dead_tup,
               round(n_dead_tup::numeric / NULLIF(n_live_tup, 0) * 100, 1) as bloat_pct,
               last_autovacuum, last_autoanalyze
        FROM pg_stat_user_tables
        WHERE relname = 'samba_collected_product'
    """)
    print(f"  live={stats['n_live_tup']} dead={stats['n_dead_tup']} bloat={stats['bloat_pct']}%")
    print(f"  last_autovacuum={stats['last_autovacuum']}")
    print(f"  last_autoanalyze={stats['last_autoanalyze']}")

    # 현재 active 쿼리 (IO 대기 포함)
    print("\n=== 현재 active 쿼리 전체 ===")
    active = await conn.fetch("""
        SELECT pid,
               extract(epoch from now() - query_start)::int as dur_sec,
               wait_event_type, wait_event,
               left(query, 150) as q
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND state = 'active'
          AND pid != pg_backend_pid()
        ORDER BY dur_sec DESC NULLS LAST
    """)
    for r in active:
        print(f"  pid={r['pid']} dur={r['dur_sec']}s wait={r['wait_event_type']}/{r['wait_event']}")
        print(f"    {r['q']}")

    await conn.close()


asyncio.run(main())
