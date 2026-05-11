"""webp 자산 변환 작업 범위 파악."""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host='172.18.0.2',
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 1. images 배열에 .webp URL 포함된 상품 수
        print("\n[1] images 배열에 .webp URL 포함된 상품 수 (전체):")
        cnt = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM samba_collected_product
            WHERE images::text LIKE '%.webp%'
            """
        )
        print(f"  {cnt:,}건")

        # 2. detail_images에 .webp 포함된 상품 수
        print("\n[2] detail_images에 .webp 포함된 상품 수:")
        cnt = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM samba_collected_product
            WHERE detail_images::text LIKE '%.webp%'
            """
        )
        print(f"  {cnt:,}건")

        # 3. detail_html에 .webp 포함된 상품 수
        print("\n[3] detail_html에 .webp 포함된 상품 수:")
        cnt = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM samba_collected_product
            WHERE detail_html LIKE '%.webp%'
            """
        )
        print(f"  {cnt:,}건")

        # 4. R2 호스트별 webp URL 분포 (샘플)
        print("\n[4] R2 webp URL 호스트 분포 (샘플 10건):")
        rows = await conn.fetch(
            """
            SELECT DISTINCT
              regexp_replace(
                substring(images::text from 'https://[^"]+\\.webp'),
                '^(https://[^/]+).*$',
                '\\1'
              ) AS host
            FROM samba_collected_product
            WHERE images::text LIKE '%.webp%'
            LIMIT 10
            """
        )
        for r in rows:
            print(f"  {r['host']}")

        # 5. transformed/ 경로 webp만 — 배경제거 워커 산출물 추정 수
        print("\n[5] 'transformed/ai_' webp 자산 포함 상품 (배경제거 워커 산출물):")
        cnt = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM samba_collected_product
            WHERE images::text LIKE '%/transformed/ai_%.webp%'
            """
        )
        print(f"  {cnt:,}건")

        # 6. 한 상품당 평균 webp 이미지 수 (어림)
        print("\n[6] 상위 5건 — images 배열 길이 + webp 개수:")
        rows = await conn.fetch(
            """
            SELECT id,
                   jsonb_array_length(images::jsonb) AS img_cnt,
                   (SELECT COUNT(*) FROM jsonb_array_elements_text(images::jsonb) v
                    WHERE v LIKE '%.webp') AS webp_cnt
            FROM samba_collected_product
            WHERE images IS NOT NULL
              AND images::text LIKE '%.webp%'
            ORDER BY id DESC
            LIMIT 5
            """
        )
        for r in rows:
            print(f"  {r['id']} | total={r['img_cnt']} webp={r['webp_cnt']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
