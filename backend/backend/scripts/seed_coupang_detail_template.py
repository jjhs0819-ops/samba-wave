"""쿠팡 상세페이지 템플릿 시드 — 상단/하단 배너 업로드 + 템플릿 생성 + 정책 연결.

상세페이지 구성 (위 → 아래):
    [상단 배너]  ← 자체 제작물 (backend/static/banners/coupang_top.jpg)
    [대표 이미지]  ┐
    [추가 이미지]  ├ 소싱처 상품 이미지
    [상세 이미지]  ┘
    [하단 배너]  ← 자체 제작물 (backend/static/banners/coupang_bottom.jpg)

소싱처 상세페이지 HTML 을 그대로 쓰지 않는다(지재권). 이미지만 사용한다.

사용법:
    python -m backend.scripts.seed_coupang_detail_template --dry-run
    python -m backend.scripts.seed_coupang_detail_template --apply
    python -m backend.scripts.seed_coupang_detail_template --apply --top-cropped

옵션:
    --top-cropped  상단 배너를 리뷰 섹션 없이 자른 버전(coupang_top.jpg, 780x1424)
                   으로 등록. 기본값은 쇼팡 제공 원본(coupang_top_full.jpg, 780x3000).
                   원본 하단 1/3 에는 타 쇼핑몰 리뷰 캡처와 "누적 구매 건수
                   130,000건" 문구가 있다 (2026-07-22 사용자 확인 후 원본 채택).
"""

import argparse
import asyncio
import hashlib
import logging
import mimetypes
import sys
import warnings
from pathlib import Path
from typing import Any

# SQLModel 이 session.execute() 마다 exec() 권장 DeprecationWarning 을 30줄씩 뱉어
# 사람이 읽어야 할 시드 결과가 묻힌다. 이 스크립트에서만 억제.
warnings.filterwarnings("ignore", category=DeprecationWarning)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BANNER_DIR = Path(__file__).resolve().parent.parent / "static" / "banners"
TEMPLATE_NAME = "쿠팡 기본 상세 템플릿"

# 상세페이지 구성 — _build_detail_html 의 img_checks / img_order 규약
IMG_CHECKS: dict[str, bool] = {
    "topImg": True,  # 상단 배너
    "main": True,  # 대표 이미지
    "sub": True,  # 추가 이미지
    "title": False,  # 상품명 텍스트 — 쿠팡은 상품명이 별도 노출되므로 끔
    "option": False,  # 옵션 이미지 — 소싱처가 옵션별 이미지를 주지 않아 데이터 없음
    "detail": True,  # 상세 이미지 (detail_images)
    "sizeChart": False,  # 실측 사이즈표 — 가방은 해당 없음
    "bottomImg": True,  # 하단 배너
}
IMG_ORDER: list[str] = [
    "topImg",
    "main",
    "sub",
    "title",
    "option",
    "detail",
    "sizeChart",
    "bottomImg",
]


async def _upload_banner(session: Any, path: Path) -> str:
    """배너를 R2 에 업로드하고 공개 URL 반환. R2 미설정이면 빈 문자열.

    ImageTransformService._save_image 는 정사각형 padding 을 하므로 쓰지 않는다
    (780x2404 배너가 2404x2404 로 늘어남). 여기서는 원본 비율 그대로 올린다.
    """
    from backend.domain.samba.image.service import ImageTransformService

    svc = ImageTransformService(session)
    r2 = await svc._get_r2_client()
    if not r2:
        return ""

    client, bucket_name, public_url = r2
    data = path.read_bytes()
    content_hash = hashlib.md5(data).hexdigest()[:16]
    key = f"banners/{path.stem}_{content_hash}{path.suffix}"
    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"

    import io
    from functools import partial

    await asyncio.to_thread(
        partial(
            client.upload_fileobj,
            io.BytesIO(data),
            bucket_name,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": "public, max-age=31536000",
            },
        )
    )
    return f"{public_url}/{key}"


