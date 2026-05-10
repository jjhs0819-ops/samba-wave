"""삼바 상품 중복수집 전수조사 - 삭제 없이 통계만"""

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

    # 1) 전체 중복 (tenant, source_site, site_product_id) 그룹
    print("=== 1) 중복 그룹 통계 ===")
    rows = await conn.fetch(
        """
        SELECT tenant_id, source_site, COUNT(*) AS dup_count, COUNT(DISTINCT site_product_id) AS dup_products
        FROM (
            SELECT tenant_id, source_site, site_product_id, COUNT(*) AS c
            FROM samba_collected_product
            WHERE site_product_id IS NOT NULL AND site_product_id <> ''
            GROUP BY tenant_id, source_site, site_product_id
            HAVING COUNT(*) > 1
        ) t
        GROUP BY tenant_id, source_site
        ORDER BY tenant_id, source_site
        """
    )
    total_dup_rows = 0
    total_dup_products = 0
    for r in rows:
        # 중복으로 인한 잉여 row = 총 row - 그룹 수
        # 다시 계산: 그룹별 (c-1) 합
        pass
    # 더 정확한 통계
    detail = await conn.fetch(
        """
        SELECT tenant_id, source_site,
               COUNT(*) AS group_cnt,
               SUM(c) AS total_rows,
               SUM(c - 1) AS surplus_rows
        FROM (
            SELECT tenant_id, source_site, site_product_id, COUNT(*) AS c
            FROM samba_collected_product
            WHERE site_product_id IS NOT NULL AND site_product_id <> ''
            GROUP BY tenant_id, source_site, site_product_id
            HAVING COUNT(*) > 1
        ) t
        GROUP BY tenant_id, source_site
        ORDER BY surplus_rows DESC
        """
    )
    print(
        f"{'tenant_id':<28} {'source_site':<12} {'중복그룹':>8} {'총row':>8} {'잉여row':>8}"
    )
    grand_groups = 0
    grand_rows = 0
    grand_surplus = 0
    for r in detail:
        print(
            f"{(r['tenant_id'] or '-'):<28} {r['source_site']:<12} {r['group_cnt']:>8} {r['total_rows']:>8} {r['surplus_rows']:>8}"
        )
        grand_groups += r["group_cnt"]
        grand_rows += r["total_rows"]
        grand_surplus += r["surplus_rows"]
    print(f"{'합계':<28} {'':<12} {grand_groups:>8} {grand_rows:>8} {grand_surplus:>8}")

    # 2) 중복 그룹 분포 (몇 개씩 중복?)
    print("\n=== 2) 중복 개수 분포 (한 site_product_id당 row 수) ===")
    dist = await conn.fetch(
        """
        SELECT c AS dup_count, COUNT(*) AS group_cnt
        FROM (
            SELECT site_product_id, source_site, tenant_id, COUNT(*) AS c
            FROM samba_collected_product
            WHERE site_product_id IS NOT NULL AND site_product_id <> ''
            GROUP BY tenant_id, source_site, site_product_id
            HAVING COUNT(*) > 1
        ) t
        GROUP BY c
        ORDER BY c
        """
    )
    for r in dist:
        print(f"  {r['dup_count']}개 중복: {r['group_cnt']:,}그룹")

    # 3) 등록상품/미등록 분포 (중복 row 중 registered_accounts 비어있는 비율)
    print("\n=== 3) 중복 row 등록 여부 분포 ===")
    reg_stats = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE jsonb_array_length(COALESCE(registered_accounts, '[]'::jsonb)) = 0) AS unregistered,
          COUNT(*) FILTER (WHERE jsonb_array_length(COALESCE(registered_accounts, '[]'::jsonb)) > 0) AS registered,
          COUNT(*) AS total_dup_rows
        FROM samba_collected_product cp
        WHERE (tenant_id, source_site, site_product_id) IN (
          SELECT tenant_id, source_site, site_product_id
          FROM samba_collected_product
          WHERE site_product_id IS NOT NULL AND site_product_id <> ''
          GROUP BY tenant_id, source_site, site_product_id
          HAVING COUNT(*) > 1
        )
        """
    )
    print(f"  중복 row 총: {reg_stats['total_dup_rows']:,}")
    print(f"  - 등록계정 있음: {reg_stats['registered']:,}")
    print(f"  - 미등록: {reg_stats['unregistered']:,}")

    # 4) 표본 — 가장 많이 중복된 상품 5건
    print("\n=== 4) 가장 많이 중복된 상품 표본 ===")
    sample = await conn.fetch(
        """
        SELECT tenant_id, source_site, site_product_id, COUNT(*) AS c
        FROM samba_collected_product
        WHERE site_product_id IS NOT NULL AND site_product_id <> ''
        GROUP BY tenant_id, source_site, site_product_id
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
        LIMIT 5
        """
    )
    for s in sample:
        print(f"\n  {s['source_site']} {s['site_product_id']} ({s['c']}개 row):")
        rs = await conn.fetch(
            """
            SELECT id, name, sale_status, created_at, updated_at,
                   jsonb_array_length(COALESCE(registered_accounts, '[]'::jsonb)) AS reg_cnt,
                   COALESCE(jsonb_object_keys(COALESCE(last_sent_data, '{}'::jsonb)), '') AS lsd_keys
            FROM samba_collected_product
            WHERE tenant_id = $1 AND source_site = $2 AND site_product_id = $3
            ORDER BY created_at
            LIMIT 10
            """,
            s["tenant_id"],
            s["source_site"],
            s["site_product_id"],
        )
        for r in rs:
            print(
                f"    id={r['id']} created={r['created_at']} updated={r['updated_at']} reg={r['reg_cnt']} name={(r['name'] or '')[:30]}"
            )

    await conn.close()


asyncio.run(main())
