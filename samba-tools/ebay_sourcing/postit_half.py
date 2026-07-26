"""포스트잇을 카드 가로의 정확히 절반 크기로 결정론 합성 [컨테이너 실행].

Gemini 에게 크기를 맡기면 매번 랜덤(카드보다 큰 포스트잇이 통과). 그래서 크기를
사람이 정한다: 카드 폭을 검출 → 포스트잇 폭 = 카드 폭 x 0.5 로 강제 붙인다.

카드 검출: 채도(홀로 무지개) 마스크를 침식해 손가락 연결을 끊고, 최대 연결블롭의
bbox 를 카드로 본다. 배경은 상단 테두리 색으로 채워 정사각형으로 만든다.

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
from PIL import Image, ImageFilter  # noqa: E402
from scipy import ndimage  # noqa: E402

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"
POSTIT = "/tmp/postit_cut.png"
NOTE_RATIO = 0.5  # 포스트잇 가로 = 카드 가로의 절반
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
    ring = np.concatenate([
        a[:bt].reshape(-1, 3), a[-bt:].reshape(-1, 3),
        a[:, :bs].reshape(-1, 3), a[:, -bs:].reshape(-1, 3)])
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
    cols = np.where(m[y0:y1 + 1].sum(0) > 0.30 * (y1 - y0 + 1))[0]
    if len(cols) < 3:
        xs = np.where(m.any(0))[0]
        x0, x1 = int(xs.min()), int(xs.max())
    else:
        x0, x1 = int(cols.min()), int(cols.max())
    pad = max(2, w // 250)
    return (max(0, x0 - pad), max(0, y0 - pad),
            min(w - 1, x1 + pad), min(h - 1, y1 + pad))


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


def extract_paper(path: str) -> Image.Image:
    """긴 노란 포스트잇에서 종이만 잘라 RGBA(흰 바탕 투명)."""
    p = Image.open(path).convert("RGB")
    a = np.asarray(p).astype(int)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = a.max(2)
    sat = mx - a.min(2)
    # 흰 바탕 = 밝고 무채색. 종이(노랑)+글씨(검정)는 아님.
    is_white = (mx > 205) & (sat < 25)
    paper = ~is_white
    paper = ndimage.binary_closing(paper, iterations=3)
    ys, xs = np.where(paper)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    crop = a[y0:y1 + 1, x0:x1 + 1]
    alpha = (~is_white[y0:y1 + 1, x0:x1 + 1]).astype(np.uint8) * 255
    rgba = np.dstack([crop.astype(np.uint8), alpha])
    return Image.fromarray(rgba, "RGBA")


def _paste_note(canvas, note, nx, ny, note_w, note_h):
    sh = Image.new("RGBA", (note_w, note_h), (0, 0, 0, 0))
    sh.paste((0, 0, 0, 80), (0, 0, note_w, note_h))
    sh = sh.filter(ImageFilter.GaussianBlur(max(3, note_h // 12)))
    canvas.paste(sh, (nx, ny + max(2, note_h // 20)), sh)
    canvas.paste(note, (nx, ny), note)


def compose(src: Image.Image, paper_src: Image.Image) -> Image.Image:
    """① 정사각 크롭 먼저(번장 사진 대부분 정사각, 길면 잘라냄) → ② 그 안에 포스트잇을
    카드폭 0.5로 얹는다. 배경색 패딩/채우기 절대 없음. 포스트잇은 항상 크롭 안에 보인다."""
    src = src.convert("RGB")
    w, h = src.size
    x0, y0, x1, y1 = detect_card_bbox(src)
    card_w, card_h = x1 - x0, y1 - y0
    cx = (x0 + x1) // 2

    note_w = max(40, int(card_w * NOTE_RATIO))
    note_h = int(note_w * paper_src.height / paper_src.width)
    note = paper_src.resize((note_w, note_h), Image.LANCZOS)
    mg = max(6, min(w, h) // 60)
    gap = max(8, int(card_h * 0.04))
    side = min(w, h)

    # 포스트잇 = 카드 바로 아래. 카드+포스트잇이 정사각에 안 들어가면 카드 하단에 겹쳐 얹음
    # (손 아래 천에 뜨는 것 방지 — 항상 카드에 붙어있게)
    note_top = y1 + gap
    if (note_top + note_h) - y0 > side - mg:
        note_top = y1 - note_h - gap  # 카드 하단 위에 얹기
        note_top = max(note_top, y0 + card_h // 3)
    note_bottom = note_top + note_h
    nx = min(max(cx - note_w // 2, 0), w - note_w)

    canvas = src.copy()
    _paste_note(canvas, note, nx, note_top, note_w, note_h)

    # 정사각 크롭 = 카드 상단부터 포스트잇 하단까지 담게(카드 안 자름, 패딩 없음)
    top = y0 - mg
    if note_bottom + mg > top + side:      # 포스트잇이 크롭 밖이면 아래로 밀되
        top = note_bottom + mg - side
    top = min(max(top, 0), h - side)
    left = min(max(cx - side // 2, 0), w - side)
    return canvas.crop((left, top, left + side, top + side))


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
    paper = extract_paper(POSTIT)
    print(f"포스트잇 종이 {paper.size}, 비율 {NOTE_RATIO}")
    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            acc = (await s.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.id == KV))).scalars().first()
            svc = ImageTransformService(s)
            async with httpx.AsyncClient(timeout=40, headers=H) as c:
                for sku, (nm, pid) in TARGETS.items():
                    url = f"https://media.bunjang.co.kr/product/{pid}_1_w856.jpg"
                    raw = (await c.get(url)).content
                    src = Image.open(io.BytesIO(raw))
                    out = compose(src, paper)
                    buf = io.BytesIO()
                    out.save(buf, "JPEG", quality=92)
                    open(f"/tmp/half_{nm}.jpg", "wb").write(buf.getvalue())
                    print(f"[{nm}] 생성 {out.size} → /tmp/half_{nm}.jpg")
                    if not apply:
                        continue
                    p = (await s.execute(select(SambaCollectedProduct).where(
                        SambaCollectedProduct.id == sku))).scalars().first()
                    lid = (p.market_product_nos or {}).get(KV, "")
                    new_url = await svc._save_image(buf.getvalue(), url)
                    p.images = [new_url] + list(p.images or [])[1:]
                    s.add(p)
                    await s.commit()
                    cat = "108857" if p.applied_policy_id in (
                        "pol_kpopcard_v1", "pol_kpopgoods_v1") else "183454"
                    res = await dispatch_to_market(
                        s, "ebay", p.model_dump(), category_id=cat,
                        account=acc, existing_product_no=lid)
                    print(f"[{nm}] eBay revise {'OK' if res.get('success') else res.get('message')}")
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
