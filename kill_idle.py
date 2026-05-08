import asyncio
import asyncpg
from backend.core.config import settings

async def main():
    conn = await asyncpg.connect(
        host='172.18.0.2', port=5432, ssl=False,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name,
    )
    rows = await conn.fetch("""
        SELECT pid, state, wait_event_type, wait_event,
               now() - xact_start AS duration, query
        FROM pg_stat_activity
        WHERE state = 'idle in transaction'
        ORDER BY duration DESC
    """)
    print(f"idle in transaction: {len(rows)}개")
    for r in rows:
        print(f"  pid={r['pid']} duration={r['duration']} query={str(r['query'])[:120]}")

    killed = await conn.fetch("""
        SELECT pid, pg_terminate_backend(pid) AS killed
        FROM pg_stat_activity
        WHERE state = 'idle in transaction'
    """)
    remaining = sum(1 for r in killed if not r['killed'])
    print(f"정리 완료: {len(killed)}개 종료, remaining={remaining}")
    await conn.close()

asyncio.run(main())
