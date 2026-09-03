"""포이즌 묶음 SKU 원가 배수 테스트 (2026-09-01 FT8529 실사고).

무신사 FT8529 는 3켤레 1세트(23,000원)인데, 포이즌 카탈로그의 같은 품번에는
"2 Set 6 Pack"(=3켤레 세트 x2) SKU 가 있다. 매칭이 사이즈(level2)만 보기 때문에
묶음 SKU 가 걸렸고, 3켤레 원가 20,540 으로 51,000원에 등록됐다.
→ 팔리면 정산 36,000 / 실매입 46,000 = -5,080원 확정 역마진.

묶음 SKU 는 "N Set" 의 N 만큼 원가를 배수 처리해야 한다.
"""

from __future__ import annotations

from backend.domain.samba.proxy.poison import bundle_multiplier


def test_2세트_묶음은_2배():
    # 실제 SPU 1069199 SKU 속성 (language=en / ko)
    assert bundle_multiplier("2 Set 6 Pack") == 2
    assert bundle_multiplier("2 세트 6 팩") == 2


def test_구성만_적힌_표기는_1배():
    # SPU 기본단위 자체가 3켤레 = 소싱처 상품 1개 (JV7417, HQ4335-910 실제 등록건)
    assert bundle_multiplier("3 Pack (Black)") == 1
    assert bundle_multiplier("3-pack set (Pink+Purple+Dark Red)") == 1
    assert bundle_multiplier("3팩 세트 (핑크+퍼플+다크 레드)") == 1


def test_일반_색상속성은_1배():
    assert bundle_multiplier("Cloud White/Halo Silver") == 1
    assert bundle_multiplier("브라운[CNY 뉴 이어 박스]") == 1
    assert bundle_multiplier("") == 1
    assert bundle_multiplier(None) == 1


def test_비정상_배수는_무시():
    # 색상코드 등 오탐 방지 — 2~20 범위만 인정
    assert bundle_multiplier("1 Set 3 Pack") == 1
    assert bundle_multiplier("99 Set") == 1


def test_실사고_원가환산():
    # 3켤레 원가 20,540 x 2세트 = 41,080 → 최소 56,080원 이상이라야 본전
    from backend.domain.samba.proxy.poison import _min_price_for_profit

    cost = 20540 * bundle_multiplier("2 Set 6 Pack")
    assert cost == 41080
    assert _min_price_for_profit(cost, 0) == 56080
    assert _min_price_for_profit(cost, 10000) == 66080
