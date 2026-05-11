"""다양한 조건으로 카운트해서 1,784가 어디서 나오는지 추적."""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.read_db_host,
        port=settings.read_db_port,
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )
    try:
        # 1. SSG 전체
        c1 = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product WHERE source_site='SSG'"
        )
        print(f"SSG 전체: {c1}")

        # 2. SSG + ai_img_no
        c2 = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product WHERE source_site='SSG' AND (tags IS NULL OR NOT (tags @> '[\"__ai_image__\"]'::jsonb))"
        )
        print(f"SSG + ai_img_no: {c2}")

        # 3. SSG + ai_img_no + '나이키' 브랜드 검색
        c3 = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG'
              AND (tags IS NULL OR NOT (tags @> '["__ai_image__"]'::jsonb))
              AND (name ILIKE '%나이%' OR brand ILIKE '%나이%' OR style_code ILIKE '%나이%' OR site_product_id ILIKE '%나이%')
            """
        )
        print(f"SSG + ai_img_no + '나이' name_all: {c3}")

        # 4. SSG + ai_img_no + 그룹필터 (검색필터 '나이' 이름)
        c4 = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product cp
            WHERE cp.source_site='SSG'
              AND (cp.tags IS NULL OR NOT (cp.tags @> '["__ai_image__"]'::jsonb))
              AND cp.search_filter_id IN (
                  SELECT id FROM samba_search_filter WHERE name ILIKE '%나이%'
              )
            """
        )
        print(f"SSG + ai_img_no + 검색필터'나이': {c4}")

        # 5. 두 상품의 site_product_id로 조회
        rows = await conn.fetch(
            """
            SELECT id, site_product_id, source_site, name, tags
            FROM samba_collected_product
            WHERE site_product_id IN ('1000764104705','1000825308937')
            """
        )
        for r in rows:
            tags = r["tags"]
            has = "__ai_image__" in (tags or [])
            print(
                f"  spid={r['site_product_id']} id={r['id']} has_ai_image={has} tags={tags}"
            )
    finally:
        await conn.close()


asyncio.run(main())
