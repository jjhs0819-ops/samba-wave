"""shipment/monitor_event 영향 row 상세 — 키프 cpid로 재연결 vs 그대로 두기 결정용"""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    RANK_SQL = """
    WITH dup_keys AS (
      SELECT COALESCE(tenant_id, '__NULL__') AS tk, source_site, site_product_id
      FROM samba_collected_product
      WHERE site_product_id IS NOT NULL AND site_product_id <> ''
      GROUP BY COALESCE(tenant_id, '__NULL__'), source_site, site_product_id
      HAVING COUNT(*) > 1
    ),
    ranked AS (
      SELECT cp.id, cp.source_site, cp.site_product_id,
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
    SELECT id, source_site, site_product_id, rnk FROM ranked
    """
    await conn.execute(f"CREATE TEMP TABLE _ranked AS {RANK_SQL}")
    await conn.execute("CREATE INDEX ON _ranked(id)")
    await conn.execute("CREATE INDEX ON _ranked(source_site, site_product_id)")

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

    print("=== A) samba_shipment.product_id 영향 1,134 row 상세 ===")
    sh_status = await conn.fetch(
        """
        SELECT status, COUNT(*) AS c FROM samba_shipment
        WHERE product_id IN (SELECT id FROM _safe_del)
        GROUP BY status ORDER BY c DESC
        """
    )
    for r in sh_status:
        print(f"  status={r['status']}: {r['c']}")

    print("\n  표본 5건:")
    samples = await conn.fetch(
        """
        SELECT s.id, s.product_id, s.status, s.created_at, s.order_id
        FROM samba_shipment s
        WHERE s.product_id IN (SELECT id FROM _safe_del)
        LIMIT 5
        """
    )
    for s in samples:
        print(f"  ship_id={s['id']} pid={s['product_id']} status={s['status']} ord={s['order_id']}")

    print("\n=== B) samba_monitor_event.product_id 영향 1,850 row 상세 ===")
    ev_type = await conn.fetch(
        """
        SELECT event_type, COUNT(*) AS c FROM samba_monitor_event
        WHERE product_id IN (SELECT id FROM _safe_del)
        GROUP BY event_type ORDER BY c DESC LIMIT 20
        """
    )
    for r in ev_type:
        print(f"  event_type={r['event_type']}: {r['c']}")

    # monitor_event는 보통 로그성 - 무방
    # shipment는 주문 연결 - 위험

    print("\n=== C) shipment 영향 cpid 그룹의 keep cpid 매핑 가능 여부 ===")
    # 각 shipment의 cpid를 keep cpid로 재연결 가능한지
    mapped = await conn.fetchval(
        """
        SELECT COUNT(*) FROM samba_shipment s
        JOIN _safe_del d ON d.id = s.product_id
        JOIN _ranked r_del ON r_del.id = s.product_id
        JOIN _ranked r_keep ON r_keep.source_site = r_del.source_site
          AND r_keep.site_product_id = r_del.site_product_id
          AND r_keep.rnk = 1
        """
    )
    print(f"  keep cpid로 재연결 가능: {mapped} / 1134")

    # 만약 mapped<1134이면 keep이 없는 그룹 = 이상
    print("\n=== D) shipment 보유 cpid를 _safe_del에서 제외하는 옵션 ===")
    safe_minus_ship = await conn.fetchval(
        """
        SELECT COUNT(*) FROM _safe_del d
        WHERE d.id NOT IN (SELECT product_id FROM samba_shipment WHERE product_id IS NOT NULL)
        """
    )
    print(f"  shipment 미참조 cpid만 삭제: {safe_minus_ship}")

    # monitor_event는?
    safe_minus_both = await conn.fetchval(
        """
        SELECT COUNT(*) FROM _safe_del d
        WHERE d.id NOT IN (SELECT product_id FROM samba_shipment WHERE product_id IS NOT NULL)
          AND d.id NOT IN (SELECT product_id FROM samba_monitor_event WHERE product_id IS NOT NULL)
        """
    )
    print(f"  shipment+monitor 모두 미참조 cpid만 삭제: {safe_minus_both}")

    await conn.close()


asyncio.run(main())
