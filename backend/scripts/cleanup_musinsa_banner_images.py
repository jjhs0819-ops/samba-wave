# -*- coding: utf-8 -*-
"""#420 후속 — 기존 DB images/image_mirror_map 의 msscdn 배너 URL 정정.

MUSINSA 상품의 images 배열 + image_mirror_map 키에서 _is_msscdn_banner_url 로
판별되는 배너/이벤트/공지 URL 을 제거한다.

MODE:
  scan (기본) — 영향 상품 수·총 배너 URL·삭제대상 샘플·0이미지 위험 집계(쓰기 없음)
  fix          — 실제 정정 UPDATE

안전장치(fix): 배너 제거 시 images 가 0개가 되는 상품은 SKIP(상품이미지 전멸 방지).

실행(컨테이너): /app/backend/.venv/bin/python3 /tmp/cb.py [scan|fix]
"""

import asyncio
import sys
import traceback

from sqlalchemy import select, update
from sqlalchemy.orm import load_only

from backend.db.orm import get_write_session
from backend.domain.samba.collector.model import SambaCollectedProduct as CP

BATCH = 500

# 엄격 배너 판별 — 진짜 상품이미지(goods_img/prd_img)는 보존하고
# 명백한 배너/이벤트/공지 경로 + 깨진 JS 템플릿 URL 만 제거.
# (_is_msscdn_banner_url 는 prd_img-without-detail_ 까지 배너로 오판 → 일괄삭제 부적합)
_BANNER_PATH_MARKERS = (
    "/display/images/",
    "/banner",
    "/event",
    "/contents",
    "/common/",
    "/notice",
)
_BROKEN_MARKERS = ("%24", "${", "$(this", "data(", "{$")


def _is_banner(url: object) -> bool:
    if not isinstance(url, str) or not url:
        return False
    low = url.lower()
    if "msscdn.net" not in low:
        return False
    # 깨진 JS 템플릿 누수 URL → 무조건 제거
    if any(m in low for m in _BROKEN_MARKERS):
        return True
    # 진짜 상품 이미지 경로 보존
    if "/images/goods_img/" in low or "/images/prd_img/" in low:
        return False
    # 명백한 배너/이벤트/공지 경로만 제거
    return any(m in low for m in _BANNER_PATH_MARKERS)


async def run(mode: str) -> None:
    affected = 0
    total_banner_imgs = 0
    total_banner_keys = 0
    zero_guard_skipped = 0
    updated = 0
    samples: list[str] = []
    scanned = 0
    last_id = ""

    async with get_write_session() as session:
        while True:
            rows = (
                (
                    await session.execute(
                        select(CP)
                        .options(load_only(CP.id, CP.images, CP.image_mirror_map))
                        .where(CP.source_site == "MUSINSA", CP.id > last_id)
                        .order_by(CP.id)
                        .limit(BATCH)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                break
            for p in rows:
                last_id = p.id
                scanned += 1
                imgs = list(p.images or [])
                mmap = dict(p.image_mirror_map or {})
                banner_imgs = [u for u in imgs if isinstance(u, str) and _is_banner(u)]
                banner_keys = [k for k in mmap if isinstance(k, str) and _is_banner(k)]
                if not banner_imgs and not banner_keys:
                    continue
                affected += 1
                total_banner_imgs += len(banner_imgs)
                total_banner_keys += len(banner_keys)
                if len(samples) < 25:
                    for u in banner_imgs + banner_keys:
                        if u not in samples:
                            samples.append(u)
                        if len(samples) >= 25:
                            break

                new_imgs = [
                    u for u in imgs if not (isinstance(u, str) and _is_banner(u))
                ]
                new_map = {
                    k: v
                    for k, v in mmap.items()
                    if not (isinstance(k, str) and _is_banner(k))
                }
                # 0이미지 방어 — 원래 이미지가 있었는데 전부 배너로 판정되면 SKIP
                if imgs and not new_imgs:
                    zero_guard_skipped += 1
                    if mode == "fix":
                        continue

                if mode == "fix":
                    _vals = {}
                    if new_imgs != imgs:
                        _vals["images"] = new_imgs
                    if new_map != mmap:
                        _vals["image_mirror_map"] = new_map
                    if _vals:
                        await session.execute(
                            update(CP).where(CP.id == p.id).values(**_vals)
                        )
                        updated += 1
            if mode == "fix":
                await session.commit()
            print(
                f"  ...진행 scanned={scanned} affected={affected} updated={updated}",
                flush=True,
            )

    print("\n===== 결과 =====", flush=True)
    print(f"MODE: {mode}", flush=True)
    print(f"스캔 상품: {scanned}", flush=True)
    print(f"영향 상품(배너 보유): {affected}", flush=True)
    print(f"제거 대상 images URL: {total_banner_imgs}", flush=True)
    print(f"제거 대상 mirror_map 키: {total_banner_keys}", flush=True)
    print(f"0이미지 위험 SKIP: {zero_guard_skipped}", flush=True)
    if mode == "fix":
        print(f"실제 UPDATE: {updated}", flush=True)
    print("\n--- 제거 대상 URL 샘플(최대 25) ---", flush=True)
    for u in samples:
        print(f"  {u}", flush=True)


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if mode not in ("scan", "fix"):
        print("MODE 는 scan|fix", flush=True)
        return
    try:
        await run(mode)
    except Exception:
        print(traceback.format_exc(), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
