from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.notice_utils import build_smartstore_notice


def test_build_smartstore_notice_truncates_oversized_string_fields() -> None:
    notice = build_smartstore_notice(
        {
            "category1": "신발",
            "name": "테스트 신발",
            "care_instructions": "a" * 1605,
            "quality_guarantee": "b" * 1602,
            "material": "합성가죽",
            "brand": "테스트브랜드",
        }
    )

    shoes_notice = notice["shoes"]

    assert notice["productInfoProvidedNoticeType"] == "SHOES"
    assert len(shoes_notice["caution"]) == 1500
    assert len(shoes_notice["warrantyPolicy"]) == 1500
    assert shoes_notice["caution"] == "a" * 1500
    assert shoes_notice["warrantyPolicy"] == "b" * 1500


# ── 더현대Hi 카테고리 고시그룹 회귀 (2026-07-14 전 카테고리 1,362개 전수 실측 기반) ──

from backend.domain.samba.proxy.notice_utils import (  # noqa: E402
    build_ssg_notice,
    detect_notice_group,
)


def _th_product(path: str, name: str = "") -> dict:
    segs = [s.strip() for s in path.split(" > ")]
    return {
        "category1": segs[0] if len(segs) > 0 else "",
        "category2": segs[1] if len(segs) > 1 else "",
        "category3": segs[2] if len(segs) > 2 else "",
        "category4": segs[3] if len(segs) > 3 else "",
        "category": path,
        "name": name,
    }


def test_thehyundai_composite_cat1_lejyeo_sports() -> None:
    """cat1 "레저/스포츠"(더현대 표기, "스포츠/레저"의 어순 반전)가 복합 cat1로
    처리돼 하위 품목이 sports(기타재화 고시)로 빠지지 않아야 한다."""
    assert detect_notice_group(_th_product("레저/스포츠 > 스포츠 슈즈 > 여성스포츠화 > 러닝/조깅/워킹화")) == "shoes"
    assert detect_notice_group(_th_product("레저/스포츠 > 일반스포츠 > 남성/공용의류 > 하의")) == "wear"
    assert detect_notice_group(_th_product("레저/스포츠 > 워터 > 실내수영복 > 반신수영복")) == "wear"


def test_thehyundai_exact_sports_not_hijacking_items() -> None:
    """cat2 "골프"(exact sports)가 하위 품목(모자/가방/신발)을 가로채지 않아야 한다.
    미수정 시 sports → SSG 의류 고시 폴백으로 잡화/가방 고시 항목 불일치."""
    assert detect_notice_group(_th_product("레저/스포츠 > 골프 > 모자/헤어밴드 > 볼캡")) == "accessories"
    assert detect_notice_group(_th_product("레저/스포츠 > 골프 > 골프백/캐디백 > 캐디백")) == "bag"
    assert detect_notice_group(_th_product("레저/스포츠 > 골프 > 골프화 > 스파이크")) == "shoes"
    assert detect_notice_group(_th_product("레저/스포츠 > 데일리 > 하계화 > 슬리퍼/샌들")) == "shoes"
    # 진짜 장비는 sports 유지 (SSG 에서 의류 고시로 안전 폴백)
    assert detect_notice_group(_th_product("레저/스포츠 > 캠핑/아웃도어 > 숙영장비 > 텐트/타프/그늘막")) == "sports"


def test_thehyundai_cat4_exact_and_vocab() -> None:
    """cat4 정확 매칭 지원 + 더현대 어휘(쥬얼리 철자/유아동 의류) 보강 회귀."""
    assert detect_notice_group(_th_product("패션 > 워치/쥬얼리 > 목걸이")) == "accessories"
    assert detect_notice_group(_th_product("유아동/패밀리 > 토들러패션 > 바지/레깅스")) == "wear"
    assert detect_notice_group(_th_product("유아동/패밀리 > 유아패션 > 우주복")) == "wear"
    assert detect_notice_group(_th_product("레저/스포츠 > 워터 > 수상레저/서핑/스노클링 > 수모/수경")) == "accessories"


def test_build_ssg_notice_caution_from_care_instructions() -> None:
    """취급주의: 소싱 care_instructions 폴백 — 긴 실문구는 '참조' 포함해도 채택,
    짧은 모호값("상세페이지 참조")은 여전히 필터."""
    long_care = "세탁 가능 여부는 상품 택을 참조 하십시오. " * 3
    _, attrs = build_ssg_notice(
        {**_th_product("레저/스포츠 > 스포츠 슈즈 > 여성스포츠화"), "care_instructions": long_care}
    )
    caution = next(a for a in attrs if a["itemMngPropId"] == "0000000013")
    assert caution["itemMngCntt"].startswith("세탁 가능 여부는")
    assert len(caution["itemMngCntt"]) <= 250

    _, attrs2 = build_ssg_notice(
        {**_th_product("레저/스포츠 > 스포츠 슈즈 > 여성스포츠화"), "care_instructions": "상세페이지 참조"}
    )
    caution2 = next(a for a in attrs2 if a["itemMngPropId"] == "0000000013")
    assert caution2["itemMngCntt"] == "상세페이지 참조"  # fallback 유지


def test_build_ssg_notice_size_from_size_notice() -> None:
    """치수: 더현대 mndr '치수'(size_notice) → shoes 0000000170 실값."""
    _, attrs = build_ssg_notice(
        {**_th_product("레저/스포츠 > 스포츠 슈즈 > 여성스포츠화"), "size_notice": "230-260"}
    )
    size = next(a for a in attrs if a["itemMngPropId"] == "0000000170")
    assert size["itemMngCntt"] == "230-260"
