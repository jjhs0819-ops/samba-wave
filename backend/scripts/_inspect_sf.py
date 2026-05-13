"""검색필터에 묶인 마스마룰즈 상품 분석."""

import asyncio
import json

import asyncpg
from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )

    rows = await conn.fetch(
        """
        SELECT id, site_product_id, name, brand, source_site,
               options::text AS options_txt,
               addon_options::text AS addon_txt,
               jsonb_typeof(options::jsonb) AS opt_type,
               jsonb_typeof(addon_options::jsonb) AS addon_type
        FROM samba_collected_product
        WHERE search_filter_id = 'sf_01KRASAFGHK1TQC6VZDTEZ8P7C'
        ORDER BY id
        LIMIT 5
        """
    )
    for r in rows:
        print(f"--- id={r['id']} site={r['site_product_id']} brand={r['brand']} source={r['source_site']}")
        print(f"  name: {r['name'][:60]}")
        print(f"  opt_type={r['opt_type']} addon_type={r['addon_type']}")
        print(f"  options: {(r['options_txt'] or 'null')[:500]}")
        print(f"  addon  : {(r['addon_txt'] or 'null')[:500]}\n")

    # opt_cnt / addon_cnt 분포
    dist = await conn.fetch(
        """
        WITH t AS MATERIALIZED (
          SELECT id,
                 CASE WHEN jsonb_typeof(options::jsonb) = 'array' THEN jsonb_array_length(options::jsonb) ELSE NULL END AS opt_cnt,
                 CASE WHEN addon_options IS NOT NULL AND jsonb_typeof(addon_options::jsonb) = 'array' THEN jsonb_array_length(addon_options::jsonb) ELSE 0 END AS addon_cnt
          FROM samba_collected_product
          WHERE search_filter_id = 'sf_01KRASAFGHK1TQC6VZDTEZ8P7C'
        )
        SELECT opt_cnt, addon_cnt, count(*) AS c FROM t GROUP BY opt_cnt, addon_cnt ORDER BY c DESC LIMIT 20
        """
    )
    print("[옵션수×애드온수 분포 — 검색필터 sf_...EZ8P7C]")
    for r in dist:
        print(f"  opt={r['opt_cnt']:>3}  addon={r['addon_cnt']:>3}  count={r['c']}")

    # 무신사 전체 (옵션≤1 + addon≥1) 분포
    print("\n[무신사 전체 — opt≤1 AND addon≥1]")
    total = await conn.fetchval(
        """
        WITH t AS MATERIALIZED (
          SELECT id,
                 CASE WHEN jsonb_typeof(options::jsonb) = 'array' THEN jsonb_array_length(options::jsonb) ELSE NULL END AS opt_cnt,
                 CASE WHEN addon_options IS NOT NULL AND jsonb_typeof(addon_options::jsonb) = 'array' THEN jsonb_array_length(addon_options::jsonb) ELSE 0 END AS addon_cnt
          FROM samba_collected_product
          WHERE source_site IN ('MUSINSA','무신사')
        )
        SELECT count(*) FROM t WHERE opt_cnt IS NOT NULL AND opt_cnt <= 1 AND addon_cnt >= 1
        """
    )
    print(f"  count={total}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
