"""오토튠 enabled_sources DB 설정 및 현재 상태 진단."""

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

    print("=== autotune_enabled_sources DB 설정 ===")
    row = await conn.fetchrow("""
        SELECT value FROM samba_settings WHERE key = 'autotune_enabled_sources'
    """)
    if row:
        print(f"  value: {row['value']}")
    else:
        print("  (설정 없음 — 전체 허용)")

    print()
    print("=== autotune_enabled_markets DB 설정 ===")
    row = await conn.fetchrow("""
        SELECT value FROM samba_settings WHERE key = 'autotune_enabled_markets'
    """)
    if row:
        print(f"  value: {row['value']}")
    else:
        print("  (설정 없음 — 전체 허용)")

    print()
    print("=== DB에서 활성 소싱처 (registered + 정책있음) ===")
    rows = await conn.fetch("""
        SELECT source_site, COUNT(*) AS cnt
        FROM samba_collected_product
        WHERE status = 'registered'
          AND applied_policy_id IS NOT NULL
          AND registered_accounts IS NOT NULL
          AND jsonb_typeof(registered_accounts) = 'array'
          AND registered_accounts != '[]'::jsonb
          AND market_product_nos IS NOT NULL
          AND market_product_nos::text != 'null'
          AND market_product_nos::text != '{}'
        GROUP BY source_site
        ORDER BY cnt DESC
    """)
    for r in rows:
        print(f"  {r['source_site']:15s}: {r['cnt']:,}개")

    await conn.close()


asyncio.run(main())
