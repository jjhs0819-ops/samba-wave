"""테트리스 배치 상태 진단 — 마켓 타입별 assignment 개수 + sync 설정."""

import asyncio
import asyncpg

from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host='172.18.0.2',
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1. tetris_sync_interval_hours 설정 — 테이블명 자동 탐지
        try:
            row = await conn.fetchrow(
                "SELECT value FROM samba_settings WHERE key='tetris_sync_interval_hours'"
            )
        except Exception:
            row = None
        if row is None:
            try:
                row = await conn.fetchrow(
                    "SELECT value FROM settings WHERE key='tetris_sync_interval_hours'"
                )
            except Exception:
                row = None
        print(f"\n[1] tetris_sync_interval_hours = {row['value'] if row else 'None'}")

        # 2. 마켓 타입별 assignment count
        print("\n[2] 마켓 타입별 assignment 개수:")
        rows = await conn.fetch(
            """
            SELECT a.market_type, COUNT(*) AS cnt
            FROM samba_tetris_assignment t
            JOIN samba_market_account a ON a.id = t.market_account_id
            GROUP BY a.market_type
            ORDER BY a.market_type
            """
        )
        for r in rows:
            print(f"  {r['market_type']}: {r['cnt']}건")

        # 3. 마켓 타입별 transmit job 상태
        print("\n[3] 현재 pending/running transmit 잡 (마켓 타입별):")
        rows = await conn.fetch(
            """
            SELECT
              ma.market_type,
              j.status,
              COUNT(*) AS cnt
            FROM samba_jobs j
            CROSS JOIN LATERAL jsonb_array_elements_text((j.payload::jsonb)->'target_account_ids') AS acc_id
            JOIN samba_market_account ma ON ma.id = acc_id
            WHERE j.job_type='transmit'
              AND j.status IN ('pending','running')
            GROUP BY ma.market_type, j.status
            ORDER BY ma.market_type, j.status
            """
        )
        for r in rows:
            print(f"  {r['market_type']} / {r['status']}: {r['cnt']}건")

        # 3-b. 가장 최근 transmit 잡 20건 — 타깃 계정/소싱처/브랜드/상태
        print("\n[3-b] 가장 최근 transmit 잡 20건:")
        rows = await conn.fetch(
            """
            SELECT
              j.id,
              j.status,
              j.created_at,
              (j.payload::jsonb)->>'source_site' AS site,
              (j.payload::jsonb)->>'brand_name' AS brand,
              (j.payload::jsonb)->>'target_account_ids' AS target_ids
            FROM samba_jobs j
            WHERE j.job_type='transmit'
            ORDER BY j.created_at DESC
            LIMIT 20
            """
        )
        for r in rows:
            print(f"  {r['created_at']} | {r['status']:10s} | {r['site']:10s}/{r['brand']:20s} → {r['target_ids']}")

        # 4. SS/11번가/롯데ON 배치 예시
        print("\n[4] SS/11번가/롯데ON 배치 sample (각 10건):")
        for mt in ('smartstore', '11st', 'lotteon'):
            rows = await conn.fetch(
                """
                SELECT t.source_site, t.brand_name, t.market_account_id, t.excluded, ma.account_label
                FROM samba_tetris_assignment t
                JOIN samba_market_account ma ON ma.id = t.market_account_id
                WHERE ma.market_type = $1
                LIMIT 10
                """,
                mt,
            )
            print(f"  -- {mt} --")
            for r in rows:
                print(f"    {r['source_site']}/{r['brand_name']} → {r['account_label']} excluded={r['excluded']}")

        # 5. SS/11번가/롯데ON 배치 중 미등록 상품 개수 (왜 잡이 안 생기는지)
        print("\n[5] SS/11번가/롯데ON 배치별 미등록 상품 수 (상위 10건):")
        rows = await conn.fetch(
            """
            SELECT
              ma.market_type,
              t.source_site,
              t.brand_name,
              ma.account_label,
              t.market_account_id,
              t.excluded,
              (SELECT COUNT(*)
                FROM samba_collected_product scp
                WHERE scp.source_site = t.source_site
                  AND BTRIM(scp.brand) = t.brand_name
                  AND (scp.registered_accounts IS NULL
                       OR NOT ((scp.registered_accounts::jsonb) ? t.market_account_id))
              ) AS unregistered_cnt
            FROM samba_tetris_assignment t
            JOIN samba_market_account ma ON ma.id = t.market_account_id
            WHERE ma.market_type IN ('smartstore','11st','lotteon')
            ORDER BY unregistered_cnt DESC
            LIMIT 30
            """
        )
        for r in rows:
            print(f"  {r['market_type']} {r['source_site']}/{r['brand_name']} → {r['account_label']} "
                  f"미등록={r['unregistered_cnt']} excluded={r['excluded']}")

        # 6. 최근 1시간 sync_all 로그 흔적 — pending/running 잡 created_at 기준
        print("\n[6] 최근 6시간 transmit 잡 생성 시간대별 (마켓 타입별):")
        rows = await conn.fetch(
            """
            SELECT
              ma.market_type,
              DATE_TRUNC('hour', j.created_at) AS hour,
              COUNT(*) AS cnt,
              MIN(j.created_at) AS first_at,
              MAX(j.created_at) AS last_at
            FROM samba_jobs j
            CROSS JOIN LATERAL jsonb_array_elements_text((j.payload::jsonb)->'target_account_ids') AS acc_id
            JOIN samba_market_account ma ON ma.id = acc_id
            WHERE j.job_type='transmit'
              AND j.created_at > NOW() - INTERVAL '6 hours'
            GROUP BY ma.market_type, DATE_TRUNC('hour', j.created_at)
            ORDER BY hour DESC, ma.market_type
            """
        )
        for r in rows:
            print(f"  {r['hour']} | {r['market_type']:12s} | {r['cnt']:4d}건 | first={r['first_at']} last={r['last_at']}")

        # [핵심 진단] 11번가 가디 잡 4건 + running 1건 상세 — 진짜 상태 확인
        print("\n[CORE] 11번가 가디-unclehg 타깃 잡 전수조사 (최근 6시간):")
        rows = await conn.fetch(
            """
            SELECT
              j.id, j.status, j.job_type, j.created_at, j.started_at, j.completed_at,
              j.current, j.total, j.error,
              (j.payload::jsonb)->>'source_site' AS site,
              (j.payload::jsonb)->>'brand_name' AS brand,
              jsonb_array_length((j.payload::jsonb)->'product_ids') AS pid_cnt
            FROM samba_jobs j
            WHERE j.job_type = 'transmit'
              AND (j.payload::jsonb)->>'target_account_ids' LIKE '%ma_01KQBJGJ0QGMZ5THS89RQ4VK47%'
              AND j.created_at > NOW() - INTERVAL '8 hours'
            ORDER BY j.created_at DESC
            """
        )
        for r in rows:
            print(f"  [{r['status']:10s}] {r['created_at']} | started={r['started_at']} | "
                  f"{r['site']}/{r['brand']} | {r['current']}/{r['total']} | pids={r['pid_cnt']} | err={r['error'][:80] if r['error'] else ''}")

        # 현재 워커 상태 — running 잡들이 모두 언제 시작됐는지
        print("\n[CORE-2] 현재 running 잡 전체:")
        rows = await conn.fetch(
            """
            SELECT
              j.id, j.job_type, j.created_at, j.started_at,
              j.current, j.total, j.progress,
              (j.payload::jsonb)->>'source_site' AS site,
              (j.payload::jsonb)->>'brand_name' AS brand,
              (j.payload::jsonb)->>'target_account_ids' AS targets
            FROM samba_jobs j
            WHERE j.status = 'running'
            ORDER BY j.started_at DESC NULLS LAST
            """
        )
        for r in rows:
            print(f"  {r['job_type']} | created={r['created_at']} started={r['started_at']} | "
                  f"{r['site']}/{r['brand']} | {r['current']}/{r['total']} ({r['progress']}%) | targets={r['targets']}")

        # 7-zero. 가디 계정 additional_fields 전체 (maxCount/tetrisAccountOrder)
        print("\n[7-zero] 11번가/SS/lotteon 계정 additional_fields (maxCount 등):")
        rows = await conn.fetch(
            """
            SELECT market_type, account_label, additional_fields
            FROM samba_market_account
            WHERE market_type IN ('smartstore','11st','lotteon','playauto','lottehome')
            ORDER BY market_type, account_label
            """
        )
        for r in rows:
            print(f"  {r['market_type']:12s} | {r['account_label']:35s} | {r['additional_fields']}")

        # 7-pre. 11번가/SS/lotteon 계정의 market_name 확인
        print("\n[7-pre] 11번가/SS/롯데ON 계정 market_name 매핑:")
        rows = await conn.fetch(
            """
            SELECT id, market_type, market_name, account_label
            FROM samba_market_account
            WHERE market_type IN ('smartstore','11st','lotteon','playauto','lottehome')
            ORDER BY market_type, account_label
            """
        )
        for r in rows:
            print(f"  {r['market_type']:12s} | name={r['market_name']!r:30s} | label={r['account_label']!r:30s} | id={r['id']}")

        # 7. assignment 생성 시간 (created_at)
        print("\n[7] SS/11번가/롯데ON assignment 생성 시간:")
        rows = await conn.fetch(
            """
            SELECT
              ma.market_type,
              t.source_site,
              t.brand_name,
              ma.account_label,
              t.excluded,
              t.created_at,
              t.updated_at
            FROM samba_tetris_assignment t
            JOIN samba_market_account ma ON ma.id = t.market_account_id
            WHERE ma.market_type IN ('smartstore','11st','lotteon','lottehome')
            ORDER BY t.created_at DESC
            """
        )
        for r in rows:
            print(f"  {r['created_at']} | {r['market_type']:10s} | {r['source_site']:10s}/{r['brand_name']:20s} → {r['account_label']:30s} excluded={r['excluded']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
