"""source_site='manual' 상품 현황 조회"""
import asyncio
import asyncpg
import json
import sys
import os

sys.path.insert(0, "/app/backend")
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        database=settings.write_db_name,
        user=settings.write_db_user,
        password=settings.write_db_password,
        ssl=False,
    )

    # 1. 건수 확인
    count = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM samba_collected_product
        WHERE source_site = 'manual'
        """
    )
    print(f"\n[전체] source_site='manual' 상품 수: {count:,}건")

    # 2. 오토튠 active_sites 쿼리 조건 통과 건수
    count_active = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM samba_collected_product
        WHERE source_site = 'manual'
          AND registered_accounts IS NOT NULL
          AND registered_accounts != 'null'::jsonb
          AND registered_accounts != '[]'::jsonb
          AND market_product_nos IS NOT NULL
          AND market_product_nos::text != 'null'
          AND market_product_nos::text != '{}'
          AND applied_policy_id IS NOT NULL
        """
    )
    print(f"[오토튠 조건 통과] {count_active:,}건")

    # 3. 샘플 10건
    rows = await conn.fetch(
        """
        SELECT id, name, brand, registered_accounts, market_product_nos,
               applied_policy_id, created_at
        FROM samba_collected_product
        WHERE source_site = 'manual'
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    print(f"\n[샘플 10건] (최신순)")
    for r in rows:
        ra = r["registered_accounts"]
        mpn = r["market_product_nos"]
        print(f"  id={r['id'][:16]}... name={r['name'][:30] if r['name'] else '-'}")
        print(f"    brand={r['brand']} policy={r['applied_policy_id']}")
        print(f"    registered_accounts={ra}")
        print(f"    market_product_nos={mpn}")
        print()

    # 4. 오토튠 조건 통과 건만 샘플
    if count_active > 0:
        rows_active = await conn.fetch(
            """
            SELECT id, name, brand, registered_accounts, market_product_nos
            FROM samba_collected_product
            WHERE source_site = 'manual'
              AND registered_accounts IS NOT NULL
              AND registered_accounts != 'null'::jsonb
              AND registered_accounts != '[]'::jsonb
              AND market_product_nos IS NOT NULL
              AND market_product_nos::text != 'null'
              AND market_product_nos::text != '{}'
              AND applied_policy_id IS NOT NULL
            LIMIT 5
            """
        )
        print(f"[오토튠 조건 통과 샘플 5건]")
        for r in rows_active:
            print(f"  id={r['id'][:16]}... name={r['name'][:40] if r['name'] else '-'}")
            print(f"    registered_accounts={r['registered_accounts']}")
            print(f"    market_product_nos={r['market_product_nos']}")
            print()

    await conn.close()


asyncio.run(main())
