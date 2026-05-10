"""samba_collected_product.id 를 참조하는 FK + 삭제 대상 영향 row 조사

- pg_constraint로 FK 전수조사 (confdeltype 포함)
- 삭제 대상 cpid (rnk>1 AND id NOT IN queue) 추출
- 각 자식 테이블별 영향 row 카운트
- 백업 테이블에 삭제 대상 cpid 전부 존재하는지 검증
"""

import asyncio
import asyncpg
from backend.core.config import settings


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


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    print("=== A) 삭제 대상 cpid 임시 테이블 생성 ===")
    # 삭제 대상 = rnk>1 이고 큐에 없는 cpid
    await conn.execute("DROP TABLE IF EXISTS _del_targets")
    await conn.execute(
        f"""
        CREATE TEMP TABLE _del_targets AS
        SELECT id FROM ({RANK_SQL}) t
        WHERE rnk > 1
          AND id NOT IN (
            SELECT DISTINCT collected_product_id
            FROM samba_dedupe_market_delete_queue
          )
        """
    )
    await conn.execute("CREATE INDEX ON _del_targets(id)")

    total = await conn.fetchval("SELECT COUNT(*) FROM _del_targets")
    print(f"  삭제 대상 cpid: {total:,}개 (기대: ~26,235)")

    # 큐에 적재된 distinct cpid 수
    qcpid = await conn.fetchval(
        "SELECT COUNT(DISTINCT collected_product_id) FROM samba_dedupe_market_delete_queue"
    )
    qrows = await conn.fetchval("SELECT COUNT(*) FROM samba_dedupe_market_delete_queue")
    print(f"  큐 row: {qrows:,}, 큐 distinct cpid: {qcpid:,}")

    # 전체 rnk>1 (백업 테이블 row 수와 비교)
    total_rnk_gt1 = await conn.fetchval(
        f"SELECT COUNT(*) FROM ({RANK_SQL}) t WHERE rnk > 1"
    )
    backup_cnt = await conn.fetchval(
        "SELECT COUNT(*) FROM samba_collected_product_dup_backup_20260510"
    )
    print(f"  rnk>1 전체: {total_rnk_gt1:,}, 백업 테이블: {backup_cnt:,}")
    print(f"  → 검증식: 백업({backup_cnt}) = 삭제대상({total}) + 큐cpid({qcpid}) ?")
    diff = backup_cnt - (total + qcpid)
    print(f"     차이: {diff} (0이어야 함)")

    print("\n=== B) 백업 존재 검증 (삭제 대상 cpid 전부 백업되어 있어야 함) ===")
    missing = await conn.fetchval(
        """
        SELECT COUNT(*) FROM _del_targets t
        WHERE NOT EXISTS (
          SELECT 1 FROM samba_collected_product_dup_backup_20260510 b
          WHERE b.id = t.id
        )
        """
    )
    print(f"  백업 누락: {missing}개 (0이어야 함)")

    print("\n=== C) FK 전수조사 (samba_collected_product.id 참조) ===")
    fks = await conn.fetch(
        """
        SELECT c.conname,
               c.conrelid::regclass::text AS child_table,
               a.attname AS child_column,
               c.confdeltype AS on_delete,
               c.confupdtype AS on_update
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f'
          AND c.confrelid = 'samba_collected_product'::regclass
        ORDER BY c.conrelid::regclass::text
        """
    )
    if not fks:
        print("  (FK 없음)")
    deltype_map = {'a': 'NO ACTION', 'r': 'RESTRICT', 'c': 'CASCADE', 'n': 'SET NULL', 'd': 'SET DEFAULT'}
    for fk in fks:
        action = deltype_map.get(fk['on_delete'], fk['on_delete'])
        print(f"  {fk['child_table']}.{fk['child_column']}  (FK: {fk['conname']})  ON DELETE {action}")

    print("\n=== D) FK 자식 테이블별 영향 row 카운트 ===")
    for fk in fks:
        tbl = fk['child_table']
        col = fk['child_column']
        action = deltype_map.get(fk['on_delete'], fk['on_delete'])
        try:
            cnt = await conn.fetchval(
                f"SELECT COUNT(*) FROM {tbl} ch WHERE ch.{col} IN (SELECT id FROM _del_targets)"
            )
            print(f"  {tbl}.{col} (ON DELETE {action}): {cnt:,} row 영향")
        except Exception as e:
            print(f"  {tbl}.{col}: 조회 실패 - {e}")

    print("\n=== E) 논리적 참조 의심 컬럼 (FK 아닌 것) ===")
    # collected_product_id, cp_id, product_id 같은 이름으로 cpid를 담는 컬럼이 있는지
    candidates = await conn.fetch(
        """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name IN ('collected_product_id', 'cp_id', 'collected_id')
          AND table_name <> 'samba_collected_product'
          AND table_name <> 'samba_collected_product_dup_backup_20260510'
          AND table_name <> 'samba_dedupe_market_delete_queue'
        ORDER BY table_name, column_name
        """
    )
    if not candidates:
        print("  (의심 컬럼 없음)")
    for c in candidates:
        tbl = c['table_name']
        col = c['column_name']
        try:
            cnt = await conn.fetchval(
                f"SELECT COUNT(*) FROM {tbl} ch WHERE ch.{col} IN (SELECT id FROM _del_targets)"
            )
            print(f"  {tbl}.{col} ({c['data_type']}): {cnt:,} row 영향")
        except Exception as e:
            print(f"  {tbl}.{col}: 조회 실패 - {e}")

    print("\n=== F) 사전 그룹 무결성 점검 ===")
    # 삭제 대상 그룹에 keep(rnk=1)이 정상적으로 1개 존재하는지
    bad_groups = await conn.fetchval(
        f"""
        WITH r AS ({RANK_SQL})
        SELECT COUNT(*) FROM (
          SELECT id FROM r WHERE rnk = 1
            AND id IN (SELECT id FROM _del_targets)
        ) bad
        """
    )
    print(f"  _del_targets에 rnk=1이 들어가있는지: {bad_groups} (0이어야 함)")

    await conn.close()


asyncio.run(main())
