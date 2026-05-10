"""중복상품 삭제 드라이런 - 실제 삭제 없음, 어떤 row가 남고/지워질지 시뮬레이션"""

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

    # 보존 우선순위 ranking 식 (작을수록 남김):
    #  1. registered_accounts 비어있지 않으면 우선
    #  2. last_sent_data에 sale_price>0 인 키 1개 이상이면 우선
    #  3. updated_at 최신
    #  4. created_at 오래된 것
    # NULL-safe: tenant_id가 NULL인 그룹도 포함 (COALESCE로 더미값 매칭)
    rank_sql = """
        WITH dup_keys AS (
          SELECT COALESCE(tenant_id, '__NULL__') AS tk, source_site, site_product_id
          FROM samba_collected_product
          WHERE site_product_id IS NOT NULL AND site_product_id <> ''
          GROUP BY COALESCE(tenant_id, '__NULL__'), source_site, site_product_id
          HAVING COUNT(*) > 1
        ),
        ranked AS (
          SELECT cp.id, cp.tenant_id, cp.source_site, cp.site_product_id, cp.name,
                 cp.created_at, cp.updated_at,
                 CASE WHEN jsonb_typeof(cp.registered_accounts) = 'array'
                      THEN jsonb_array_length(cp.registered_accounts) ELSE 0 END AS reg_cnt,
                 cp.last_sent_data,
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

    # 1) 카운트 검증
    counts = await conn.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE rnk = 1) AS keep_cnt,
          COUNT(*) FILTER (WHERE rnk > 1) AS delete_cnt,
          COUNT(*) AS total
        FROM ({rank_sql}) t
        """
    )
    print("=== 드라이런 결과 ===")
    print(f"중복 row 총: {counts['total']:,}")
    print(f"  유지(keep, rnk=1): {counts['keep_cnt']:,}")
    print(f"  삭제(delete, rnk>1): {counts['delete_cnt']:,}")

    # 2) 소싱처별 삭제수
    print("\n=== 소싱처별 삭제 카운트 ===")
    by_site = await conn.fetch(
        f"""
        SELECT source_site,
               COUNT(*) FILTER (WHERE rnk = 1) AS keep_cnt,
               COUNT(*) FILTER (WHERE rnk > 1) AS delete_cnt
        FROM ({rank_sql}) t
        GROUP BY source_site
        ORDER BY delete_cnt DESC
        """
    )
    for r in by_site:
        print(
            f"  {r['source_site']:<10} 유지 {r['keep_cnt']:>6,}  삭제 {r['delete_cnt']:>6,}"
        )

    # 3) 표본 30개 그룹 (랜덤 + 다양한 site)
    print("\n=== 표본 30 그룹 (남길 row vs 지울 row) ===")
    samples = await conn.fetch(
        f"""
        WITH groups AS (
          SELECT DISTINCT COALESCE(tenant_id, '__NULL__') AS tk, source_site, site_product_id
          FROM ({rank_sql}) t
        ),
        picked AS (
          SELECT * FROM groups
          ORDER BY md5(source_site || site_product_id)
          LIMIT 30
        )
        SELECT t.*
        FROM ({rank_sql}) t
        JOIN picked p ON COALESCE(t.tenant_id, '__NULL__') = p.tk
                     AND t.source_site = p.source_site
                     AND t.site_product_id = p.site_product_id
        ORDER BY t.source_site, t.site_product_id, t.rnk
        """
    )
    cur_key = None
    for r in samples:
        key = (r["source_site"], r["site_product_id"])
        if key != cur_key:
            print(f"\n  [{r['source_site']}] {r['site_product_id']}")
            cur_key = key
        # last_sent_data에서 sale_price>0 키 카운트
        lsd = r["last_sent_data"] or {}
        if isinstance(lsd, str):
            import json as _j

            try:
                lsd = _j.loads(lsd)
            except Exception:
                lsd = {}
        sent_ok = sum(
            1
            for v in (lsd or {}).values()
            if isinstance(v, dict) and (v.get("sale_price") or 0) > 0
        )
        mark = "✅ 유지" if r["rnk"] == 1 else "❌ 삭제"
        print(
            f"    {mark} id={r['id']} reg={r['reg_cnt']} sent_ok={sent_ok} created={r['created_at']} updated={r['updated_at']} name={(r['name'] or '')[:30]}"
        )

    # 4) 우려사항: 삭제 대상 중 registered_accounts 가진 row 수 (충돌 케이스)
    print("\n=== 위험도 점검 ===")
    risk = await conn.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE rnk > 1 AND reg_cnt > 0) AS dangerous_delete,
          COUNT(*) FILTER (WHERE rnk > 1) AS total_delete
        FROM ({rank_sql}) t
        """
    )
    print(
        f"  삭제 대상 중 registered_accounts 보유: {risk['dangerous_delete']:,} / {risk['total_delete']:,}"
    )
    print("  → 0이 아니면 유지 row와 충돌. 그룹별로 모두 등록된 케이스 의미.")

    await conn.close()


asyncio.run(main())
