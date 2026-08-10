"""POIZON 시세 게이트 테스트 (2026-08-10).

포이즌은 입찰 경쟁 시장이라, 시장 최저가보다 비싸게 걸면 노출조차 되지 않는다.
실측(표본 200 SKU)에서 정책가 그대로 등록하면 96%가 노출 불가였다.

정책(사장님 확정):
- 마진율이 아니라 **건당 순이익 절대금액**으로 판단한다(기본 10,000원).
- 마진이 낮다고 건너뛰지 않는다. 노출이 우선이므로 시장가까지 내려서라도 등록한다.
- 단 시장가로 팔아도 순이익이 하한에 못 미치면 그때는 등록하지 않는다.

순이익 = 판매가 - 포이즌수수료 - 원가,  수수료 = clamp(판매가×10%, 15,000, 45,000)
"""

from __future__ import annotations

from backend.domain.samba.proxy.poison import decide_bid_price, poizon_fee

MIN_PROFIT = 10000


def profit(price: int, cost: int) -> float:
    return price - poizon_fee(price) - cost


def test_수수료는_최저_15000원이_걸린다():
    assert poizon_fee(70000) == 15000  # 10% = 7,000 → 최저 적용
    assert poizon_fee(200000) == 20000  # 10%
    assert poizon_fee(600000) == 45000  # 최대 적용


def test_목표가가_시장가보다_싸면_목표가_그대로():
    # 원가 50,000 / 목표가 80,000 / 시장가 100,000 → 목표가 유지(마진 최대화)
    r = decide_bid_price(cost=50000, target=80000, market=100000, min_profit=MIN_PROFIT)
    assert r.price == 80000
    assert r.skipped is False


def test_목표가가_시장가보다_비싸면_시장가로_내린다():
    # 노출이 우선 — 마진이 줄어도 시장가까지 내려서 등록한다
    # 원가 50,000 / 시장가 90,000 → 90,000-15,000-50,000 = 25,000 (하한 통과)
    r = decide_bid_price(cost=50000, target=120000, market=90000, min_profit=MIN_PROFIT)
    assert r.price == 90000
    assert r.skipped is False
    assert profit(r.price, 50000) >= MIN_PROFIT


def test_시장가로_내려도_최소이익_미달이면_스킵():
    # 원가 50,000 / 시장가 72,000 → 72,000-15,000-50,000 = 7,000 < 10,000
    r = decide_bid_price(cost=50000, target=85000, market=72000, min_profit=MIN_PROFIT)
    assert r.skipped is True
    assert "최소이익" in r.reason


def test_최소이익_경계값():
    # 원가 50,000, 최소이익 10,000 → 필요 판매가 = 50,000+15,000+10,000 = 75,000
    ok = decide_bid_price(cost=50000, target=90000, market=75000, min_profit=MIN_PROFIT)
    assert ok.skipped is False
    assert ok.price == 75000
    assert profit(75000, 50000) == 10000

    ng = decide_bid_price(cost=50000, target=90000, market=74999, min_profit=MIN_PROFIT)
    assert ng.skipped is True


def test_목표가가_최소이익보다_낮으면_올려서_등록():
    # 정책가가 너무 낮게 잡힌 경우 — 마진 하한선까지 올린다
    r = decide_bid_price(cost=50000, target=60000, market=120000, min_profit=MIN_PROFIT)
    assert r.skipped is False
    assert r.price == 75000  # cost + 15,000 + 10,000


def test_시세가_없으면_경쟁자가_없다고_보고_목표가로_등록():
    r = decide_bid_price(cost=50000, target=90000, market=None, min_profit=MIN_PROFIT)
    assert r.skipped is False
    assert r.price == 90000


def test_시세가_없어도_최소이익은_지킨다():
    r = decide_bid_price(cost=50000, target=60000, market=None, min_profit=MIN_PROFIT)
    assert r.price == 75000


def test_고가구간은_정률_10퍼센트로_하한을_계산():
    # 원가 300,000 → 저가식(300,000+25,000=325,000)은 10%가 32,500>15,000이라 부적합.
    # 고가식: (300,000+10,000)/0.9 = 344,445
    r = decide_bid_price(cost=300000, target=200000, market=None, min_profit=MIN_PROFIT)
    assert r.price == 344445
    assert profit(r.price, 300000) >= MIN_PROFIT


def test_원가가_0이면_스킵():
    r = decide_bid_price(cost=0, target=50000, market=70000, min_profit=MIN_PROFIT)
    assert r.skipped is True


def test_1000원_단위_보정해도_시장가를_넘지_않는다():
    # 시장가 72,900 → 내림 72,000. 올림(73,000)이면 노출 실패한다.
    r = decide_bid_price(
        cost=40000, target=120000, market=72900, min_profit=MIN_PROFIT, unit=1000
    )
    assert r.price == 72000
    assert r.price <= 72900


def test_1000원_단위_보정해도_최소이익은_지킨다():
    # 하한 = 40,000+15,000+10,000 = 65,000 → 단위 올림해도 65,000
    r = decide_bid_price(
        cost=40000, target=50000, market=None, min_profit=MIN_PROFIT, unit=1000
    )
    assert r.price == 65000
    assert profit(r.price, 40000) >= MIN_PROFIT


def test_단위보정으로_하한이_상한을_넘으면_스킵():
    # 하한 65,000 / 시장가 64,900 → 내림 64,000 < 65,000 → 등록 불가
    r = decide_bid_price(
        cost=40000, target=90000, market=64900, min_profit=MIN_PROFIT, unit=1000
    )
    assert r.skipped is True
