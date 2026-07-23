"""실물 tcg-vault 포스트잇을 상품 사진에 합성 [컨테이너 실행].

Gemini 에게 포스트잇을 "그리게" 하면 글씨체가 매번 다르고 상품이 사라지는 사고가 났다.
그래서 사용자가 직접 찍은 실물 포스트잇 사진(assets/postit_cut.png)을 두 번째 이미지로
같이 넣어 "이 종이를 그대로 놓아라"라고 지시한다. 글씨는 항상 동일한 실물이 된다.

PIL 로 덧붙이면 합성 티가 나므로 쓰지 않는다.

실행:
  docker cp samba-tools/ebay_sourcing/postit_real.py local-samba-api-1:/tmp/postit_real.py
  docker cp samba-tools/ebay_sourcing/assets/postit_cut.png local-samba-api-1:/tmp/postit_cut.png
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/postit_real.py "<상품이미지URL>" /tmp/out.jpg
"""

import asyncio
import base64
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
POSTIT = "/tmp/postit_small.png"
MAX_TRY = 8      # Gemini 크기 랜덤 → 기준 맞을 때까지 재생성
MAX_RATIO = 0.62  # 포스트잇 가로 = 상품 가로의 절반 (실측 보정 포함)

PROMPT = (
    "You are given two photos. The FIRST photo is a product. The SECOND photo is a real "
    "yellow paper note with the handwritten text 'tcg-vault'.\n"
    "Task: place that EXACT note from the second photo into the first photo, lying flat on "
    "the surface DIRECTLY BELOW the product — horizontally centered on the product, just under "
    "its bottom edge, as if someone physically put it there. Never beside the product, never "
    "above it, never off to one side.\n"
    "Hard rules:\n"
    "1. Use the note exactly as it appears in the second photo — same paper, same handwriting. "
    "Do NOT redraw, re-letter, or restyle the text.\n"
    "2. Do NOT cover, crop, move, recolor or alter the product in any way. The whole product "
    "must stay fully visible exactly as in the first photo.\n"
    "3. The note must rest ON the same surface, matching that surface's perspective, with a "
    "soft contact shadow under its lower edge so it does not look like it floats.\n"
    "3b. SIZE (critical, most common failure): measure the product's width in pixels, call it "
    "P. The note's width must be 0.5 x P — if the product is 600 px wide the note must be "
    "about 300 px wide, NOT 800 px. The note's left edge must be to the RIGHT of the product's "
    "left edge and its right edge to the LEFT of the product's right edge, so the note sits "
    "entirely inside the product's vertical band. A note wider than the product is a failure.\n"
    "4. Match the first photo's lighting, white balance and grain so it looks like one photo.\n"
    "5. Keep the original background and the SAME framing: identical aspect ratio and zoom "
    "as the first photo. Do NOT widen the canvas, do NOT add empty space around the scene, "
    "do NOT zoom out. The product must fill the frame just like in the first photo.\n"
    "6. If there is no free surface below the product, let the note slightly overlap the "
    "bottom edge of the frame instead of shrinking the product."
)


def note_ratio(img_bytes: bytes) -> float:
    """포스트잇 가로 / 상품 가로 비율.

    Gemini 는 크기 지시를 자주 무시한다(같은 프롬프트로 1.27~1.88 랜덤).
    그래서 생성물을 직접 재보고 기준을 넘으면 다시 뽑는다. 반환 -1 = 측정 실패.
    """
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(io.BytesIO(img_bytes)).convert("RGB")).astype(int)
    h = a.shape[0]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    sat = a.max(axis=2) - a.min(axis=2)
    # 상품 폭: 상단 60% 에서 채도 있는 열. 슬리브는 무채색이라 아트 폭의 1.35배로 본다(실측 보정).
    # 포스트잇 윗부분이 상단 60% 안까지 올라오면 상품으로 오인되므로 노란 화소는 뺀다.
    note_px = (r > 150) & (g > 140) & (b < r - 20) & (b < g - 15)
    top = (sat[: int(h * 0.6)] > 40) & ~note_px[: int(h * 0.6)]
    cols = np.nonzero(top.sum(axis=0) > 15)[0]
    if not len(cols):
        return -1.0
    product_w = (cols.max() - cols.min()) * 1.35

    # 포스트잇: 하단 40% 에서 "세로로 꽉 찬" 노란 열만. 카드 아트의 노란 부분은
    # 세로로 이어지지 않으므로 이 조건으로 걸러진다(2026-07-23 오측정 수정).
    band = a[int(h * 0.6):]
    br, bg, bb = band[:, :, 0], band[:, :, 1], band[:, :, 2]
    yellow = (br > 150) & (bg > 140) & (bb < br - 20) & (bb < bg - 15)
    # 손글씨 획이 세로로 관통하는 열은 노란색이 끊기므로 "최장 연속 구간"으로 재면
    # 폭이 과소평가된다. 좌우 끝 사이 거리로 잰다.
    solid = np.nonzero(yellow.sum(axis=0) > band.shape[0] * 0.35)[0]
    if len(solid) < 10:
        return -1.0
    return float((solid.max() - solid.min()) / product_w)


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.image.service import ImageTransformService

    src_url, out_path = sys.argv[1], sys.argv[2]
    tok = current_tenant_id.set(TENANT)
    try:
        product = httpx.get(src_url, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0",
                                     "Referer": "https://m.bunjang.co.kr/"}).content
        note = open(POSTIT, "rb").read()

        async with get_write_session() as s:
            key, model = await ImageTransformService(s)._get_gemini_config()

        body = {
            "contents": [{"parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": "image/jpeg",
                                 "data": base64.b64encode(product).decode("ascii")}},
                {"inline_data": {"mime_type": "image/png",
                                 "data": base64.b64encode(note).decode("ascii")}},
            ]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        best, best_ratio = None, 99.0
        async with httpx.AsyncClient(timeout=180) as c:
            for tri in range(MAX_TRY):
                r = await c.post(url, json=body, headers={"Content-Type": "application/json"})
                if r.status_code == 429:
                    await asyncio.sleep(30 * (tri + 1))
                    continue
                r.raise_for_status()
                out = None
                for part in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
                    if "inlineData" in part:
                        out = base64.b64decode(part["inlineData"]["data"])
                        break
                if not out:
                    continue
                ratio = note_ratio(out)
                print(f"  시도{tri + 1} 포스트잇/상품 비율 {ratio:.2f}")
                if 0 < ratio < best_ratio:
                    best, best_ratio = out, ratio
                if 0 < ratio <= MAX_RATIO:
                    break
        if not best:
            print("실패: 이미지 파트 없음")
            return
        open(out_path, "wb").write(best)
        print(f"OK {len(best)} bytes 비율 {best_ratio:.2f} → {out_path}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
