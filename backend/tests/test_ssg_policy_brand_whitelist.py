"""SSG 정책 브랜드 화이트리스트 가드 회귀 테스트 (2026-09-01 사장님 지시).

"신세계몰에 계약 등록된 브랜드만 올릴것" — 계정 정책(ssgBrandMappings)에 등록된
브랜드만 전송하고, 미계약 브랜드는 실패가 아닌 스킵(_skip_retry) 처리한다.
2026-09-01 복구 작업에서 비계약 브랜드 331건이 기타(9999999999)로 올라간 실사고 재발 방지.

검증 대상: backend.domain.samba.plugins.markets.ssg
  - _match_policy_brand (완전일치 + 접두일치, 포함매칭 금지)
  - SSGPlugin.execute 초입 가드 (DB/네트워크 접근 없이 순수 단위 검증)

execute 는 가드 통과 시 다음 검증(카테고리 미매핑 에러)으로 진행하므로,
category_id="" 를 센티널로 사용해 "가드 통과 = 카테고리 에러 반환"으로 판별한다.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.domain.samba.plugins.markets.ssg import SSGPlugin, _match_policy_brand

# 실측 — 계정 ma_01KSJ25PQFWV7VZXC1TFT13NVE 의 ssgBrandMappings 24개와 동일 구성
POLICY_BRANDS = [
    "리",
    "반스",
    "조던",
    "푸마",
    "휠라",
    "나이키",
    "살로몬",
    "아식스",
    "아이더",
    "이미스",
    "컨버스",
    "크록스",
    "뉴발란스",
    "다이나핏",
    "닥터마틴",
    "스파이더",
    "아디다스",
    "언더아머",
    "잔스포츠",
    "컬럼비아",
    "뉴발란스 키즈",
    "아디다스 키즈",
    "리 키즈",
    "LEE",
]
POLICY_MAPPINGS = [
    {"brandNm": nm, "brandId": f"20000000{i:02d}"} for i, nm in enumerate(POLICY_BRANDS)
]

CATEGORY_MISSING = "전시카테고리가 매핑되지 않았습니다"
SKIP_PREFIX = "스킵 (신세계몰 미계약 브랜드:"


def _execute(product: dict, creds: dict) -> dict:
    """가드 단위 검증용 execute 호출 — category_id="" 센티널로 네트워크 차단."""
    return asyncio.run(
        SSGPlugin().execute(
            session=None,
            product=product,
            creds=creds,
            category_id="",  # 가드 통과 시 카테고리 미매핑 에러로 즉시 반환
            account=None,
            existing_no="",
        )
    )


def _creds(mappings) -> dict:
    return {"apiKey": "test-key", "ssgBrandMappings": mappings}


# ── 1) 매칭 규칙: 완전일치 + 접두일치(양방향), 포함매칭 금지 ────────────────


@pytest.mark.parametrize(
    "brand",
    [
        "아디다스",  # 완전일치
        "아디다스 키즈",  # 공백 표기 차이 → 정규화 완전일치
        "LEE",  # 영문 표기 → 완전일치(소문자 정규화)
        "리",  # 1자 브랜드 완전일치
        "리 키즈",
        "나이키키즈",  # 접두일치 — 실측 1,591건
        "나이키 키즈",
        "나이키 스윔",  # 접두일치 — 실측 155건
        "나이키골프",
        "아디다스 오리지널",  # 접두일치 — 실측 1,087건
        "아디다스(퍼포먼스)",  # 괄호 표기 — 접두일치로 통과해야 함
        "휠라키즈",  # 접두일치 — 실측 322건
    ],
)
def test_contracted_brand_matches(brand):
    assert _match_policy_brand(brand, POLICY_MAPPINGS) != ""


@pytest.mark.parametrize(
    "brand",
    [
        "노스페이스",
        "코드그라피",
        "코닥",
        "미즈노",
        "에잇세컨즈",
        "파타고니아",
        "룰루레몬",
        "코오롱스포츠",  # "잔스포츠" 포함매칭이면 뚫림 — 접두라서 스킵
        "빈폴 키즈",
        "와키윌리",  # ★1자 브랜드 "리" 포함매칭 오탐 회귀 방지 (실측 오탐 사례)
        "블랙야크",
        "마크곤잘레스",
    ],
)
def test_uncontracted_brand_no_match(brand):
    assert _match_policy_brand(brand, POLICY_MAPPINGS) == ""


# ── 2) execute 가드: 정책 브랜드 → 전송 진행 ──────────────────────────────


@pytest.mark.parametrize(
    "brand", ["아디다스", "아디다스 키즈", "LEE", "리", "나이키키즈", "나이키 스윔"]
)
def test_execute_contracted_brand_proceeds(brand):
    result = _execute(
        {"name": "테스트 상품", "brand": brand, "sale_price": 10000},
        _creds(POLICY_MAPPINGS),
    )
    assert result["success"] is False
    assert CATEGORY_MISSING in result["message"]  # 가드 통과 후 다음 검증 도달
    assert SKIP_PREFIX not in result["message"]


# ── 3) execute 가드: 미계약 브랜드 → 스킵(_skip_retry) + 사유 문구 ─────────


@pytest.mark.parametrize("brand", ["노스페이스", "와키윌리", "코닥"])
def test_execute_uncontracted_brand_skipped(brand):
    result = _execute(
        {"name": "테스트 상품", "brand": brand, "sale_price": 10000},
        _creds(POLICY_MAPPINGS),
    )
    assert result["success"] is False
    # 기존 스킵 관례(_skip_retry) — 전송 워커가 failed 아닌 skipped 로 분류
    assert result.get("_skip_retry") is True
    assert result["message"] == f"스킵 (신세계몰 미계약 브랜드: {brand})"


# ── 4) ssgBrandMappings 빈 배열/None → 가드 비활성(전송 진행) ──────────────


@pytest.mark.parametrize("mappings", [[], None])
def test_execute_empty_mappings_disables_guard(mappings):
    result = _execute(
        {"name": "테스트 상품", "brand": "노스페이스", "sale_price": 10000},
        _creds(mappings),
    )
    assert result["success"] is False
    assert CATEGORY_MISSING in result["message"]  # 가드 미적용 → 다음 검증 도달
    assert SKIP_PREFIX not in result["message"]


def test_execute_corrupted_string_mappings_disables_guard():
    # 프론트 직렬화 잔해('[object Object]') → 복원 불가 → 가드 비활성 (전 상품 차단 방지)
    result = _execute(
        {"name": "테스트 상품", "brand": "노스페이스", "sale_price": 10000},
        _creds("[object Object]"),
    )
    assert CATEGORY_MISSING in result["message"]


# ── 5) brand 비어있고 manufacturer 로만 매칭되는 경우 ─────────────────────


def test_execute_manufacturer_fallback_match():
    result = _execute(
        {
            "name": "테스트 상품",
            "brand": "",
            "manufacturer": "나이키",
            "sale_price": 10000,
        },
        _creds(POLICY_MAPPINGS),
    )
    assert CATEGORY_MISSING in result["message"]  # manufacturer 매칭으로 가드 통과
    assert SKIP_PREFIX not in result["message"]


def test_execute_manufacturer_fallback_no_match_skipped():
    result = _execute(
        {
            "name": "테스트 상품",
            "brand": "",
            "manufacturer": "노스페이스",
            "sale_price": 10000,
        },
        _creds(POLICY_MAPPINGS),
    )
    assert result.get("_skip_retry") is True
    assert result["message"] == "스킵 (신세계몰 미계약 브랜드: 노스페이스)"
