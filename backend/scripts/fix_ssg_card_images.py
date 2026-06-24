"""SSG 카드/UI 에셋 이미지 오염 정리.

sui.ssgcdn.com/ui/ssg/img/common/card/ 패턴 이미지가 images 배열에 들어간
SSG 상품을 찾아서:
  1. images 배열에서 카드 이미지 제거
  2. 마켓 등록된 상품은 계정별 delete_market Job 발행

실행:
  python scripts/fix_ssg_card_images.py [--dry-run]
"""

import asyncio
import json
import sys
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DRY_RUN = "--dry-run" in sys.argv

_CARD_PATTERNS = [
    "sui.ssgcdn.com/ui/ssg/img/common/card/",
    "sui.ssgcdn.com/ui/",
]


def _is_card_image(url: str) -> bool:
    if not url:
        return False
    return any(p in url for p in _CARD_PATTERNS)


def _clean_images(images: list) -> list:
    return [u for u in (images or []) if not _is_card_image(u)]


async def main():
    import asyncpg
    from backend.core.config import settings

    conn = await asyncpg.connect(
        host=settings.DB_WRITE_HOST,
        port=settings.DB_WRITE_PORT,
        database=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        ssl=settings.DB_WRITE_SSL,
    )

    try:
        rows = await conn.fetch(
            """
            SELECT id, site_product_id, images, registered_accounts,
                   brand, tenant_id
            FROM samba_collected_product
            WHERE source_site = 'SSG'
              AND images IS NOT NULL
            """
        )

        targets = []
        for row in rows:
            imgs = row["images"] or []
            if isinstance(imgs, str):
                try:
                    imgs = json.loads(imgs)
                except Exception:
                    imgs = []

            if not any(_is_card_image(u) for u in imgs):
                continue

            reg = row["registered_accounts"] or []
            if isinstance(reg, str):
                try:
                    reg = json.loads(reg)
                except Exception:
                    reg = []

            targets.append(
                {
                    "id": row["id"],
                    "site_product_id": row["site_product_id"],
                    "images": imgs,
                    "registered_accounts": reg,
                    "brand": row["brand"] or "",
                    "tenant_id": row["tenant_id"],
                }
            )

        print(f"카드 이미지 오염 상품: {len(targets)}개")
        registered = [t for t in targets if t["registered_accounts"]]
        print(f"  └ 마켓 등록된 상품: {len(registered)}개")

        if DRY_RUN:
            print("\n[DRY RUN] 샘플 5개:")
            for t in targets[:5]:
                card_imgs = [u for u in t["images"] if _is_card_image(u)]
                print(
                    f"  {t['site_product_id']}: 카드이미지 {len(card_imgs)}개"
                    f", 마켓등록={t['registered_accounts']}"
                )
            # 발행 예정 Job 목록
            job_groups: dict = defaultdict(list)
            for t in registered:
                for acct_id in t["registered_accounts"]:
                    key = (t["tenant_id"], acct_id, t["brand"])
                    job_groups[key].append(t["id"])
            print(f"\n발행 예정 delete_market Job: {len(job_groups)}개")
            for (tid, acct, brand), pids in list(job_groups.items())[:5]:
                print(f"  tenant={tid} acct={acct} brand={brand} 상품={len(pids)}개")
            return

        # 1) images 정리
        fixed = 0
        for t in targets:
            clean = _clean_images(t["images"])
            card_cnt = len(t["images"]) - len(clean)
            print(
                f"[{t['site_product_id']}] 카드이미지 {card_cnt}개 제거"
                f", 잔여 {len(clean)}개"
                f", 마켓등록={bool(t['registered_accounts'])}"
            )
            await conn.execute(
                """
                UPDATE samba_collected_product
                SET images = CAST($1 AS jsonb),
                    updated_at = NOW()
                WHERE id = $2
                """,
                json.dumps(clean),
                t["id"],
            )
            fixed += 1

        print(f"\nimages 정리 완료: {fixed}개")

        # 2) 마켓 등록 상품 → 계정×브랜드 단위 delete_market Job 발행
        job_groups: dict = defaultdict(list)
        for t in registered:
            for acct_id in t["registered_accounts"]:
                key = (t["tenant_id"], acct_id, t["brand"])
                job_groups[key].append(t["id"])

        job_cnt = 0
        for (tenant_id, acct_id, brand), product_ids in job_groups.items():
            job_id = str(uuid.uuid4()).replace("-", "")[:26]
            payload = {
                "product_ids": product_ids,
                "target_account_ids": [acct_id],
                "source_site": "SSG",
                "brand_name": brand,
            }
            await conn.execute(
                """
                INSERT INTO samba_jobs (id, tenant_id, job_type, status, payload, created_at, updated_at)
                VALUES ($1, $2, 'delete_market', 'pending', CAST($3 AS jsonb), NOW(), NOW())
                """,
                job_id,
                tenant_id,
                json.dumps(payload),
            )
            print(
                f"delete_market Job 발행: acct={acct_id} brand={brand} 상품={len(product_ids)}개"
            )
            job_cnt += 1

        print(f"\ndelete_market Job 발행: {job_cnt}개")
        print("완료.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
