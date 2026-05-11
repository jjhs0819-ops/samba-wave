"""11번가 가디 잡 실패 원인 추적."""

import asyncio
import json
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
        target = "ma_01KQBJGJ0QGMZ5THS89RQ4VK47"

        # 가장 최근 completed 11번가 가디 잡의 logs (실제 실패 메시지)
        print("\n[1] 최근 completed 11번가 가디 LOTTEON/나이키 잡 logs (마지막 30줄):")
        row = await conn.fetchrow(
            """
            SELECT id, logs::text AS logs_text
            FROM samba_jobs
            WHERE job_type='transmit'
              AND status='completed'
              AND (payload::jsonb)->>'target_account_ids' LIKE '%' || $1 || '%'
              AND (payload::jsonb)->>'brand_name' = '나이키'
              AND (payload::jsonb)->>'source_site' = 'LOTTEON'
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            target,
        )
        if row:
            try:
                logs = json.loads(row["logs_text"]) if row["logs_text"] else []
                if isinstance(logs, list):
                    for line in logs[-30:]:
                        print(f"  {line}")
                else:
                    print(f"  logs not list: {logs}")
            except Exception as e:
                print(
                    f"  parse error: {e}, raw len={len(row['logs_text']) if row['logs_text'] else 0}"
                )
                print(f"  raw[:500]: {(row['logs_text'] or '')[:500]}")
        else:
            print("  (no completed job)")

        # 11번가 가디 외 다른 11번가 계정 잡 결과 — 동일 실패인지 가디만 실패인지
        print("\n[2] 다른 11번가 계정들 최근 잡 결과 (실패 여부 비교):")
        rows = await conn.fetch(
            """
            SELECT
              ma.account_label,
              j.id,
              (j.payload::jsonb)->>'source_site' AS site,
              (j.payload::jsonb)->>'brand_name' AS brand,
              j.current, j.total, j.result
            FROM samba_jobs j
            CROSS JOIN LATERAL jsonb_array_elements_text((j.payload::jsonb)->'target_account_ids') AS acc_id
            JOIN samba_market_account ma ON ma.id = acc_id
            WHERE ma.market_type='11st'
              AND j.job_type='transmit'
              AND j.status='completed'
              AND j.completed_at > NOW() - INTERVAL '24 hours'
            ORDER BY j.completed_at DESC
            LIMIT 10
            """
        )
        for r in rows:
            print(
                f"  {r['account_label']:25s} | {r['site']}/{r['brand']:20s} | "
                f"{r['current']}/{r['total']} | {r['result']}"
            )

        # 11번가 가디 외 SS/lotteon completed 잡 결과 — 같은 fail 패턴인지
        print("\n[3] SS/lotteon 가디 계정 최근 completed 잡:")
        for label in ("가디-enclehhg@naver.com", "가디-unclehg"):
            rows = await conn.fetch(
                """
                SELECT
                  ma.market_type, ma.account_label,
                  (j.payload::jsonb)->>'source_site' AS site,
                  (j.payload::jsonb)->>'brand_name' AS brand,
                  j.current, j.total, j.result
                FROM samba_jobs j
                CROSS JOIN LATERAL jsonb_array_elements_text((j.payload::jsonb)->'target_account_ids') AS acc_id
                JOIN samba_market_account ma ON ma.id = acc_id
                WHERE ma.account_label = $1
                  AND j.job_type='transmit'
                  AND j.status='completed'
                  AND j.completed_at > NOW() - INTERVAL '12 hours'
                ORDER BY j.completed_at DESC
                LIMIT 5
                """,
                label,
            )
            for r in rows:
                print(
                    f"  {r['market_type']:10s} {r['account_label']:25s} | {r['site']}/{r['brand']:20s} | "
                    f"{r['current']}/{r['total']} | {r['result']}"
                )

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
