"""5/6번 결과 재실행 + 백업 누락 246 케이스 분류"""

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
  SELECT cp.id, cp.tenant_id, cp.source_site, cp.site_product_id, cp.created_at,
         CASE WHEN jsonb_typeof(cp.registered_accounts) = 'array'
              THEN jsonb_array_length(cp.registered_accounts) ELSE 0 END AS reg_cnt,
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
SELECT * FROM ranked
"""


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    # ranked 테이블을 한 번 materialize
    print("=== 0) ranked 임시테이블 materialize ===")
    await conn.execute(f"CREATE TEMP TABLE _ranked AS {RANK_SQL}")
    await conn.execute("CREATE INDEX ON _ranked(id)")
    await conn.execute("CREATE INDEX ON _ranked(source_site, site_product_id)")
    n = await conn.fetchval("SELECT COUNT(*) FROM _ranked")
    print(f"  ranked: {n}")

    print("\n=== A) _del_targets 재생성 (큐 제외, rnk>1) ===")
    await conn.execute(
        """
        CREATE TEMP TABLE _del_targets AS
        SELECT id FROM _ranked
        WHERE rnk > 1
          AND id NOT IN (
            SELECT DISTINCT collected_product_id
            FROM samba_dedupe_market_delete_queue
          )
        """
    )
    await conn.execute("CREATE INDEX ON _del_targets(id)")
    n = await conn.fetchval("SELECT COUNT(*) FROM _del_targets")
    print(f"  _del_targets: {n}")

    print("\n=== B) rnk=1인데 _del_targets 포함된 24개 분석 ===")
    bad_keep = await conn.fetch(
        """
        SELECT r.id, r.source_site, r.site_product_id, r.reg_cnt
        FROM _ranked r
        JOIN _del_targets t ON t.id = r.id
        WHERE r.rnk = 1
        """
    )
    print(f"  rnk=1인데 들어간: {len(bad_keep)}")
    for r in bad_keep[:5]:
        # 같은 그룹의 큐 cpid가 그 그룹의 다른 형제일 가능성
        sibs = await conn.fetch(
            """
            SELECT id, rnk, reg_cnt FROM _ranked
            WHERE source_site=$1 AND site_product_id=$2
            ORDER BY rnk
            """,
            r['source_site'], r['site_product_id']
        )
        in_q = await conn.fetch(
            """
            SELECT collected_product_id FROM samba_dedupe_market_delete_queue
            WHERE source_site=$1 AND site_product_id=$2
            """,
            r['source_site'], r['site_product_id']
        )
        print(f"  [{r['source_site']}] spid={r['site_product_id']} keep_id={r['id']}")
        for s in sibs:
            print(f"    sibling id={s['id']} rnk={s['rnk']} reg={s['reg_cnt']}")
        for q in in_q:
            print(f"    큐에 있는 cpid={q['collected_product_id']}")

    print("\n=== C) samba_order 영향 1 row 상세 ===")
    order_ref = await conn.fetch(
        """
        SELECT o.id AS order_id, o.collected_product_id, o.order_number, o.created_at, o.status
        FROM samba_order o
        WHERE o.collected_product_id IN (SELECT id FROM _del_targets)
        """
    )
    for r in order_ref:
        print(f"  order_id={r['order_id']} cpid={r['collected_product_id']} ord_no={r['order_number']} status={r['status']}")
        cp_info = await conn.fetchrow(
            "SELECT source_site, site_product_id FROM samba_collected_product WHERE id=$1",
            r['collected_product_id']
        )
        if cp_info:
            keep = await conn.fetchrow(
                "SELECT id FROM _ranked WHERE rnk=1 AND source_site=$1 AND site_product_id=$2",
                cp_info['source_site'], cp_info['site_product_id']
            )
            print(f"    cp site={cp_info['source_site']} spid={cp_info['site_product_id']}")
            print(f"    그룹 keep cpid={keep['id'] if keep else 'NONE'}")

    print("\n=== D) 백업 누락 246개 = 백업 시점 이후 새 dup ===")
    print("  백업 이후 신규 dup이므로 이번 삭제 대상에서 제외 (안전망 원칙)")
    miss_by_site = await conn.fetch(
        """
        SELECT cp.source_site, COUNT(*) AS c
        FROM _del_targets t
        JOIN samba_collected_product cp ON cp.id = t.id
        WHERE NOT EXISTS (
          SELECT 1 FROM samba_collected_product_dup_backup_20260510 b
          WHERE b.id = t.id
        )
        GROUP BY cp.source_site
        ORDER BY c DESC
        """
    )
    for r in miss_by_site:
        print(f"  {r['source_site']}: {r['c']}개")

    print("\n=== E) 최종 안전 삭제 대상 = _del_targets ∩ 백업 ∩ rnk!=1 ===")
    safe_n = await conn.fetchval(
        """
        SELECT COUNT(*) FROM _del_targets t
        WHERE EXISTS (
          SELECT 1 FROM samba_collected_product_dup_backup_20260510 b WHERE b.id = t.id
        )
        AND NOT EXISTS (
          SELECT 1 FROM _ranked r WHERE r.id = t.id AND r.rnk = 1
        )
        """
    )
    print(f"  안전 삭제 가능: {safe_n}개")

    # 안전 대상에서 자식 row 영향
    print("\n=== F) 안전 삭제 대상 기준 자식 row 영향 ===")
    await conn.execute(
        """
        CREATE TEMP TABLE _safe_del AS
        SELECT t.id FROM _del_targets t
        WHERE EXISTS (
          SELECT 1 FROM samba_collected_product_dup_backup_20260510 b WHERE b.id = t.id
        )
        AND NOT EXISTS (
          SELECT 1 FROM _ranked r WHERE r.id = t.id AND r.rnk = 1
        )
        """
    )
    await conn.execute("CREATE INDEX ON _safe_del(id)")

    for tbl, col in [
        ("samba_order", "collected_product_id"),
        ("samba_cs_inquiry", "collected_product_id"),
    ]:
        cnt = await conn.fetchval(
            f"SELECT COUNT(*) FROM {tbl} WHERE {col} IN (SELECT id FROM _safe_del)"
        )
        print(f"  {tbl}.{col}: {cnt} row")

    await conn.close()


asyncio.run(main())
