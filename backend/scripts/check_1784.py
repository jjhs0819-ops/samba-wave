"""1784개가 어디서 나오는지 확인."""

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
        # SSG + name_all '나이' (ai_filter 없이)
        c1 = await conn.fetchval(
            """
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site='SSG'
              AND (
                name ILIKE '%나이%'
                OR REPLACE(name,' ','') ILIKE '%나이%'
                OR name_en ILIKE '%나이%'
                OR REPLACE(COALESCE(name_en,''),' ','') ILIKE '%나이%'
                OR COALESCE(market_names::text,'') ILIKE '%나이%'
                OR COALESCE(brand,'') ILIKE '%나이%'
                OR COALESCE(style_code,'') ILIKE '%나이%'
                OR site_product_id ILIKE '%나이%'
              )
            """
        )
        print(f"SSG + name_all '나이' (NO ai_filter): {c1}")

        # SSG + brand='나이키' (전체)
        c2 = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product WHERE source_site='SSG' AND brand='나이키'"
        )
        print(f"SSG + brand=나이키: {c2}")

        # SSG + brand=나이키 + ai_img_no
        c3 = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product WHERE source_site='SSG' AND brand='나이키' AND (tags IS NULL OR NOT (tags @> '[\"__ai_image__\"]'::jsonb))"
        )
        print(f"SSG + brand=나이키 + ai_img_no: {c3}")
    finally:
        await conn.close()


asyncio.run(main())
