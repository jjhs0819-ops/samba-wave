"""gemini-3.1-flash-image 로 카드+포스트잇 합성 재시도."""

import asyncio
import base64
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

MODEL = "gemini-3.1-flash-image"
POSTIT = "/tmp/postit_small.png"

PROMPT = (
    "이 카드 사진을 나무 책상 위에 놓고, 카드 바로 아래에 두번째 사진 속 실물 포스트잇을 "
    "그대로 놓아줘. 정사각형 사진으로."
)


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.image.service import ImageTransformService

    src_url, out_path = sys.argv[1], sys.argv[2]
    tok = current_tenant_id.set("tn_01KRX6H1Q97JGPXRPB011985QT")
    try:
        product = httpx.get(src_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).content
        note = open(POSTIT, "rb").read()

        async with get_write_session() as s:
            key, _ = await ImageTransformService(s)._get_gemini_config()

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
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}"
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(url, json=body, headers={"Content-Type": "application/json"})
            print("status:", r.status_code)
            if r.status_code != 200:
                print(r.text[:2000])
                return
            out = None
            for part in r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in part:
                    out = base64.b64decode(part["inlineData"]["data"])
                    break
        if not out:
            print("실패: 이미지 파트 없음")
            print(r.json())
            return
        open(out_path, "wb").write(out)
        print(f"OK {len(out)} bytes -> {out_path}")
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
