"""프로덕션 DB idle in transaction 모니터링"""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 전체 연결 상태별 카운트
        rows = await conn.fetch(
            """
            SELECT state, COUNT(*) AS cnt
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY state
            ORDER BY cnt DESC
            """
        )
        print("=== 연결 상태별 카운트 ===")
        total = 0
        for r in rows:
            state = r["state"] or "(null)"
            print(f"  {state:<32s} : {r['cnt']:>4d}")
            total += r["cnt"]
        print(f"  {'TOTAL':<32s} : {total:>4d}")

        # idle in transaction 상세
        idle_rows = await conn.fetch(
            """
            SELECT
                pid,
                application_name,
                client_addr,
                EXTRACT(EPOCH FROM (now() - state_change))::int AS idle_sec,
                EXTRACT(EPOCH FROM (now() - xact_start))::int  AS xact_sec,
                LEFT(query, 120) AS query
            FROM pg_stat_activity
            WHERE state = 'idle in transaction'
              AND datname = current_database()
            ORDER BY state_change ASC
            """
        )
        print(f"\n=== idle in transaction 상세 ({len(idle_rows)}건) ===")
        for r in idle_rows:
            print(
                f"  pid={r['pid']:>6d} idle={r['idle_sec']:>5d}s xact={r['xact_sec']:>5d}s "
                f"app={r['application_name'][:20]:<20s} addr={str(r['client_addr'] or ''):<15s}"
            )
            if r["query"]:
                print(f"    query: {r['query']}")

        # 오래된 트랜잭션 경고 (5분 이상 — PG idle_in_transaction_session_timeout=60s를 넘긴 진짜 좀비)
        long_idle = [r for r in idle_rows if (r["idle_sec"] or 0) >= 300]
        if long_idle:
            print(
                f"\n[!] 5분 이상 idle 트랜잭션 {len(long_idle)}건 — 좀비 의심 (PG 1분 timeout 회피)"
            )
        else:
            print("\n[OK] 5분 이상 idle 트랜잭션 없음")

        # 최대 연결수 대비 사용률
        max_conn_row = await conn.fetchrow("SHOW max_connections")
        max_conn = int(max_conn_row["max_connections"])
        usage_pct = (total / max_conn) * 100 if max_conn else 0
        print("\n=== 연결 사용률 ===")
        print(f"  {total} / {max_conn}  ({usage_pct:.1f}%)")
        if usage_pct >= 80:
            print("[!] 연결 사용률 80% 초과 — 풀 고갈 임박")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
