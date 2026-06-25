"""idle in transaction 좀비 연결 정리."""
import asyncio, asyncpg, sys, os
sys.path.insert(0, "/app/backend")
os.chdir("/app/backend")
from backend.core.config import settings

async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    cnt = await conn.fetchval("""
        SELECT COUNT(*) FROM pg_stat_activity
        WHERE state = 'idle in transaction'
        AND datname = current_database()
        AND state_change < now() - interval '150 seconds'
    """)
    print(f"idle in transaction 연결: {cnt}개")

    killed = await conn.fetchval("""
        SELECT COUNT(pg_terminate_backend(pid))
        FROM pg_stat_activity
        WHERE state = 'idle in transaction'
        AND datname = current_database()
        AND pid <> pg_backend_pid()
        AND state_change < now() - interval '150 seconds'
    """)
    print(f"정리됨: {killed}개")

    remaining = await conn.fetchval("""
        SELECT COUNT(*) FROM pg_stat_activity
        WHERE state = 'idle in transaction'
        AND datname = current_database()
        AND state_change < now() - interval '150 seconds'
    """)
    print(f"잔여: {remaining}개")

    await conn.close()

asyncio.run(main())
