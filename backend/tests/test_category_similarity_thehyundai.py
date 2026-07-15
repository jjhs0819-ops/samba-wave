"""더현대Hi 카테고리 → 마켓 유사도 매칭 회귀 (2026-07-14 운영 SSG 트리 실측 기반).

더현대는 5단 트리라 소스 leaf 가 스타일 수식어("데일리/하이브리드")여서
기존 leaf-필수 판정이 전부 None 을 반환했고, 품목 불일치 패널티 목록 부족으로
"아동운동화 → 주니어카시트" 오매칭이 있었다. 축소판 후보 리스트로 회귀 고정.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.category.rules import _similarity_match_smartstore

# 운영 SSG 트리(4,334개)의 관련 후보 축소판
_SSG_CANDIDATES = [
    "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 러닝화",
    "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 슬리퍼/샌들",
    "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 티셔츠",
    "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 반바지",
    "신세계몰메인매장 > 유모차/카시트/실내용품 > 카시트 > 주니어카시트",
    "신세계몰메인매장 > 명품잡화/아이웨어 > 아동화",
    "신세계몰메인매장 > 수영/수상레저 > 남성수영복/래쉬가드 > 래쉬가드",
]


def test_five_level_leaf_fallback_to_item_segment() -> None:
    """소스 leaf(수식어) 미매칭이어도 품목 세그먼트(마지막-1)로 폴백 매칭."""
    got = _similarity_match_smartstore(
        "레저/스포츠 > 스포츠 슈즈 > 여성스포츠화 > 러닝/조깅/워킹화 > 데일리/하이브리드",
        _SSG_CANDIDATES,
    )
    assert got == "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 러닝화"


def test_kids_sneakers_not_matched_to_carseat() -> None:
    """품목 불일치 패널티: 아동운동화가 주니어카시트로 가지 않고 아동화로."""
    got = _similarity_match_smartstore(
        "유아동/패밀리 > 신발/가방/잡화 > 아동운동화", _SSG_CANDIDATES
    )
    assert got == "신세계몰메인매장 > 명품잡화/아이웨어 > 아동화"


def test_swimwear_token_extraction() -> None:
    """"반신수영복" 합성어에서 수영복 토큰 추출 → 수영복 카테고리."""
    got = _similarity_match_smartstore(
        "레저/스포츠 > 워터 > 실내수영복 > 반신수영복", _SSG_CANDIDATES
    )
    assert got == "신세계몰메인매장 > 수영/수상레저 > 남성수영복/래쉬가드 > 래쉬가드"


def test_leaf_fallback_kids_guard() -> None:
    """폴백 유아동 가드: 소스에 유아동 키워드 없으면 아동 후보 채택 금지
    (기존 소싱처 "신발 > 스니커즈 > 캔버스/단화"가 아동화로 새는 부작용 방지)."""
    kids_only = ["신세계몰메인매장 > 슈즈/운동화 > 아동신발 > 스니커즈"]
    got = _similarity_match_smartstore("신발 > 스니커즈 > 캔버스/단화", kids_only)
    assert got is None
