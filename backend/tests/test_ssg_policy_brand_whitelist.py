"""SSG 정책 브랜드 화이트리스트 가드 회귀 테스트 (2026-09-01 사장님 지시).

"신세계몰에 계약 등록된 브랜드만 올릴것" — 판정 목록은 **정책 ∪ 계정 합집합**:
  - 정책: samba_policy.market_policies['신세계몰(전시)'].ssgBrandMappings
    (정책관리 화면의 목록 — market_base 가 product['_policy_brand_mappings'] 주입)
  - 계정: samba_market_account.additional_fields.ssgBrandMappings
두 목록은 서로 다르다(실측): 정책에만 코닥·코드그라피·미즈노·라코스테,
계정에만 리·리 키즈·조던·뉴발란스 키즈·아디다스 키즈. 한쪽만 보면 정상
브랜드가 스킵되는 회귀가 난다(2026-09-01 코닥/코드그라피 스킵 실사고).
미계약 브랜드는 실패가 아닌 스킵(_skip_retry) 처리한다.

검증 대상: backend.domain.samba.plugins.markets.ssg
  - _match_policy_brand (완전일치 + 접두일치, 포함매칭 금지)
  - _merge_brand_mappings (정책∪계정 합집합, 같은 brandNm 은 정책 우선)
  - SSGPlugin.execute 초입 가드 (DB/네트워크 접근 없이 순수 단위 검증)

execute 는 가드 통과 시 다음 검증(카테고리 미매핑 에러)으로 진행하므로,
category_id="" 를 센티널로 사용해 "가드 통과 = 카테고리 에러 반환"으로 판별한다.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.domain.samba.plugins.markets.ssg import (
    SSGPlugin,
    _match_policy_brand,
    _merge_brand_mappings,
)

# 실측 A — 정책 pol_01KQPZP5CYZQQ2YYKPR5Z068QS(어브로드-1)
# market_policies['신세계몰(전시)'].ssgBrandMappings 23개와 동일 구성
POLICY_BRANDS = [
    "반스",
    "코닥",
    "푸마",
    "휠라",
    "나이키",
    "미즈노",
    "살로몬",
    "아식스",
    "아이더",
    "이미스",
    "컨버스",
    "크록스",
    "뉴발란스",
    "다이나핏",
    "닥터마틴",
    "라코스테",
    "스파이더",
    "아디다스",
    "언더아머",
    "잔스포츠",
    "컬럼비아",
    "코드그라피",
    "LEE",
]
# 실측 B — 계정 ma_01KSJ25PQFWV7VZXC1TFT13NVE
# additional_fields.ssgBrandMappings 24개와 동일 구성
ACCOUNT_BRANDS = [
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
# brandId 접두를 P/A 로 달리 해 우선순위(정책 우선) 판별에 사용
POLICY_MAPPINGS = [
    {"brandNm": nm, "brandId": f"P{i:09d}"} for i, nm in enumerate(POLICY_BRANDS)
]
ACCOUNT_MAPPINGS = [
    {"brandNm": nm, "brandId": f"A{i:09d}"} for i, nm in enumerate(ACCOUNT_BRANDS)
]
UNION_MAPPINGS = _merge_brand_mappings(POLICY_MAPPINGS, ACCOUNT_MAPPINGS)

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


def _creds(account_mappings) -> dict:
    return {"apiKey": "test-key", "ssgBrandMappings": account_mappings}


def _product(brand: str, policy_mappings=None, **extra) -> dict:
    p = {"name": "테스트 상품", "brand": brand, "sale_price": 10000, **extra}
    if policy_mappings is not None:
        # market_base._apply_market_settings 가 정책에서 주입하는 키
        p["_policy_brand_mappings"] = policy_mappings
    return p


# ── 1) 합집합 구성: 정규화 중복제거 + 정책 우선 ────────────────────────────


def test_merge_union_size_and_membership():
    # A-only 4(코닥·미즈노·라코스테·코드그라피) + B-only 5(리·조던·키즈류) + 공통 19
    assert len(UNION_MAPPINGS) == 28
    names = {m["brandNm"] for m in UNION_MAPPINGS}
    for nm in ["코닥", "코드그라피", "미즈노", "라코스테"]:  # 정책에만
        assert nm in names
    for nm in ["리", "리 키즈", "조던", "뉴발란스 키즈", "아디다스 키즈"]:  # 계정에만
        assert nm in names


def test_merge_policy_id_wins_on_duplicate():
    # 같은 brandNm(나이키·LEE 등)이 양쪽에 있고 ID 가 다르면 → 정책 ID 사용
    by_name = {m["brandNm"]: m["brandId"] for m in UNION_MAPPINGS}
    assert by_name["나이키"].startswith("P")
    assert by_name["LEE"].startswith("P")
    assert by_name["리"].startswith("A")  # 계정에만 있는 항목은 계정 ID 유지


def test_merge_coerces_corrupted_sides():
    # 한쪽이 직렬화 잔해/None 이어도 다른 쪽만으로 합집합 구성
    assert len(_merge_brand_mappings("[object Object]", ACCOUNT_MAPPINGS)) == 24
    assert len(_merge_brand_mappings(POLICY_MAPPINGS, None)) == 23
    assert _merge_brand_mappings(None, None) == []


# ── 2) 매칭 규칙: 완전일치 + 접두일치(양방향), 포함매칭 금지 ────────────────


@pytest.mark.parametrize(
    "brand",
    [
        "아디다스",  # 완전일치
        "아디다스 키즈",  # 공백 표기 차이 → 정규화 완전일치
        "LEE",  # 영문 표기 → 완전일치(소문자 정규화)
        "리",  # 1자 브랜드 완전일치 (계정에만 존재 — 정책 LEE 와 별개)
        "리 키즈",
        "코닥",  # 정책에만 존재 — 실측 1,825건 스킵 회귀 방지
        "코드그라피",  # 정책에만 존재 — 실측 1,373건
        "미즈노",  # 정책에만 존재 — 실측 412건
        "라코스테",  # 정책에만 존재
        "조던",  # 계정에만 존재 — 실측 48건
        "뉴발란스 키즈",  # 계정에만 존재
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
    assert _match_policy_brand(brand, UNION_MAPPINGS) != ""


@pytest.mark.parametrize(
    "brand",
    [
        "에잇세컨즈",  # 실측 스킵 대상 247건
        "노스페이스",  # 87건
        "파타고니아",  # 36건
        "룰루레몬",  # 29건
        "빈폴 키즈",  # 19건
        "코오롱스포츠",  # 15건 — "잔스포츠" 포함매칭이면 뚫림, 접두라서 스킵
        "킨",  # 11건
        "지프",  # 10건
        "블랙야크",  # 4건
        "마크곤잘레스",  # 3건
        "와키윌리",  # 2건 ★1자 브랜드 "리" 포함매칭 오탐 회귀 방지 (실측 오탐 사례)
    ],
)
def test_uncontracted_brand_no_match(brand):
    assert _match_policy_brand(brand, UNION_MAPPINGS) == ""


# ── 3) execute 가드: 합집합 브랜드 → 전송 진행 ─────────────────────────────


@pytest.mark.parametrize(
    "brand",
    [
        "아디다스",
        "아디다스 키즈",
        "LEE",
        "리",  # 계정에만
        "조던",  # 계정에만
        "코닥",  # 정책에만
        "코드그라피",  # 정책에만
        "나이키키즈",
        "나이키 스윔",
    ],
)
def test_execute_contracted_brand_proceeds(brand):
    result = _execute(
        _product(brand, policy_mappings=POLICY_MAPPINGS),
        _creds(ACCOUNT_MAPPINGS),
    )
    assert result["success"] is False
    assert CATEGORY_MISSING in result["message"]  # 가드 통과 후 다음 검증 도달
    assert SKIP_PREFIX not in result["message"]


# ── 4) execute 가드: 미계약 브랜드 → 스킵(_skip_retry) + 사유 문구 ─────────


@pytest.mark.parametrize("brand", ["노스페이스", "와키윌리", "에잇세컨즈"])
def test_execute_uncontracted_brand_skipped(brand):
    result = _execute(
        _product(brand, policy_mappings=POLICY_MAPPINGS),
        _creds(ACCOUNT_MAPPINGS),
    )
    assert result["success"] is False
    # 기존 스킵 관례(_skip_retry) — 전송 워커가 failed 아닌 skipped 로 분류
    assert result.get("_skip_retry") is True
    assert result["message"] == f"스킵 (신세계몰 미계약 브랜드: {brand})"


# ── 5) 소스 조합 4종: 정책만 / 계정만 / 둘 다 / 둘 다 없음 ─────────────────


def test_execute_policy_only_source():
    # 계정 목록이 비어도 정책 목록만으로 가드 동작 (정책 브랜드 통과)
    result = _execute(_product("코닥", policy_mappings=POLICY_MAPPINGS), _creds([]))
    assert CATEGORY_MISSING in result["message"]
    # 합집합 밖 브랜드는 스킵
    result = _execute(
        _product("노스페이스", policy_mappings=POLICY_MAPPINGS), _creds([])
    )
    assert result.get("_skip_retry") is True


def test_execute_account_only_source():
    # 정책 목록이 없어도 계정 목록만으로 가드 동작 (기존 동작 유지)
    result = _execute(_product("리"), _creds(ACCOUNT_MAPPINGS))
    assert CATEGORY_MISSING in result["message"]
    result = _execute(_product("노스페이스"), _creds(ACCOUNT_MAPPINGS))
    assert result.get("_skip_retry") is True


@pytest.mark.parametrize("account_mappings", [[], None])
def test_execute_both_empty_disables_guard(account_mappings):
    # 정책·계정 모두 비어있으면 가드 비활성 → 미계약 브랜드도 다음 검증으로 진행
    result = _execute(_product("노스페이스"), _creds(account_mappings))
    assert result["success"] is False
    assert CATEGORY_MISSING in result["message"]
    assert SKIP_PREFIX not in result["message"]


def test_execute_corrupted_string_mappings_disables_guard():
    # 프론트 직렬화 잔해('[object Object]') → 복원 불가 → 가드 비활성 (전 상품 차단 방지)
    result = _execute(_product("노스페이스"), _creds("[object Object]"))
    assert CATEGORY_MISSING in result["message"]


# ── 6) brand 비어있고 manufacturer 로만 매칭되는 경우 ─────────────────────


def test_execute_manufacturer_fallback_match():
    result = _execute(
        _product("", policy_mappings=POLICY_MAPPINGS, manufacturer="나이키"),
        _creds(ACCOUNT_MAPPINGS),
    )
    assert CATEGORY_MISSING in result["message"]  # manufacturer 매칭으로 가드 통과
    assert SKIP_PREFIX not in result["message"]


def test_execute_manufacturer_fallback_no_match_skipped():
    result = _execute(
        _product("", policy_mappings=POLICY_MAPPINGS, manufacturer="노스페이스"),
        _creds(ACCOUNT_MAPPINGS),
    )
    assert result.get("_skip_retry") is True
    assert result["message"] == "스킵 (신세계몰 미계약 브랜드: 노스페이스)"
