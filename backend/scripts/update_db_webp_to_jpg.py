"""DB 의 samba_collected_product.images / detail_images / detail_html 에서
transformed/ai_*.webp / split/*.webp URL 을 .jpg 로 치환.

전제: 사전에 convert_webp_to_jpg.py 로 R2 에 .jpg 자산이 모두 만들어져 있어야 한다.
순서를 어기면 DB 의 jpg URL 이 R2 에서 404 가 나 이미지가 깨진다.

검증 모드(--dry-run) 우선 실행 권장.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import asyncpg

from backend.core.config import settings

logger = logging.getLogger("update_db_webp_to_jpg")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


# transformed/ai_* 과 split/* 패턴만 치환 — 다른 webp(외부 CDN 미러 등)는 건드리지 않음
SQL_UPDATE_IMAGES = """
WITH targets AS (
    SELECT id, images::text AS old_txt
    FROM samba_collected_product
    WHERE images::text LIKE '%/transformed/ai_%.webp%'
       OR images::text LIKE '%/split/%.webp%'
), patched AS (
    SELECT id,
           regexp_replace(
             regexp_replace(old_txt, '(/transformed/ai_[0-9a-fA-F_]+)\\.webp', '\\1.jpg', 'g'),
             '(/split/[A-Za-z0-9_]+)\\.webp', '\\1.jpg', 'g'
           ) AS new_txt
    FROM targets
)
UPDATE samba_collected_product scp
SET images = p.new_txt::jsonb
FROM patched p
WHERE scp.id = p.id
"""

SQL_UPDATE_DETAIL_IMAGES = """
WITH targets AS (
    SELECT id, detail_images::text AS old_txt
    FROM samba_collected_product
    WHERE detail_images IS NOT NULL
      AND (detail_images::text LIKE '%/transformed/ai_%.webp%'
           OR detail_images::text LIKE '%/split/%.webp%')
), patched AS (
    SELECT id,
           regexp_replace(
             regexp_replace(old_txt, '(/transformed/ai_[0-9a-fA-F_]+)\\.webp', '\\1.jpg', 'g'),
             '(/split/[A-Za-z0-9_]+)\\.webp', '\\1.jpg', 'g'
           ) AS new_txt
    FROM targets
)
UPDATE samba_collected_product scp
SET detail_images = p.new_txt::jsonb
FROM patched p
WHERE scp.id = p.id
"""

SQL_UPDATE_DETAIL_HTML = """
UPDATE samba_collected_product
SET detail_html = regexp_replace(
    regexp_replace(detail_html, '(/transformed/ai_[0-9a-fA-F_]+)\\.webp', '\\1.jpg', 'g'),
    '(/split/[A-Za-z0-9_]+)\\.webp', '\\1.jpg', 'g'
)
WHERE detail_html IS NOT NULL
  AND (detail_html LIKE '%/transformed/ai_%.webp%'
       OR detail_html LIKE '%/split/%.webp%')
"""

SQL_COUNT_BEFORE = """
SELECT
  (SELECT COUNT(*) FROM samba_collected_product WHERE images::text LIKE '%/transformed/ai_%.webp%' OR images::text LIKE '%/split/%.webp%') AS images_cnt,
  (SELECT COUNT(*) FROM samba_collected_product WHERE detail_images IS NOT NULL AND (detail_images::text LIKE '%/transformed/ai_%.webp%' OR detail_images::text LIKE '%/split/%.webp%')) AS detail_images_cnt,
  (SELECT COUNT(*) FROM samba_collected_product WHERE detail_html IS NOT NULL AND (detail_html LIKE '%/transformed/ai_%.webp%' OR detail_html LIKE '%/split/%.webp%')) AS detail_html_cnt
"""


async def main(dry_run: bool):
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        row = await conn.fetchrow(SQL_COUNT_BEFORE)
        logger.info(
            f"[BEFORE] images={row['images_cnt']:,} "
            f"detail_images={row['detail_images_cnt']:,} "
            f"detail_html={row['detail_html_cnt']:,}"
        )

        if dry_run:
            logger.info("dry-run 모드 — 변경 없이 종료")
            return

        async with conn.transaction():
            r1 = await conn.execute(SQL_UPDATE_IMAGES)
            logger.info(f"images update: {r1}")
            r2 = await conn.execute(SQL_UPDATE_DETAIL_IMAGES)
            logger.info(f"detail_images update: {r2}")
            r3 = await conn.execute(SQL_UPDATE_DETAIL_HTML)
            logger.info(f"detail_html update: {r3}")

        row = await conn.fetchrow(SQL_COUNT_BEFORE)
        logger.info(
            f"[AFTER ] images={row['images_cnt']:,} "
            f"detail_images={row['detail_images_cnt']:,} "
            f"detail_html={row['detail_html_cnt']:,}"
        )

    finally:
        await conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--apply", action="store_true", help="실제 update 실행 (기본은 dry-run)"
    )
    args = p.parse_args()
    asyncio.run(main(dry_run=not args.apply))
