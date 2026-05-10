import asyncio
import asyncpg
import sys
import datetime

sys.path.insert(0, "/app/backend")
from backend.core.config import settings


async def main():
    s = settings
    now = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        conn = await asyncpg.connect(
            host=s.write_db_host,
            port=int(s.write_db_port),
            ssl=False,
            user=s.write_db_user,
            password=s.write_db_password,
            database=s.write_db_name,
        )
        rows = await conn.fetch("""
            SELECT state, count(*) as cnt,
                   max(now() - state_change) as max_idle
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY state ORDER BY cnt DESC
        """)
        total = await conn.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        iit = next((r["cnt"] for r in rows if r["state"] == "idle in transaction"), 0)
        active = next((r["cnt"] for r in rows if r["state"] == "active"), 0)
        max_iit = next(
            (r["max_idle"] for r in rows if r["state"] == "idle in transaction"), None
        )

        status = "OK" if total <= 35 and iit < 5 else "WARN"
        if total > 45 or iit >= 10:
            status = "CRIT"

        print(
            f"[{now}] {status} | 총={total}/35 active={active} idle_in_tx={iit} max_iit={str(max_iit)[:12] if max_iit else '-'}"
        )

        # 장기 active 쿼리 (3분+)
        long_rows = await conn.fetch("""
            SELECT pid, now() - state_change as dur, left(query, 80) as q
            FROM pg_stat_activity
            WHERE state = 'active' AND now() - state_change > interval '3 minutes'
              AND datname = current_database()
            ORDER BY dur DESC LIMIT 5
        """)
        for r in long_rows:
            print(f"  └ 장기쿼리 PID {r['pid']} {str(r['dur'])[:12]}  {r['q']}")

        # idle in transaction 세션의 마지막 쿼리
        if iit > 0:
            iit_rows = await conn.fetch("""
                SELECT pid, now() - state_change as dur, left(query, 100) as q
                FROM pg_stat_activity
                WHERE state = 'idle in transaction'
                  AND datname = current_database()
                ORDER BY dur DESC LIMIT 5
            """)
            for r in iit_rows:
                print(f"  └ [iit] PID {r['pid']} {str(r['dur'])[:12]}  {r['q']}")

        await conn.close()
    except Exception as e:
        print(f"[{now}] ERROR: {e}")


asyncio.run(main())
