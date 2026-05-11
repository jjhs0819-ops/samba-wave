"""프로덕션 DB 커넥션 풀 상태 점검 스크립트."""

import asyncio

import asyncpg

from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        ssl=False,
    )
    try:
        max_conn = await conn.fetchval("SHOW max_connections")
        total = await conn.fetchval("SELECT count(*) FROM pg_stat_activity")
        print(f"[전체] {total} / max_connections={max_conn}")

        print("\n[state 별 집계]")
        rows = await conn.fetch(
            """
      SELECT state, count(*) AS cnt
      FROM pg_stat_activity
      WHERE datname=$1
      GROUP BY state
      ORDER BY cnt DESC
      """,
            settings.db_name,
        )
        for r in rows:
            print(f"  {r['state']}: {r['cnt']}")

        print("\n[application_name × state]")
        rows = await conn.fetch(
            """
      SELECT application_name, state, count(*) AS cnt
      FROM pg_stat_activity
      WHERE datname=$1
      GROUP BY application_name, state
      ORDER BY cnt DESC
      """,
            settings.db_name,
        )
        for r in rows:
            print(f"  {r['application_name']!r:40s} {r['state']!s:25s} {r['cnt']}")

        print("\n[idle in transaction 상위 10건]")
        rows = await conn.fetch(
            """
      SELECT pid, application_name, state,
             EXTRACT(EPOCH FROM (now() - state_change))::int AS age_sec,
             LEFT(query, 120) AS q
      FROM pg_stat_activity
      WHERE datname=$1 AND state LIKE 'idle in transaction%'
      ORDER BY state_change ASC
      LIMIT 10
      """,
            settings.db_name,
        )
        for r in rows:
            print(
                f"  pid={r['pid']} age={r['age_sec']}s app={r['application_name']!r} q={r['q']!r}"
            )

        print("\n[active 쿼리 상위 10건 (오래 실행 중)]")
        rows = await conn.fetch(
            """
      SELECT pid, application_name,
             EXTRACT(EPOCH FROM (now() - query_start))::int AS age_sec,
             LEFT(query, 120) AS q
      FROM pg_stat_activity
      WHERE datname=$1 AND state='active' AND pid<>pg_backend_pid()
      ORDER BY query_start ASC
      LIMIT 10
      """,
            settings.db_name,
        )
        for r in rows:
            print(
                f"  pid={r['pid']} age={r['age_sec']}s app={r['application_name']!r} q={r['q']!r}"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