async def main(
    apply: bool, top_cropped: bool, top_url_arg: str = "", bottom_url_arg: str = ""
) -> int:
    from sqlmodel import select

    from backend.db.orm import get_write_session
    from backend.domain.samba.policy.model import SambaDetailTemplate, SambaPolicy

    top_name = "coupang_top.jpg" if top_cropped else "coupang_top_full.jpg"
    top_path = BANNER_DIR / top_name
    bottom_path = BANNER_DIR / "coupang_bottom.jpg"

    for p in (top_path, bottom_path):
        if not p.exists():
            logger.error(f"배너 파일 없음: {p}")
            return 1
    logger.info(f"상단 배너: {top_path.name} ({top_path.stat().st_size / 1024:.0f} KB)")
    logger.info(
        f"하단 배너: {bottom_path.name} ({bottom_path.stat().st_size / 1024:.0f} KB)"
    )

    async with get_write_session() as session:
        # --top-url/--bottom-url 로 이미 호스팅된 URL 을 주면 업로드를 건너뛴다
        # (R2 외 호스팅을 쓰는 경우).
        top_url = top_url_arg or await _upload_banner(session, top_path)
        bottom_url = bottom_url_arg or await _upload_banner(session, bottom_path)

        if not top_url or not bottom_url:
            logger.error(
                "\nR2(cloudflare_r2) 설정이 없어 배너를 올릴 곳이 없습니다.\n"
                "쿠팡은 상세 이미지를 URL 로 받아가므로 공개 접근 가능한 호스팅이 필요합니다.\n"
                "(localhost:28080/static 은 쿠팡 서버에서 접근 불가)\n"
                "해결: 설정 페이지에서 Cloudflare R2 자격증명 등록 후 재실행,\n"
                "      또는 --top-url / --bottom-url 로 이미 호스팅된 URL 직접 지정."
            )
            return 1

        logger.info(f"\n상단 URL: {top_url}")
        logger.info(f"하단 URL: {bottom_url}")

        # 템플릿 조회/생성 (이름 기준 멱등)
        tpl = (
            (
                await session.execute(
                    select(SambaDetailTemplate).where(
                        SambaDetailTemplate.name == TEMPLATE_NAME
                    )
                )
            )
            .scalars()
            .first()
        )

        if tpl:
            logger.info(f"\n기존 템플릿 갱신: {tpl.id}")
        else:
            tpl = SambaDetailTemplate(name=TEMPLATE_NAME)
            logger.info(f"\n신규 템플릿 생성: {tpl.id}")

        tpl.top_image_s3_key = top_url
        tpl.bottom_image_s3_key = bottom_url
        tpl.img_checks = IMG_CHECKS
        tpl.img_order = IMG_ORDER
        tpl.main_image_index = 0
        # 마켓 갤러리에는 대표이미지 1장만 — 추가이미지 미전송 방침
        tpl.gallery_include_sub = False

        # 쿠팡 정책에 연결
        policies = (await session.execute(select(SambaPolicy))).scalars().all()
        targets = [p for p in policies if "쿠팡" in (p.name or "")] or list(policies)
        for pol in targets:
            extras = dict(pol.extras or {})
            extras["detail_template_id"] = tpl.id
            pol.extras = extras
            logger.info(
                f"정책 연결: {pol.id} ({pol.name}) → detail_template_id={tpl.id}"
            )

        if not apply:
            logger.info("\n[dry-run] 저장하지 않았습니다. --apply 로 실행하세요.")
            await session.rollback()
            return 0

        session.add(tpl)
        for pol in targets:
            session.add(pol)
        await session.commit()
        logger.info("\n저장 완료.")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 저장 (없으면 dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 확인만 (기본값)")
    ap.add_argument(
        "--top-cropped",
        action="store_true",
        help="상단 배너를 리뷰 섹션 제거 버전으로 등록 (기본값은 쇼팡 제공 원본)",
    )
    ap.add_argument(
        "--top-url", default="", help="이미 호스팅된 상단 배너 URL (업로드 생략)"
    )
    ap.add_argument(
        "--bottom-url", default="", help="이미 호스팅된 하단 배너 URL (업로드 생략)"
    )
    args = ap.parse_args()
    sys.exit(
        asyncio.run(
            main(
                apply=args.apply,
                top_cropped=args.top_cropped,
                top_url_arg=args.top_url,
                bottom_url_arg=args.bottom_url,
            )
        )
    )
