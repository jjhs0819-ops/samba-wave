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


# ---------------------------------------------------------------------------
# 2026-08-22 재발: 위 환산은 PoisonPlugin.execute() 안에만 있는데, 오토튠이
# 상품 대표원가 기준으로 "가격 변동 없음"이라 판단해 execute() 를 아예 호출하지
# 않아 환산·취소가 한 번도 돌지 않았다.
#   [오토튠][가격스킵] JI0080 포이즌: expected=83600==last=83600, cost_now=73990
# 실사고: JI0080 은 220/285/290 만 149,000(브랜드배송)이고 나머지는 73,990 인데
# 220 이 109,000 에 걸린 채로 남아 주문이 들어왔다(정산 94,000 - 실매입 149,000).
# → 라이브 입찰가와 옵션 실매입가를 직접 비교해 손실 입찰을 찾아내야 한다.
# ---------------------------------------------------------------------------


def test_손실입찰_판별_JI0080_220_290():
    from backend.domain.samba.proxy.poison import find_losing_bids

    options = [
        {"name": "220", "price": 149000, "stock": 99},
        {"name": "230", "price": 73990, "stock": 99},
        {"name": "285", "price": 149000, "stock": 99},
        {"name": "290", "price": 149000, "stock": 99},
    ]
    sizes = {
        "220": {"price": 109000, "biddingNo": "1"},
        "230": {"price": 95000, "biddingNo": "2"},
        "285": {"price": 174000, "biddingNo": "3"},
        "290": {"price": 109000, "biddingNo": "4"},
    }
    losing = find_losing_bids(cost=73990, options=options, sizes=sizes)
    # 220/290: 109,000 - 수수료 15,000 - 실매입 149,000 = -55,000
    # 285: 174,000 - 17,400 - 149,000 = +7,600 → 손실 아님
    # 230: 95,000 - 15,000 - 73,990 = +6,010 → 손실 아님
    assert sorted(losing) == ["220", "290"]


def test_옵션가_균일하면_손실입찰_없음():
    from backend.domain.samba.proxy.poison import find_losing_bids

    # 미즈노형: cost 가 할인 매입가라 옵션가보다 낮다. 환산하면 오판이 난다.
    options = [{"name": "260", "price": 206990, "stock": 9}]
    sizes = {"260": {"price": 230000, "biddingNo": "1"}}
    assert find_losing_bids(cost=177420, options=options, sizes=sizes) == []


def test_취소된_입찰은_대상_아님():
    from backend.domain.samba.proxy.poison import find_losing_bids

    options = [
        {"name": "220", "price": 149000, "stock": 99},
        {"name": "230", "price": 73990, "stock": 99},
    ]
    # biddingNo 없음(=이미 취소) → 손실이어도 다시 전송할 이유가 없다
    sizes = {"220": {"price": 109000, "status": "cancelled"}}
    assert find_losing_bids(cost=73990, options=options, sizes=sizes) == []


def test_입찰가_없으면_판정하지_않는다():
    from backend.domain.samba.proxy.poison import find_losing_bids

    options = [
        {"name": "220", "price": 149000, "stock": 99},
        {"name": "230", "price": 73990, "stock": 99},
    ]
    sizes = {"220": {"biddingNo": "1"}}
    assert find_losing_bids(cost=73990, options=options, sizes=sizes) == []


def test_이미_취소된_입찰은_취소성공으로_본다():
    """포이즌이 'Listing has been canceled.' 를 code!=200 으로 돌려준다.

    실패로 처리하면 호출부가 DB 의 biddingNo 를 지우지 않아 라이브에 없는 번호가
    영구히 남고, 손실 입찰 감지가 매 사이클 헛취소를 반복한다(2026-08-22 IY7278).
    """
    import asyncio
    from unittest.mock import AsyncMock, patch

    from backend.domain.samba.proxy.poison import PoisonClient

    c = PoisonClient(app_key="K", app_secret="S")
    with patch.object(
        PoisonClient,
        "_post",
        new=AsyncMock(return_value={"code": 500080004, "msg": "Listing has been canceled."}),
    ):
        r = asyncio.run(c.cancel_listing("151220034897237952"))
    assert r["success"] is True
    assert r.get("already_cancelled") is True


def test_진짜_취소실패는_실패로_남는다():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from backend.domain.samba.proxy.poison import PoisonClient

    c = PoisonClient(app_key="K", app_secret="S")
    with patch.object(
        PoisonClient,
        "_post",
        new=AsyncMock(return_value={"code": 500080002, "msg": "Invalid request parameter(s)"}),
    ):
        r = asyncio.run(c.cancel_listing("1"))
    assert r["success"] is False
