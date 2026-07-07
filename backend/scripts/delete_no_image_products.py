"""대표이미지 누락/잘못된 상품 삭제 스크립트.

사용법:
  # 건수만 확인 (삭제 안 함)
  python scripts/delete_no_image_products.py

  # 실제 삭제
  python scripts/delete_no_image_products.py --execute
"""

import asyncio
import sys

import asyncpg

sys.path.insert(0, "/app/backend")
from backend.core.config import settings


async def main(execute: bool = False):
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        database=settings.write_db_name,
        user=settings.write_db_user,
        password=settings.write_db_password,
        ssl=False,
    )

    try:
        # 1) 대표이미지 누락: images IS NULL 또는 빈 배열
        # lock_delete=True(삭제 잠금) 상품은 절대 제외 — 크림 매칭 등 중요 상품 보호(2026-07-08)
        count_row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM samba_collected_product
            WHERE (images IS NULL
               OR json_array_length(images) = 0)
              AND COALESCE(lock_delete, false) = false
            """
        )
        count_no_img = count_row["cnt"]
        print(f"대표이미지 누락 상품: {count_no_img:,}건")

        # 2) SSG 비상품 이미지(sui.ssgcdn 삼성카드/쿠폰배너 등): images[0]이 sitem.ssgcdn.com 아닌 SSG 상품
        count_row2 = await conn.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM samba_collected_product
            WHERE source_site = 'SSG'
              AND images IS NOT NULL
              AND json_array_length(images) > 0
              AND images->>0 NOT LIKE '%sitem.ssgcdn.com%'
              AND COALESCE(lock_delete, false) = false
            """
        )
        count_bad_img = count_row2["cnt"]
        print(f"SSG 비상품 대표이미지 상품 (삼성카드/배너 등): {count_bad_img:,}건")

        total = count_no_img + count_bad_img
        if not execute:
            print(f"합계 {total:,}건 — 삭제하려면 --execute 옵션으로 재실행하세요.")
            return

        if total == 0:
            print("삭제할 상품 없음.")
            return

        # 삭제 실행
        if count_no_img > 0:
            deleted1 = await conn.execute(
                """
                DELETE FROM samba_collected_product
                WHERE (images IS NULL
                   OR json_array_length(images) = 0)
                  AND COALESCE(lock_delete, false) = false
                """
            )
            print(f"대표이미지 누락 삭제 완료: {deleted1}")

        if count_bad_img > 0:
            deleted2 = await conn.execute(
                """
                DELETE FROM samba_collected_product
                WHERE source_site = 'SSG'
                  AND images IS NOT NULL
                  AND json_array_length(images) > 0
                  AND images->>0 NOT LIKE '%sitem.ssgcdn.com%'
                  AND COALESCE(lock_delete, false) = false
                """
            )
            print(f"SSG 비상품 이미지 삭제 완료: {deleted2}")

    finally:
        await conn.close()


if __name__ == "__main__":
    execute_flag = "--execute" in sys.argv
    asyncio.run(main(execute=execute_flag))
