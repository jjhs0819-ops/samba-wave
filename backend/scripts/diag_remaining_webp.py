"""DB update 후 남은 webp URL 패턴 확인."""

import asyncio
import asyncpg
import re
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
    try:
        rows = await conn.fetch(
            """
            SELECT id, images::text AS img_txt
            FROM samba_collected_product
            WHERE images::text LIKE '%.webp%'
            LIMIT 10
            """
        )
        print("\n남은 webp URL 샘플 10건:")
        all_webp_urls: set[str] = set()
        for r in rows:
            urls = re.findall(r'https?://[^"]+\.webp', r["img_txt"])
            for u in urls[:3]:
                all_webp_urls.add(u)
        for u in sorted(all_webp_urls):
            print(f"  {u}")

        # 호스트별 분포
        print("\n호스트별 분포:")
        rows = await conn.fetch(
            """
            SELECT DISTINCT
              regexp_replace(
                substring(images::text from 'https?://[^"]+\\.webp'),
                '^(https?://[^/]+).*$',
                '\\1'
              ) AS host,
              COUNT(*) OVER (PARTITION BY regexp_replace(
                substring(images::text from 'https?://[^"]+\\.webp'),
                '^(https?://[^/]+).*$',
                '\\1'
              )) AS cnt
            FROM samba_collected_product
            WHERE images::text LIKE '%.webp%'
            LIMIT 10
            """
        )
        for r in rows:
            print(f"  {r['host']} — {r['cnt']:,}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
