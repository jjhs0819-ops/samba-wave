"""로컬 DB blocking 연결 정리"""
import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        host="localhost",
        port=5434,
        database="railway",
        user="postgres",
        password="gemini0674@@",
    )
    rows = await conn.fetch(
        "SELECT pid, state, left(query, 60) as q FROM pg_stat_activity"
        " WHERE datname = current_database() AND pid != pg_backend_pid()"
    )
    print(f"active connections: {len(rows)}")
    for r in rows:
        print(f"  pid={r['pid']} state={r['state']} q={r['q']}")

    killed = await conn.fetch(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
        " WHERE datname = current_database() AND pid != pg_backend_pid()"
    )
    print(f"terminated: {sum(1 for r in killed if r[0])}")
    await conn.close()


asyncio.run(main())
