"""product_id 컬럼 + 기타 cpid 잠재 참조 컬럼 전수조사"""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    print("=== A) public 스키마의 product_id 류 컬럼 전수 ===")
    cols = await conn.fetch(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
          AND column_name IN ('product_id', 'collected_product_id', 'cp_id',
                              'collected_id', 'parent_id', 'source_product_id')
          AND table_name NOT IN (
            'samba_collected_product',
            'samba_collected_product_dup_backup_20260510',
            'samba_dedupe_market_delete_queue'
          )
        ORDER BY table_name, column_name
        """
    )
    for c in cols:
        print(f"  {c['table_name']}.{c['column_name']}  ({c['data_type']})")

    print("\n=== B) ranked 임시테이블 + safe_del 재구성 ===")
    RANK_SQL = """
    WITH dup_keys AS (
      SELECT COALESCE(tenant_id, '__NULL__') AS tk, source_site, site_product_id
      FROM samba_collected_product
      WHERE site_product_id IS NOT NULL AND site_product_id <> ''
      GROUP BY COALESCE(tenant_id, '__NULL__'), source_site, site_product_id
      HAVING COUNT(*) > 1
    ),
    ranked AS (
      SELECT cp.id,
             ROW_NUMBER() OVER (
               PARTITION BY COALESCE(cp.tenant_id, '__NULL__'), cp.source_site, cp.site_product_id
               ORDER BY
                 (CASE WHEN jsonb_typeof(cp.registered_accounts) = 'array'
                        AND jsonb_array_length(cp.registered_accounts) > 0
                       THEN 1 ELSE 0 END) DESC,
                 (
                   SELECT COUNT(*) FROM jsonb_each(
                     CASE WHEN jsonb_typeof(cp.last_sent_data::jsonb) = 'object'
                          THEN cp.last_sent_data::jsonb ELSE '{}'::jsonb END
                   ) e
                   WHERE (e.value->>'sale_price') ~ '^[0-9]+(\\.[0-9]+)?$'
                     AND (e.value->>'sale_price')::numeric > 0
                 ) DESC,
                 cp.updated_at DESC NULLS LAST,
                 cp.created_at ASC NULLS LAST,
                 cp.id ASC
             ) AS rnk
      FROM samba_collected_product cp
      JOIN dup_keys d
        ON COALESCE(cp.tenant_id, '__NULL__') = d.tk
       AND cp.source_site = d.source_site
       AND cp.site_product_id = d.site_product_id
    )
    SELECT id, rnk FROM ranked
    """
    await conn.execute(f"CREATE TEMP TABLE _ranked AS {RANK_SQL}")
    await conn.execute("CREATE INDEX ON _ranked(id)")

    await conn.execute(
        """
        CREATE TEMP TABLE _safe_del AS
        SELECT r.id FROM _ranked r
        WHERE r.rnk > 1
          AND r.id NOT IN (
            SELECT DISTINCT collected_product_id FROM samba_dedupe_market_delete_queue
          )
          AND EXISTS (
            SELECT 1 FROM samba_collected_product_dup_backup_20260510 b WHERE b.id = r.id
          )
          AND r.id NOT IN (
            SELECT collected_product_id FROM samba_order
            WHERE collected_product_id IS NOT NULL
          )
        """
    )
    await conn.execute("CREATE INDEX ON _safe_del(id)")
    n = await conn.fetchval("SELECT COUNT(*) FROM _safe_del")
    print(f"  최종 _safe_del: {n}")

    print("\n=== C) 후보 컬럼 별 영향 row 카운트 ===")
    for c in cols:
        tbl = c['table_name']
        col = c['column_name']
        try:
            cnt = await conn.fetchval(
                f"SELECT COUNT(*) FROM {tbl} WHERE {col} IN (SELECT id FROM _safe_del)"
            )
            tag = " ← 영향" if cnt > 0 else ""
            print(f"  {tbl}.{col}: {cnt}{tag}")
        except Exception as e:
            print(f"  {tbl}.{col}: 조회 실패 - {e}")

    print("\n=== D) samba_collected_product_image / option 등 cpid 컬럼 직접 조회 ===")
    # product_id 외에 다른 외래 컬럼이 있을 수 있음
    misc_tables = await conn.fetch(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_name LIKE 'samba_collected_product%'
        """
    )
    for t in misc_tables:
        cols_in = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=$1",
            t['table_name']
        )
        print(f"  {t['table_name']}: {[c['column_name'] for c in cols_in]}")

    await conn.close()


asyncio.run(main())
