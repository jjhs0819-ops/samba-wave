"""SSG 이상 수집 상품 삭제 스크립트.

잘못된 배너 이미지(연관기획전/포장안내 등)가 섞인 SSG 상품을 찾아 삭제.
판별 기준: images[0] URL에 site_product_id가 포함되지 않은 상품.

사용법:
  DRY_RUN=1  → 대상만 출력 (삭제 안함, 기본)
  DELETE=1   → 실제 삭제

실행:
  sudo docker cp delete_bad_ssg_images.py samba-samba-api-1:/tmp/
  sudo docker exec samba-samba-api-1 env DELETE=1 /app/backend/.venv/bin/python3 /tmp/delete_bad_ssg_images.py
"""

import asyncio
import os
import sys

sys.path.insert(0, "/app/backend")

import asyncpg
from backend.core.config import settings

DELETE_MODE = os.environ.get("DELETE", "").strip() == "1"


async def main():
    conn = await asyncpg.connect(
        host=settings.DB_WRITE_HOST,
        port=settings.DB_WRITE_PORT,
        user=settings.DB_WRITE_USER,
        password=settings.DB_WRITE_PASSWORD,
        database=settings.DB_WRITE_NAME,
        ssl="require",
    )

    rows = await conn.fetch("""
        SELECT id, site_product_id, images
        FROM samba_collected_product
        WHERE source_site = 'SSG'
          AND images IS NOT NULL
          AND jsonb_array_length(images) > 0
    """)

    print(f"SSG 이미지 보유 상품: {len(rows):,}개")

    bad_ids = []
    for r in rows:
        pid = str(r["site_product_id"] or "")
        if not pid:
            continue
        imgs = list(r["images"] or [])
        has_correct = any(pid in str(img) for img in imgs)
        if not has_correct:
            bad_ids.append(r["id"])

    print(f"이상 이미지(item_id 불일치): {len(bad_ids):,}개")

    if not bad_ids:
        print("삭제 대상 없음.")
        await conn.close()
        return

    # 샘플 10개 출력
    sample_rows = await conn.fetch("""
        SELECT id, site_product_id, name, images
        FROM samba_collected_product
        WHERE id = ANY($1::uuid[])
        LIMIT 10
    """, bad_ids)

    print("\n[샘플]")
    for s in sample_rows:
        imgs = list(s["images"] or [])
        print(f"  {s['site_product_id']} | {(s['name'] or '')[:35]} | {str(imgs[:1])[:80]}")

    if not DELETE_MODE:
        print("\nDRY RUN — 삭제 안함. 실제 삭제하려면 env DELETE=1 로 재실행.")
        await conn.close()
        return

    deleted = await conn.execute("""
        DELETE FROM samba_collected_product
        WHERE id = ANY($1::uuid[])
    """, bad_ids)
    print(f"\n삭제 완료: {deleted}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
