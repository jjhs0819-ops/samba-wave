"""11번가 가디 계정에 실제 등록된 상품 수 확인."""

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
        target = "ma_01KQBJGJ0QGMZ5THS89RQ4VK47"  # 11st 가디-unclehg

        print(f"\n[X] 11번가 가디({target}) registered_accounts 포함 상품 수 (마켓별 매핑 테이블 있는지):")
        # market_product_mapping 같은 테이블이 있는지 우선 확인
        rows = await conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name LIKE '%market%product%mapping%'
            """
        )
        for r in rows:
            print(f"  table: {r['table_name']}")

        # registered_accounts JSONB 포함 상품 수
        print(f"\n[Y] registered_accounts에 {target} 포함된 상품 수:")
        cnt = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE registered_accounts IS NOT NULL
              AND (registered_accounts::jsonb) ? $1
            """,
            target,
        )
        print(f"  {cnt}건")

        # 11번가 가디 정책 매핑 검증 — 마켓 API 호출 가능한 상태인지
        print(f"\n[Z] samba_market_product_mapping 류 테이블 전체:")
        rows = await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public'
              AND (table_name LIKE 'samba_market%' OR table_name LIKE 'samba_mp%')
            ORDER BY table_name
            """
        )
        for r in rows:
            print(f"  {r['table_name']}")

        # samba_jobs result 필드 확인 — 최근 completed 11번가 가디 잡 result
        print(f"\n[W] 최근 completed 11번가 가디 잡 result (성공/실패 카운트):")
        rows = await conn.fetch(
            """
            SELECT
              id, status, current, total,
              (payload::jsonb)->>'source_site' AS site,
              (payload::jsonb)->>'brand_name' AS brand,
              result
            FROM samba_jobs
            WHERE job_type='transmit'
              AND status='completed'
              AND (payload::jsonb)->>'target_account_ids' LIKE '%' || $1 || '%'
            ORDER BY completed_at DESC
            LIMIT 8
            """,
            target,
        )
        for r in rows:
            print(f"  {r['id'][:12]} | {r['site']}/{r['brand']} | {r['current']}/{r['total']} | result={r['result']}")

        # 워커 1개에 한정된지 — 여러 워커 인스턴스가 도는지
        print(f"\n[V] FastAPI 백엔드 인스턴스 (samba-samba-api):")
        rows = await conn.fetch(
            """
            SELECT pid, application_name, backend_start, state, client_addr
            FROM pg_stat_activity
            WHERE datname = $1
              AND application_name LIKE '%samba%'
            ORDER BY backend_start
            """,
            settings.write_db_name,
        )
        for r in rows:
            print(f"  pid={r['pid']} app={r['application_name']} started={r['backend_start']} state={r['state']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
