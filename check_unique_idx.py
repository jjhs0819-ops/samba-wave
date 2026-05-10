"""중복배제 인덱스 존재 여부 + 중복 발생 원인 확인"""

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

    # 1) 인덱스 존재 여부
    print("=== 1) 유니크 인덱스 존재 여부 ===")
    idx = await conn.fetch(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'samba_collected_product'
          AND (indexname LIKE '%source_product%' OR indexname LIKE '%tenant_source%')
        ORDER BY indexname
        """
    )
    for i in idx:
        print(f"  {i['indexname']}")
        print(f"    {i['indexdef']}")

    # 2) 같은 site_product_id에 tenant_id가 다른 케이스
    print("\n=== 2) 중복 그룹의 tenant_id 분포 ===")
    rows = await conn.fetch(
        """
        SELECT source_site, site_product_id,
               COUNT(*) AS row_cnt,
               COUNT(DISTINCT tenant_id) AS tenant_cnt,
               COUNT(*) FILTER (WHERE tenant_id IS NULL) AS null_tenant_rows,
               COUNT(*) FILTER (WHERE tenant_id IS NOT NULL) AS notnull_tenant_rows
        FROM samba_collected_product
        WHERE site_product_id IS NOT NULL AND site_product_id <> ''
        GROUP BY source_site, site_product_id
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
        LIMIT 10
        """
    )
    print(
        f"  {'site':<10} {'site_product_id':<20} {'row':>4} {'tenant 종류':>10} {'null tenant':>11} {'notnull':>8}"
    )
    for r in rows:
        print(
            f"  {r['source_site']:<10} {r['site_product_id']:<20} {r['row_cnt']:>4} {r['tenant_cnt']:>10} {r['null_tenant_rows']:>11} {r['notnull_tenant_rows']:>8}"
        )

    # 3) 전체 중복 row 중 tenant_id NULL 비율
    print("\n=== 3) 중복 row 전체의 tenant_id NULL 비율 ===")
    null_stat = await conn.fetchrow(
        """
        WITH dup_keys AS (
          SELECT source_site, site_product_id
          FROM samba_collected_product
          WHERE site_product_id IS NOT NULL AND site_product_id <> ''
          GROUP BY source_site, site_product_id
          HAVING COUNT(*) > 1
        )
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE cp.tenant_id IS NULL) AS null_tenant,
          COUNT(*) FILTER (WHERE cp.tenant_id IS NOT NULL) AS notnull_tenant
        FROM samba_collected_product cp
        JOIN dup_keys d ON cp.source_site = d.source_site AND cp.site_product_id = d.site_product_id
        """
    )
    print(f"  중복 row 총: {null_stat['total']:,}")
    print(f"  - tenant_id IS NULL: {null_stat['null_tenant']:,}")
    print(f"  - tenant_id NOT NULL: {null_stat['notnull_tenant']:,}")

    # 4) 마이그 적용 여부 확인 — alembic_version
    print("\n=== 4) 현재 alembic head ===")
    ver = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    print(f"  alembic_version = {ver}")

    await conn.close()


asyncio.run(main())
