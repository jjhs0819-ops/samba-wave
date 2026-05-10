"""불일치 진단:
- 백업 누락 285개 정체 (백업 이후 새로 생긴 dup? rnk 재계산?)
- F단계 rnk=1이 _del_targets에 24개 들어간 케이스 분석
- samba_order 영향 1 row 상세
- 큐 cpid와 백업 테이블 교집합 검증
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
  SELECT cp.id, cp.tenant_id, cp.source_site, cp.site_product_id, cp.created_at, cp.updated_at,
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

    print("=== 1) 큐 cpid 백업 존재 검증 ===")
    queue_in_backup = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT q.collected_product_id)
        FROM samba_dedupe_market_delete_queue q
        WHERE EXISTS (
            SELECT 1 FROM samba_collected_product_dup_backup_20260510 b
            WHERE b.id = q.collected_product_id
        )
        """
    )
    queue_distinct = await conn.fetchval(
        "SELECT COUNT(DISTINCT collected_product_id) FROM samba_dedupe_market_delete_queue"
    )
    print(f"  큐 distinct cpid {queue_distinct} 중 백업에 있는 것: {queue_in_backup}")
    print(f"  큐에 있는데 백업에 없는 cpid: {queue_distinct - queue_in_backup}개")

    print("\n=== 2) 백업 테이블 cpid가 현재 collected_product에 살아있는지 ===")
    backup_alive = await conn.fetchval(
        """
        SELECT COUNT(*) FROM samba_collected_product_dup_backup_20260510 b
        WHERE EXISTS (SELECT 1 FROM samba_collected_product cp WHERE cp.id = b.id)
        """
    )
    backup_total = await conn.fetchval(
        "SELECT COUNT(*) FROM samba_collected_product_dup_backup_20260510"
    )
    print(f"  백업 {backup_total}개 중 현재 cp에 살아있는 것: {backup_alive}")
    print(f"  백업 row 중 이미 사라진 것: {backup_total - backup_alive}")

    print("\n=== 3) 임시테이블 재생성 ===")
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
    n = await conn.fetchval("SELECT COUNT(*) FROM _del_targets")
    print(f"  _del_targets: {n}")

    print("\n=== 4) 백업 누락 cpid 표본 ===")
    missing = await conn.fetch(
        """
        SELECT t.id FROM _del_targets t
        WHERE NOT EXISTS (
          SELECT 1 FROM samba_collected_product_dup_backup_20260510 b
          WHERE b.id = t.id
        )
        LIMIT 10
        """
    )
    miss_count = await conn.fetchval(
        """
        SELECT COUNT(*) FROM _del_targets t
        WHERE NOT EXISTS (
          SELECT 1 FROM samba_collected_product_dup_backup_20260510 b
          WHERE b.id = t.id
        )
        """
    )
    print(f"  백업 누락 _del_targets cpid: {miss_count}개")
    for r in missing:
        cp = await conn.fetchrow(
            "SELECT id, source_site, site_product_id, created_at FROM samba_collected_product WHERE id=$1",
            r['id']
        )
        if cp:
            print(f"    {cp['id']} site={cp['source_site']} spid={cp['site_product_id']} created={cp['created_at']}")

    print("\n=== 5) F단계 rnk=1인데 _del_targets 들어간 24개 분석 ===")
    # 이 경우는 큐에 그 그룹의 다른 형제 cpid가 적재되었지만 keep 자체는 큐에 없을 때
    bad_keep = await conn.fetch(
        f"""
        WITH r AS ({RANK_SQL})
        SELECT r.id, r.source_site, r.site_product_id, r.rnk, r.reg_cnt
        FROM r
        JOIN _del_targets t ON t.id = r.id
        WHERE r.rnk = 1
        LIMIT 5
        """
    )
    bad_keep_cnt = await conn.fetchval(
        f"""
        WITH r AS ({RANK_SQL})
        SELECT COUNT(*) FROM r
        JOIN _del_targets t ON t.id = r.id
        WHERE r.rnk = 1
        """
    )
    print(f"  rnk=1인데 _del_targets 들어간: {bad_keep_cnt}개")
    for r in bad_keep:
        # 같은 그룹의 큐 cpid 확인
        qids = await conn.fetch(
            """
            SELECT q.collected_product_id, cp.id IS NOT NULL AS in_cp
            FROM samba_dedupe_market_delete_queue q
            LEFT JOIN samba_collected_product cp ON cp.id = q.collected_product_id
            WHERE q.source_site = $1 AND q.site_product_id = $2
            """,
            r['source_site'], r['site_product_id']
        )
        print(f"  [{r['source_site']}] spid={r['site_product_id']} keep_id={r['id']} reg_cnt={r['reg_cnt']}")
        for q in qids:
            print(f"    같은 그룹 큐 cpid={q['collected_product_id']} cp에 살아있음={q['in_cp']}")

    print("\n=== 6) samba_order.collected_product_id=영향 1건 상세 ===")
    order_ref = await conn.fetch(
        """
        SELECT o.collected_product_id, o.id AS order_id, o.order_number, o.created_at, o.status
        FROM samba_order o
        WHERE o.collected_product_id IN (SELECT id FROM _del_targets)
        """
    )
    for r in order_ref:
        print(f"  order_id={r['order_id']} cpid={r['collected_product_id']} ord_no={r['order_number']} status={r['status']} created={r['created_at']}")
        # keep cpid (같은 그룹에서 rnk=1)
        cp = await conn.fetchrow(
            "SELECT source_site, site_product_id, tenant_id FROM samba_collected_product WHERE id=$1",
            r['collected_product_id']
        )
        if cp:
            print(f"    cp: site={cp['source_site']} spid={cp['site_product_id']}")
            keep = await conn.fetchrow(
                f"""
                WITH r AS ({RANK_SQL})
                SELECT id FROM r
                WHERE rnk = 1 AND source_site = $1 AND site_product_id = $2
                """,
                cp['source_site'], cp['site_product_id']
            )
            if keep:
                print(f"    이 그룹의 keep cpid = {keep['id']}")

    await conn.close()


asyncio.run(main())
