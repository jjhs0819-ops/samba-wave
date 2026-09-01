"""실물 tcg-vault 포스트잇을 크림(KREAM) 소싱 상품 사진에 합성 [1회 테스트, 컨테이너 실행].

postit_real.py(git f0fa92fc, 2026-07-30 이전 최종본)를 크림 소싱용으로 Referer만 조정.
사용자 명시 요청으로 금지 해제 후 1회 테스트.
"""

import asyncio
import base64
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
POSTIT = "/tmp/postit_small.png"
MAX_TRY = 8
MAX_RATIO = 0.62

PROMPT = (
    "이 카드 사진을 나무 책상 위에 놓고, 카드 바로 아래에 두번째 사진 속 실물 포스트잇을 "
    "그대로 놓아줘. 정사각형 사진으로."
)


def note_ratio(img_bytes: bytes) -> float:
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(io.BytesIO(img_bytes)).convert("RGB")).astype(int)
    h = a.shape[0]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    sat = a.max(axis=2) - a.min(axis=2)
    note_px = (r > 150) & (g > 140) & (b < r - 20) & (b < g - 15)
    top = (sat[: int(h * 0.6)] > 40) & ~note_px[: int(h * 0.6)]
    cols = np.nonzero(top.sum(axis=0) > 15)[0]
    if not len(cols):
        return -1.0
    product_w = (cols.max() - cols.min()) * 1.35

    band = a[int(h * 0.6):]
    br, bg, bb = band[:, :, 0], band[:, :, 1], band[:, :, 2]
    yellow = (br > 150) & (bg > 140) & (bb < br - 20) & (bb < bg - 15)
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
                            headers={"User-Agent": "Mozilla/5.0"}).content
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
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"aspectRatio": "1:1"},
            },
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

        # Gemini 가 캔버스를 옆으로 늘리는 경우 대비 — 정사각형 아니면 중앙 크롭으로 강제
        from PIL import Image
        im = Image.open(io.BytesIO(best))
        w, h = im.size
        if w != h:
            side = min(w, h)
            left = (w - side) // 2
            top = 0  # 포스트잇이 하단에 있으므로 위쪽 기준 크롭(하단 잘림 방지)
            im2 = im.crop((left, top, left + side, top + side))
            buf = io.BytesIO()
            im2.save(buf, format="JPEG", quality=92)
            best = buf.getvalue()
            print(f"  캔버스 {w}x{h} -> 정사각 {side}x{side} 강제 크롭")

        open(out_path, "wb").write(best)
        print(f"OK {len(best)} bytes 비율 {best_ratio:.2f} -> {out_path}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
