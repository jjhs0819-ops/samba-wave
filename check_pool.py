import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    c = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    db_name = settings.write_db_name
    rows = await c.fetch(
        "SELECT state, COUNT(*) AS cnt FROM pg_stat_activity "
        "WHERE datname=$1 GROUP BY state ORDER BY cnt DESC",
        db_name,
    )
    print("--- state breakdown ---")
    for r in rows:
        print(f"{r['state']!r:30s} {r['cnt']}")

    total = await c.fetchval(
        "SELECT COUNT(*) FROM pg_stat_activity WHERE datname=$1",
        db_name,
    )
    mx = await c.fetchval("SHOW max_connections")
    print(f"total={total}  max_connections={mx}")

    print("--- idle in transaction (oldest 10) ---")
    rows = await c.fetch(
        "SELECT pid, EXTRACT(EPOCH FROM (now()-state_change))::int AS sec, "
        "LEFT(query, 120) AS q FROM pg_stat_activity "
        "WHERE state='idle in transaction' AND datname=$1 "
        "ORDER BY state_change LIMIT 10",
        db_name,
    )
    for r in rows:
        print(f"pid={r['pid']:>7} {r['sec']:>5}s | {r['q']}")

    print("--- active (oldest 10) ---")
    rows = await c.fetch(
        "SELECT pid, EXTRACT(EPOCH FROM (now()-query_start))::int AS sec, "
        "LEFT(query, 120) AS q FROM pg_stat_activity "
        "WHERE state='active' AND datname=$1 "
        "ORDER BY query_start LIMIT 10",
        db_name,
    )
    for r in rows:
        print(f"pid={r['pid']:>7} {r['sec']:>5}s | {r['q']}")

    print("--- by application_name ---")
    rows = await c.fetch(
        "SELECT application_name, state, COUNT(*) AS cnt FROM pg_stat_activity "
        "WHERE datname=$1 GROUP BY application_name, state ORDER BY cnt DESC LIMIT 15",
        db_name,
    )
    for r in rows:
        print(f"{r['application_name']!r:40s} {r['state']!r:25s} {r['cnt']}")

    await c.close()


asyncio.run(main())
