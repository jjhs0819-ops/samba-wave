"""대표사진 생성(카드 검출 + 정사각 크롭) [컨테이너 실행].

**포스트잇 합성·배경 패딩 없음** — 2026-07-30 영구 금지(오려붙인 티/가짜 배경으로
사용자 반복 격노). 파일명은 이력상 남아있을 뿐, 하는 일은 크롭뿐이다.
라이브 불량 일괄 교정은 `fix_no_postit.py` 가 담당한다.

카드 검출: 테두리 최빈색을 배경으로 보고 색차 마스크 → 최대 블롭 → 행/열 투영.

실행(생성만, eBay 미반영):
  docker cp postit_half.py local-samba-api-1:/tmp/postit_half.py
  docker cp assets/postit_cut.png local-samba-api-1:/tmp/postit_cut.png
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/postit_half.py --gen
실행(생성+eBay revise):
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/postit_half.py --apply
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.bunjang.co.kr/"}

# sku -> 번장 pid (사용자 확인 3건). 필요시 추가.
TARGETS = {
    "cp_01KWWF4RBX06V258JDD1CR2W6J": ("zapdos", "409126673"),
    "cp_01KWWEHX06394WCAT4KZS64NNT": ("ludicolo", "416718478"),
    "cp_01KXFWFTS3ZJ8RJZXG60GSHVMS": ("ninja", "420355046"),
    "cp_01KWWF5136G97Z0ZKC3CSZP4BG": ("zekrom", "418241162"),
}


def _bg_color(a: np.ndarray):
    """테두리 링의 최빈색 = 벽. 카드가 프레임을 꽉 채워도 벽이 테두리 다수면 정확.

    (모서리 중앙값은 카드가 하단폭을 채우면 카드색에 오염됨 → mode 사용)
    """
    h, w = a.shape[:2]
    bt = max(3, int(h * 0.04))
    bs = max(3, int(w * 0.04))
    ring = np.concatenate(
        [
            a[:bt].reshape(-1, 3),
            a[-bt:].reshape(-1, 3),
            a[:, :bs].reshape(-1, 3),
            a[:, -bs:].reshape(-1, 3),
        ]
    )
    q = (ring // 16) * 16
    keys, counts = np.unique(q, axis=0, return_counts=True)
    return keys[int(np.argmax(counts))].astype(float) + 8


def _bbox_from_mask(m: np.ndarray, w: int, h: int):
    """마스크 최대 블롭에서 행/열 투영으로 카드 사각형만 추출(손가락 등 좁은 돌출 제거)."""
    m = ndimage.binary_opening(m, iterations=1)
    lbl, n = ndimage.label(m)
    if n == 0:
        return None
    sizes = ndimage.sum(m, lbl, range(1, n + 1))
    m = lbl == (int(np.argmax(sizes)) + 1)
    rows_w = m.sum(1)
    maxw = rows_w[: int(h * 0.6)].max() if rows_w[: int(h * 0.6)].size else rows_w.max()
    maxw = max(maxw, rows_w.max() * 0.9)
    good = np.where(rows_w > 0.55 * maxw)[0]
    if len(good) < 3:
        ys, xs = np.where(m)
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    y0, y1 = int(good.min()), int(good.max())
    cols = np.where(m[y0 : y1 + 1].sum(0) > 0.30 * (y1 - y0 + 1))[0]
    if len(cols) < 3:
        xs = np.where(m.any(0))[0]
        x0, x1 = int(xs.min()), int(xs.max())
    else:
        x0, x1 = int(cols.min()), int(cols.max())
    pad = max(2, w // 250)
    return (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(w - 1, x1 + pad),
        min(h - 1, y1 + pad),
    )


def detect_card_bbox(img: Image.Image):
    """카드 bbox. 벽 배경과의 색차, 컬러 배경(매트)이면 밝기로 폴백."""
    a = np.asarray(img.convert("RGB")).astype(int)
    h, w = a.shape[:2]
    bg = _bg_color(a)
    bb = _bbox_from_mask(np.abs(a - bg).sum(2) > 45, w, h)
    if bb is None or (bb[2] - bb[0]) * (bb[3] - bb[1]) > 0.82 * w * h:
        lum = (a * [0.299, 0.587, 0.114]).sum(2)
        thr = max(140, np.median(lum) + 25)
        bb2 = _bbox_from_mask(lum > thr, w, h)
        if bb2 and (bb2[2] - bb2[0]) * (bb2[3] - bb2[1]) < 0.82 * w * h:
            return bb2
    return bb if bb else (0, 0, w - 1, h - 1)


def extract_paper(path: str) -> None:
    """[폐기] 포스트잇 종이 추출. 2026-07-30 포스트잇 합성 영구 금지로 제거.

    붙이는 도구가 남아 있으면 다시 쓰게 되므로 함수 본체를 없앤다.
    """
    raise RuntimeError(
        "포스트잇 합성 영구 금지(2026-07-30). fix_no_postit.py 를 쓸 것."
    )


def compose(src: Image.Image, paper_src=None) -> Image.Image:
    """대표사진 = 깨끗한 카드만. **포스트잇 합성 안 함**(컷아웃 사고 종결, 사용자 결정
    2026-07-27). 카드 중심으로 정사각 크롭 → 카드 얼굴/상단 안 잘림. 배경색 패딩 없음.
    paper_src 는 호환용 인자(사용 안 함)."""
    src = src.convert("RGB")
    w, h = src.size
    x0, y0, x1, y1 = detect_card_bbox(src)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    side = min(w, h)
    # 카드가 정사각에 다 들어가면 카드 전체를 담게 중심 정렬(얼굴 잘림 방지)
    left = min(max(cx - side // 2, 0), w - side)
    top = min(max(cy - side // 2, 0), h - side)
    return src.crop((left, top, left + side, top + side))


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.image.service import ImageTransformService
    from backend.domain.samba.shipment.dispatcher import dispatch_to_market
    from sqlmodel import select

    apply = "--apply" in sys.argv
    print("대표사진 = 원본 크롭만(포스트잇·패딩 없음)")
    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (
                (
                    await s.execute(
                        select(SambaMarketAccount).where(SambaMarketAccount.id == KV)
                    )
                )
                .scalars()
                .first()
            )
            svc = ImageTransformService(s)
            async with httpx.AsyncClient(timeout=40, headers=H) as c:
                for sku, (nm, pid) in TARGETS.items():
                    url = f"https://media.bunjang.co.kr/product/{pid}_1_w856.jpg"
                    raw = (await c.get(url)).content
                    src = Image.open(io.BytesIO(raw))
                    out = compose(src)
                    buf = io.BytesIO()
                    out.save(buf, "JPEG", quality=92)
                    open(f"/tmp/half_{nm}.jpg", "wb").write(buf.getvalue())
                    print(f"[{nm}] 생성 {out.size} → /tmp/half_{nm}.jpg")
                    if not apply:
                        continue
                    p = (
                        (
                            await s.execute(
                                select(SambaCollectedProduct).where(
                                    SambaCollectedProduct.id == sku
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    lid = (p.market_product_nos or {}).get(KV, "")
                    new_url = await svc._save_image(buf.getvalue(), url)
                    p.images = [new_url] + list(p.images or [])[1:]
                    s.add(p)
                    await s.commit()
                    cat = (
                        "108857"
                        if p.applied_policy_id
                        in ("pol_kpopcard_v1", "pol_kpopgoods_v1")
                        else "183454"
                    )
                    res = await dispatch_to_market(
                        s,
                        "ebay",
                        p.model_dump(),
                        category_id=cat,
                        account=acc,
                        existing_product_no=lid,
                    )
                    print(
                        f"[{nm}] eBay revise {'OK' if res.get('success') else res.get('message')}"
                    )
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
