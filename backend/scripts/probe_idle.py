"""idle in transaction 점검 — 읽기 전용. 컨테이너 내 .venv python으로 실행."""

import asyncio

import asyncpg

from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        rows = await conn.fetch(
            """
            SELECT state,
                   count(*) AS cnt,
                   COALESCE(max(EXTRACT(EPOCH FROM (now() - state_change)))::int, 0) AS max_age_sec
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY state
            ORDER BY cnt DESC
            """
        )
        idle_tx = await conn.fetch(
            """
            SELECT pid,
                   EXTRACT(EPOCH FROM (now() - state_change))::int AS age_sec,
                   left(coalesce(query, ''), 80) AS q
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND state = 'idle in transaction'
            ORDER BY age_sec DESC
            LIMIT 10
            """
        )
        total = await conn.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        maxc = await conn.fetchval("SHOW max_connections")

        print(f"[STATE] total_conns={total} max_connections={maxc}")
        for r in rows:
            print(f"  {r['state']!s:30} cnt={r['cnt']:3d} max_age={r['max_age_sec']}s")
        print(f"[IDLE_IN_TX] count={len(idle_tx)} (top10)")
        for r in idle_tx:
            print(f"  pid={r['pid']} age={r['age_sec']}s q={r['q']!r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
