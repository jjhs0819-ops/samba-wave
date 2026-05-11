"""SQLAlchemy cast 패턴 vs raw text 패턴 차이 검증 (raw SQL)."""

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
        # 패턴 A: SQLAlchemy cast('[..]', JSONB)이 실제로 생성하는 SQL
        # → CAST($1 AS JSONB) 형태로 바운드 파라미터로 전달
        # name search '나이' (name_all) + SSG + ai_img_no
        # name pattern
        name_pat = "%나이%"
        like_no_space = "%나이%"

        # Pattern A simulation: CAST($N AS JSONB)
        rA = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG'
              AND (
                name ILIKE $1
                OR REPLACE(name,' ','') ILIKE $2
                OR name_en ILIKE $1
                OR REPLACE(COALESCE(name_en,''),' ','') ILIKE $2
                OR COALESCE(market_names::text,'') ILIKE $1
                OR COALESCE(brand,'') ILIKE $1
                OR COALESCE(style_code,'') ILIKE $1
                OR site_product_id ILIKE $1
              )
              AND (tags IS NULL OR NOT (tags @> CAST($3 AS JSONB)))
            """,
            name_pat,
            like_no_space,
            '["__ai_image__"]',
        )
        print(f"Pattern A (CAST $N AS JSONB) with bound param: {rA}")

        # Pattern B: text inline JSONB literal
        rB = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG'
              AND (
                name ILIKE $1
                OR REPLACE(name,' ','') ILIKE $2
                OR name_en ILIKE $1
                OR REPLACE(COALESCE(name_en,''),' ','') ILIKE $2
                OR COALESCE(market_names::text,'') ILIKE $1
                OR COALESCE(brand,'') ILIKE $1
                OR COALESCE(style_code,'') ILIKE $1
                OR site_product_id ILIKE $1
              )
              AND (tags IS NULL OR NOT (tags @> '["__ai_image__"]'::jsonb))
            """,
            name_pat,
            like_no_space,
        )
        print(f"Pattern B (inline ::jsonb literal): {rB}")

        # 비교: ai_filter 없이
        rNo = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG'
              AND (
                name ILIKE $1
                OR REPLACE(name,' ','') ILIKE $2
                OR name_en ILIKE $1
                OR REPLACE(COALESCE(name_en,''),' ','') ILIKE $2
                OR COALESCE(market_names::text,'') ILIKE $1
                OR COALESCE(brand,'') ILIKE $1
                OR COALESCE(style_code,'') ILIKE $1
                OR site_product_id ILIKE $1
              )
            """,
            name_pat,
            like_no_space,
        )
        print(f"No ai_filter: {rNo}")
    finally:
        await conn.close()


asyncio.run(main())
