"""두 상품의 tags 컬럼과 ai_img_no 필터 동작 직접 확인."""

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
        rows = await conn.fetch(
            """
            SELECT id, source_site, tags,
                   tags @> '["__ai_image__"]'::jsonb AS has_ai_image,
                   (tags IS NULL OR NOT (tags @> '["__ai_image__"]'::jsonb)) AS ai_img_no_match
            FROM samba_collected_product
            WHERE id IN ('1000764104705', '1000825308937')
            """
        )
        for r in rows:
            print(f"id={r['id']} site={r['source_site']}")
            print(f"  tags={r['tags']}")
            print(f"  has_ai_image={r['has_ai_image']}")
            print(f"  ai_img_no_match(필터에 포함됨)={r['ai_img_no_match']}")

        # 추가: ai_img_no 필터를 SSG/'나이' 검색에 적용했을 때 실제 결과 수
        cnt_total = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG' AND name ILIKE '%나이%'
            """
        )
        cnt_filter = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG' AND name ILIKE '%나이%'
              AND (tags IS NULL OR NOT (tags @> '["__ai_image__"]'::jsonb))
            """
        )
        cnt_has = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG' AND name ILIKE '%나이%'
              AND tags @> '["__ai_image__"]'::jsonb
            """
        )
        print(
            f"\nSSG '나이' 전체={cnt_total}, ai_img_no필터매칭={cnt_filter}, ai_image보유={cnt_has}"
        )
    finally:
        await conn.close()


asyncio.run(main())
