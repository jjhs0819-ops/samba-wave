"""롯데ON 오토튠 미활성화 원인 진단 스크립트."""

import asyncio
import asyncpg
import sys

sys.path.insert(0, "/app/backend")
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        database=settings.write_db_name,
        user=settings.write_db_user,
        password=settings.write_db_password,
    )
    print("=== LOTTEON registered_accounts 타입 분포 ===")
    rows = await conn.fetch("""
        SELECT
            jsonb_typeof(registered_accounts) AS ra_type,
            COUNT(*) AS cnt
        FROM samba_collected_product
        WHERE source_site = 'LOTTEON'
          AND status = 'registered'
        GROUP BY jsonb_typeof(registered_accounts)
        ORDER BY cnt DESC
    """)
    for r in rows:
        print(f"  jsonb_typeof={r['ra_type']!r:12s}  count={r['cnt']}")

    print()
    print("=== LOTTEON 오토튠 조건별 통과 수 ===")
    rows = await conn.fetch("""
        SELECT
            COUNT(*) AS total_registered,
            COUNT(*) FILTER (
                WHERE registered_accounts IS NOT NULL
            ) AS not_null,
            COUNT(*) FILTER (
                WHERE registered_accounts IS NOT NULL
                  AND jsonb_typeof(registered_accounts) = 'array'
            ) AS is_array,
            COUNT(*) FILTER (
                WHERE registered_accounts IS NOT NULL
                  AND jsonb_typeof(registered_accounts) = 'array'
                  AND registered_accounts != '[]'::jsonb
            ) AS nonempty_array,
            COUNT(*) FILTER (
                WHERE registered_accounts IS NOT NULL
                  AND jsonb_typeof(registered_accounts) = 'array'
                  AND registered_accounts != '[]'::jsonb
                  AND market_product_nos IS NOT NULL
                  AND market_product_nos::text != 'null'
                  AND market_product_nos::text != '{}'
            ) AS passes_market_cond,
            COUNT(*) FILTER (
                WHERE registered_accounts IS NOT NULL
                  AND jsonb_typeof(registered_accounts) = 'array'
                  AND registered_accounts != '[]'::jsonb
                  AND market_product_nos IS NOT NULL
                  AND market_product_nos::text != 'null'
                  AND market_product_nos::text != '{}'
                  AND applied_policy_id IS NOT NULL
            ) AS passes_all
        FROM samba_collected_product
        WHERE source_site = 'LOTTEON'
          AND status = 'registered'
    """)
    for r in rows:
        print(f"  total_registered  = {r['total_registered']}")
        print(f"  not_null          = {r['not_null']}")
        print(f"  is_array          = {r['is_array']}")
        print(f"  nonempty_array    = {r['nonempty_array']}")
        print(f"  passes_market_cond= {r['passes_market_cond']}")
        print(f"  passes_all        = {r['passes_all']}")

    print()
    print("=== 비교: jsonb_typeof 없이 (이전 방식) ===")
    rows = await conn.fetch("""
        SELECT COUNT(*) AS old_style_count
        FROM samba_collected_product
        WHERE source_site = 'LOTTEON'
          AND status = 'registered'
          AND registered_accounts IS NOT NULL
          AND registered_accounts != '[]'::jsonb
          AND market_product_nos IS NOT NULL
          AND market_product_nos::text != 'null'
          AND market_product_nos::text != '{}'
          AND applied_policy_id IS NOT NULL
    """)
    print(f"  old_style_count (jsonb_typeof 없음) = {rows[0]['old_style_count']}")

    await conn.close()


asyncio.run(main())
