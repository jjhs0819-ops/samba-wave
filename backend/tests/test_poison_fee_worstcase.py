"""등록가 하한은 최악 수수료로 잡는다 (2026-09-04 실사고).

포이즌 수수료는 품목마다 요율/최저액이 다르다. 주문 응답 poundage_detail 실측:
  양말 FT8529 → current_percent 1000(10%), 수수료 15,000
  모자 JV7391 → current_percent 1400(14%), 수수료 18,000
등록 전에는 이 요율을 알 수 없다 — 카탈로그·추천가 응답에 수수료 정보가 없다.

표준값(10%/15,000)으로 하한을 잡으면 14% 품목에서 3,000원이 통째로 손실이 된다.
실사고: 모자 48,000 판매, 원가 29,687 → 계산상 +3,313 이었으나 실제 정산 +313.
"""

from __future__ import annotations

from backend.domain.samba.proxy.poison import (
    POISON_FEE_MIN,
    POISON_FEE_MIN_WORST,
    POISON_FEE_RATE,
    POISON_FEE_RATE_WORST,
    _min_price_for_profit,
    decide_bid_price,
    poizon_fee,
)


def test_표준값과_최악값이_따로_있다():
    # 표준(신발·의류) 은 마진 표시·기존 계산용으로 그대로 두고,
    # 하한 계산만 최악값을 쓴다
    assert (POISON_FEE_RATE, POISON_FEE_MIN) == (0.10, 15000)
    assert (POISON_FEE_RATE_WORST, POISON_FEE_MIN_WORST) == (0.14, 18000)


def test_모자_실제수수료는_최악값으로_계산해야_맞는다():
    # 48,000 x 14% = 6,720 < 최저 18,000 → 실청구 18,000 (실측치와 일치)
    assert poizon_fee(48000, POISON_FEE_RATE_WORST, POISON_FEE_MIN_WORST) == 18000
    # 표준값으로 보면 15,000 이라 3,000원을 놓친다
    assert poizon_fee(48000) == 15000


def test_실사고_하한_비교():
    cost = 29687
    # 표준값 하한 45,687 → 48,000 등록이 통과했다(그래서 팔리고 +313원)
    assert _min_price_for_profit(cost, 1000) == 45687
    # 최악값 하한 48,687 → 48,000 은 애초에 막힌다
    assert (
        _min_price_for_profit(
            cost, 1000, rate=POISON_FEE_RATE_WORST, fee_min=POISON_FEE_MIN_WORST
        )
        == 48687
    )


def test_실사고_시세게이트가_등록을_막는다():
    # 시장가 48,000 · 원가 29,687 · 최소이익 8,000 → 등록 불가여야 한다
    d = decide_bid_price(
        cost=29687,
        target=60000,
        market=48000,
        min_profit=8000,
        rate=POISON_FEE_RATE_WORST,
        fee_min=POISON_FEE_MIN_WORST,
        unit=1000,
    )
    assert d.skipped is True


def test_고가구간은_요율차이가_그대로_반영된다():
    # 200,000 x 14% = 28,000 (최저·최대 구간 밖)
    assert round(poizon_fee(200000, POISON_FEE_RATE_WORST, POISON_FEE_MIN_WORST)) == 28000
