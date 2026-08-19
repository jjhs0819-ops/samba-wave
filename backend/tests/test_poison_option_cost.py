"""포이즌 옵션가 불균일 역마진 방지 테스트 (2026-08-19).

실사고: 무신사 IY7278 은 XS/L/XL 이 53,990원인데 S/M 만 109,000원이다.
상품 대표원가(cost)는 최저옵션가 53,990 으로 잡히는데, 플러그인이 모든 사이즈에
이 값을 원가로 써서 M 을 89,000원에 등록했다. 실매입 109,000 → 건당 -35,000원.

옵션가가 불균일하면 사이즈별 실매입가로 환산해야 한다.
환산식: 실원가 = 대표원가 x (해당옵션가 / 최저옵션가)
  - 옵션가가 전부 같으면 그대로 대표원가 (할인 매입가 상품 오탐 방지)
"""

from __future__ import annotations


def option_cost(fallback_cost: int, opt_price: int, min_opt_price: int) -> int:
    """플러그인 execute() 의 옵션별 원가 산출과 동일한 식."""
    if opt_price and min_opt_price and opt_price > min_opt_price:
        return int(round(fallback_cost * opt_price / min_opt_price))
    return fallback_cost


def test_옵션가가_전부_같으면_대표원가_그대로():
    # 미즈노 J1GC265132: 옵션가 전부 206,990 / 대표원가 177,420(할인 매입가)
    # 이걸 206,990 으로 올려잡으면 멀쩡한 상품이 역마진으로 오판된다
    assert option_cost(177420, 206990, 206990) == 177420


def test_비싼_옵션은_같은_할인율로_환산한다():
    # IY7278: 대표원가 53,990 = 최저옵션가 → 할인율 1.0 → M 옵션 실원가 = 109,000
    assert option_cost(53990, 109000, 53990) == 109000


def test_최저가_옵션은_대표원가_그대로():
    assert option_cost(53990, 53990, 53990) == 53990


def test_할인상품의_비싼옵션은_할인율을_유지한다():
    # 대표원가 90,000 / 최저옵션가 100,000(=10% 할인) / 비싼옵션 200,000
    # → 실매입도 10% 할인 가정 → 180,000
    assert option_cost(90000, 200000, 100000) == 180000


def test_실사고_IY7278_M은_게이트에서_걸러진다():
    from backend.domain.samba.proxy.poison import decide_bid_price, poizon_fee

    cost = option_cost(53990, 109000, 53990)  # 109,000
    # 사고 당시 시세 89,000 에 등록됐다
    r = decide_bid_price(cost=cost, target=131000, market=89000,
                         min_profit=7000, unit=1000)
    assert r.skipped is True, "실원가 109,000 이면 89,000 등록은 반드시 막혀야 한다"

    # 수정 전(대표원가 53,990)이었다면 통과했다는 것도 함께 고정
    before = decide_bid_price(cost=53990, target=89000, market=89000,
                              min_profit=7000, unit=1000)
    assert before.skipped is False
    assert before.price == 89000
    # 그 가격의 실제 순이익 = 확정손실
    assert 89000 - poizon_fee(89000) - 109000 == -35000
