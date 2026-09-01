"""buyma_watch 출품목록 → SambaCollectedProduct.images 재정렬 (오토튠 대표이미지 롤백 방지).

[배경]
오토튠 재전송(BuymaPlugin.execute → BuymaClient.transform_product)은 상품 이미지를
product["images"] 순서 그대로 바이마에 보내며 images[0]이 대표(position 1)가 된다.
그런데 백필(PR #759)은 images 필드를 채우지 않으므로, DB의 SambaCollectedProduct.images
가 무신사 원본 순서(인물/뒷면 포함 가능)로 남아 있으면 — CSV 일괄편집으로 고쳐둔
정면 대표가 오토튠 재전송 시 원본 순서로 롤백된다.

[해결]
정면 대표가 이미 반영된 buyma_watch 출품목록(items.utf8.csv)의 商品イメージ1~20
순서를 그대로 DB.images 에 반영한다. 그러면 오토튠이 재전송해도 images[0]=정면대표라
롤백되지 않는다. detail_images 는 건드리지 않는다(대표는 images 만 사용).

[전제]
- buyma_watch 의 출품목록은 '정면대표가 반영 완료된' 최신 다운로드여야 한다
  (CSV 업로드 → 바이마 반영 대기 → 그 후 다운로드한 것).
- 매칭키: 출품목록 商品管理番号 == SambaCollectedProduct.site_product_id (무신사 goodsNo).

사용:
  python scripts/buyma_reorder_images.py <items.utf8.csv경로>            # dry(변경 미리보기)
  python scripts/buyma_reorder_images.py <items.utf8.csv경로> --go       # 실제 반영
  옵션 --source-site musinsa (기본), --limit N
"""

import argparse
import asyncio
import csv
import sys

try:  # Windows cp949 콘솔에서 이모지/특수문자 print 크래시 방지
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlmodel import select

from backend.db.orm import get_write_session
from backend.domain.samba.collector.model import SambaCollectedProduct

IMG_COLS = [f"商品イメージ{i}" for i in range(1, 21)]


def load_listing(path: str) -> dict[str, list[str]]:
    """출품목록 CSV → {商品管理番号: [이미지URL 순서대로]}."""
    out: dict[str, list[str]] = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            no = (r.get("商品管理番号") or "").strip()
            if not no:
                continue
            imgs = [(r.get(c) or "").strip() for c in IMG_COLS]
            imgs = [u for u in imgs if u]
            if imgs:
                out[no] = imgs
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", help="buyma_watch 출품목록 items.utf8.csv 경로")
    ap.add_argument("--go", action="store_true", help="실제 DB 반영 (없으면 dry)")
    ap.add_argument("--source-site", default="musinsa")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    listing = load_listing(args.csv_path)
    print(f"출품목록: {len(listing)}건 (이미지 있는 것)")
    if not listing:
        print("⚠️ 출품목록이 비었거나 商品イメージ 컬럼 없음 — 중단.")
        return

    nos = list(listing.keys())
    if args.limit:
        nos = nos[: args.limit]

    matched = changed = missing = 0
    samples = []
    async with get_write_session() as session:
        for no in nos:
            stmt = select(SambaCollectedProduct).where(
                SambaCollectedProduct.site_product_id == no,
                SambaCollectedProduct.source_site == args.source_site,
            )
            row = (await session.execute(stmt)).scalars().first()
            if not row:
                missing += 1
                continue
            matched += 1
            new_imgs = listing[no]
            old_imgs = list(row.images or [])
            if old_imgs == new_imgs:
                continue  # 이미 동일
            changed += 1
            if len(samples) < 5:
                samples.append(
                    (no, (old_imgs[0] if old_imgs else "∅")[:55], new_imgs[0][:55])
                )
            if args.go:
                row.images = new_imgs  # 리스트 재할당(변경감지 보장)
                session.add(row)
        if args.go:
            await session.commit()

    print(f"\n매칭 {matched} / DB에 없음 {missing} / 변경대상 {changed}")
    print("샘플(현 images[0] → 새 images[0]):")
    for no, o, n in samples:
        print(f"  {no}: {o}\n            → {n}")
    print("\n" + ("✅ 실제 반영 완료(--go)" if args.go else "DRY — 실제 반영은 --go"))


if __name__ == "__main__":
    asyncio.run(main())
