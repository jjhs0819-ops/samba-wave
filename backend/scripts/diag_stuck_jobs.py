"""좀비 transmit 잡 진단 — pending인데 current>0이거나 row lock 잡힌 잡."""

import asyncio
import asyncpg

from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        print("\n[A] pending 잡 중 current>0 (좀비 후보):")
        rows = await conn.fetch(
            """
            SELECT id, job_type, status, created_at, started_at, current, total,
                   (payload::jsonb)->>'source_site' AS site,
                   (payload::jsonb)->>'brand_name' AS brand,
                   (payload::jsonb)->>'target_account_ids' AS targets
            FROM samba_jobs
            WHERE status='pending' AND current > 0
            ORDER BY created_at ASC
            """
        )
        for r in rows:
            print(
                f"  {r['id'][:12]} | {r['site']}/{r['brand']} → {r['targets']} | "
                f"current={r['current']}/{r['total']} | created={r['created_at']} started={r['started_at']}"
            )

        print("\n[B] pending 잡이 lock 잡혀있는지 (pg_locks 조회):")
        rows = await conn.fetch(
            """
            SELECT l.locktype, l.mode, l.granted, l.pid,
                   a.state, a.query_start, a.xact_start,
                   substring(a.query, 1, 100) AS query_snip,
                   a.application_name
            FROM pg_locks l
            JOIN pg_stat_activity a ON a.pid = l.pid
            WHERE l.relation = 'samba_jobs'::regclass
              AND a.state <> 'active'
            ORDER BY a.xact_start ASC NULLS LAST
            LIMIT 20
            """
        )
        for r in rows:
            print(
                f"  pid={r['pid']} {r['locktype']}/{r['mode']} granted={r['granted']} "
                f"state={r['state']} xact_start={r['xact_start']} app={r['application_name']}"
            )
            print(f"    query: {r['query_snip']}")

        print("\n[C] idle in transaction 좀비 연결 (samba_jobs 관련):")
        rows = await conn.fetch(
            """
            SELECT pid, state, query_start, xact_start, state_change,
                   substring(query, 1, 200) AS query_snip
            FROM pg_stat_activity
            WHERE state = 'idle in transaction'
              AND xact_start < NOW() - INTERVAL '1 minute'
            ORDER BY xact_start ASC
            LIMIT 20
            """
        )
        for r in rows:
            print(
                f"  pid={r['pid']} state={r['state']} xact_start={r['xact_start']} state_change={r['state_change']}"
            )
            print(f"    query: {r['query_snip']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
