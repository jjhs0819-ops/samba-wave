"""마켓별 수수료(feeRate) 반영 누락 방지.

calc_market_price 는 MARKET_TYPE_TO_POLICY_KEY 로 market_type → 정책키를 찾는다.
이 맵에 없는 마켓은 policy_key="" 가 되어 market_policies 의 feeRate·마켓 배송비가
통째로 무시되고, 원가+공통마진만 반영된 저가로 등록된다.

같은 사고가 두 번 났다:
  2026-07-21  eBay  — 맵 누락 → 냐옹ex $28.32 저가등록
  2026-08-15  토스  — 맵 누락 → 원가 235,000 상품이 270,900(1.15배)으로 계산됨.
                      12% 반영 시 307,800(1.31배). 건당 36,900원 손실.
                      첫 업로드 직전에 발견해 실제 등록은 0건.

세 번째를 막기 위해, 플러그인이 새로 붙었는데 맵에 등록되지 않으면 테스트가 깨진다.
"""

from backend.domain.samba.plugins import (
    MARKET_TYPE_TO_POLICY_KEY as PLUGIN_POLICY_KEYS,
)
from backend.domain.samba.shipment.service import (
    MARKET_TYPE_TO_POLICY_KEY,
    calc_market_price,
)

# 플러그인이 정책 feeRate 를 직접 읽어 가격을 만드는 마켓 — 맵에 넣으면 이중 그로스업.
#   poison: plugins/markets/poison.py 가 market_policies["포이즌"].feeRate 를 읽는다.
# (ebay 도 feeRate 를 읽지만 배송비 USD 그로스업 전용이라 맵에 있는 게 맞다.)
SELF_HANDLED_FEE = {"poison"}

# 아직 판매를 시작하지 않아 정책에 수수료 설정 자체가 없는 마켓.
# 실제로 팔기 시작하면 정책에 feeRate 를 넣고 이 목록에서 빼서 맵에 등록해야 한다.
NOT_YET_SELLING = {
    "amazon",
    "buyma",
    "cafe24",
    # 패션플러스: 수수료율 확정(패플 MD 회신) 후 이 목록에서 빼고 수수료 맵에 등록할 것.
    "fashionplus",
    "ktalpha",
    "lazada",
    "qoo10",
    "rakuten",
    "shopee",
    "shopify",
    "zoom",
}


def test_새_마켓_플러그인은_수수료_맵_등록을_강제한다():
    unmapped = set(PLUGIN_POLICY_KEYS) - set(MARKET_TYPE_TO_POLICY_KEY)
    unexpected = unmapped - SELF_HANDLED_FEE - NOT_YET_SELLING
    assert not unexpected, (
        f"수수료 맵에 없는 마켓: {sorted(unexpected)} — "
        f"이대로 전송하면 정책 feeRate 가 무시되어 저가로 등록된다. "
        f"MARKET_TYPE_TO_POLICY_KEY 에 추가하거나, 플러그인이 feeRate 를 "
        f"직접 읽는다면 SELF_HANDLED_FEE 에 넣어라."
    )


def test_토스는_수수료_맵에_있다():
    assert MARKET_TYPE_TO_POLICY_KEY.get("toss") == "토스"


def test_토스_판매가에_수수료가_반영된다():
    """2026-08-15 실측값 재현 — 맵에서 토스가 빠지면 이 테스트가 깨진다."""
    pricing = {"marginRate": 15}
    market_policies = {"토스": {"feeRate": 12}}
    cost = 235_000
    price = calc_market_price(cost, pricing, "toss", market_policies)
    without_fee = calc_market_price(cost, pricing, "toss", {})
    assert price > without_fee
    # 원가+15% 마진에서 12% 수수료를 역산하면 1.3배 언저리가 나온다
    assert 1.28 <= price / cost <= 1.34, price


def test_포이즌은_맵에_없어야_한다():
    """플러그인이 자체로 수수료를 붙이므로 맵에 넣으면 이중 반영된다."""
    assert "poison" not in MARKET_TYPE_TO_POLICY_KEY
