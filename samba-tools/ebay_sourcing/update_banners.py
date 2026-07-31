"""상세 템플릿 상단 배너 이미지 교체 [컨테이너 실행].

배너 원본은 samba-tools/ebay_sourcing/*_banner.html 이고, 웨일 헤드리스로 렌더한다:
  whale.exe --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
            --window-size=1220,1160 --screenshot=out.png file:///.../card_banner.html

여기서는 렌더된 이미지를 R2 에 올리고 samba_detail_template.top_image_s3_key 를 갈아끼운다.

실행:
  docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/update_banners.py
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
# 템플릿ID → 렌더된 배너 파일 (컨테이너 /tmp 기준)
TARGETS = {
    "dt_kpopcard_v1": "/tmp/ban_card_fin.jpg",
    "dt_kpopalbum_v1": "/tmp/ban_album_fin.jpg",
    "dt_kpopgoods_v1": "/tmp/ban_goods_fin.jpg",
    "dt_01KXD39BCZACRDC1VP23TBP2MS": "/tmp/ban_card_fin.jpg",  # 이베이 기본 = 카드 배너
}
# 굿즈는 top_html 을 상세설명으로 쓰므로 HTML 도 같이 갱신
GOODS_HTML = ("dt_kpopgoods_v1", "/tmp/goods_description.html")


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_write_session
    from backend.domain.samba.image.service import ImageTransformService
    from sqlalchemy import text as t

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_write_session() as s:
            svc = ImageTransformService(s)
            cache: dict[str, str] = {}
            for tid, path in TARGETS.items():
                if path not in cache:
                    cache[path] = await svc._save_image(open(path, "rb").read(), path)
                await s.execute(
                    t(
                        "UPDATE samba_detail_template SET top_image_s3_key = :u WHERE id = :i"
                    ),
                    {"u": cache[path], "i": tid},
                )
                print(f"배너 교체 {tid} → {cache[path]}")

            tid, hp = GOODS_HTML
            html = open(hp, encoding="utf-8").read()
            if len(html) > 4000:
                print(
                    f"경고: 굿즈 상세 {len(html)}자 — eBay 한도 4,000자 초과라 반영 안 함"
                )
            else:
                await s.execute(
                    t("UPDATE samba_detail_template SET top_html = :h WHERE id = :i"),
                    {"h": html, "i": tid},
                )
                print(f"굿즈 상세 HTML 교체 {len(html)}자")
            await s.commit()
    finally:
        current_tenant_id.reset(tok)


asyncio.run(main())
