"""tcg_vault 포스트잇 Gemini 합성 [컨테이너 실행].

카드 이미지 URL → 하단 가로 포스트잇('tcg_vault') 합성 → 저장.
반드시 생성 후 사람이(또는 Claude가) 육안검증: 상품 사라짐/포스트잇만/가림 여부.

실행:
  docker cp samba-tools/ebay_sourcing/postit.py local-samba-api-1:/tmp/postit.py
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/postit.py \
    "<카드이미지URL>" /tmp/out.jpg
  docker cp local-samba-api-1:/tmp/out.jpg ./out.jpg   # 빼서 육안확인
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
PROMPT = (
    "Place a small WIDE horizontal rectangular sticky note (thin label strip, 4:1 to "
    "5:1 ratio) at the very BOTTOM edge of the image, on the surface BELOW the card. It "
    "must NOT overlap or cover the card at all — keep the whole card fully visible. Write "
    "'tcg_vault' on the strip in neat handwritten black marker, centered. Pale yellow "
    "paper, photorealistic, soft shadow, matching lighting. Do NOT change the card or "
    "background."
)


async def main():
    import httpx

    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.image.service import ImageTransformService

    card_url, out_path = sys.argv[1], sys.argv[2]
    tok = current_tenant_id.set(TENANT)
    try:
        card = httpx.get(card_url, timeout=30).content
        async with get_write_session() as s:
            svc = ImageTransformService(s)
            key, model = await svc._get_gemini_config()
            out = await svc._transform_image_gemini(key, model, card, PROMPT, None)
        with open(out_path, "wb") as f:
            f.write(out)
        print("OK", len(out), "bytes →", out_path)
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
