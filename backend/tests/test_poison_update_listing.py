"""POIZON 입찰 수정(update-bid) 페이로드 테스트 (2026-08-19).

공통 필드(language/timeZone/countryCode/deliveryCountryCode/currency/refererSource)는
등록과 마찬가지로 필수다. 빼면 비즈니스 로직에 닿기도 전에 500080002
(Invalid request parameter(s))로 거부된다 — 라이브 실측으로 확인. 그동안 오토튠의
가격·재고 수정이 단 한 건도 마켓에 반영되지 못한 원인이었다.
"""

from __future__ import annotations

import pytest

from backend.domain.samba.proxy.poison import PoisonClient


def _client() -> PoisonClient:
    return PoisonClient(app_key="k" * 32, app_secret="s" * 32)


@pytest.mark.asyncio
async def test_수정_페이로드에_공통필드가_모두_실린다(monkeypatch):
    captured: dict = {}

    async def fake_post(path, business):
        captured["path"] = path
        captured["business"] = business
        return {"code": 200}

    c = _client()
    monkeypatch.setattr(c, "_post", fake_post)
    r = await c.update_listing(
        seller_bidding_no="151220034884985238",
        price=118000,
        quantity=4,
        global_sku_id=1001947759539472,
    )

    assert r["success"] is True
    biz = captured["business"]
    for key in (
        "language",
        "timeZone",
        "countryCode",
        "deliveryCountryCode",
        "currency",
        "refererSource",
        "requestId",
        "sellerBiddingNo",
        "price",
        "quantity",
        "globalSkuId",
    ):
        assert key in biz, f"필수 필드 누락: {key}"
    assert biz["countryCode"] == biz["deliveryCountryCode"] == "KR"
    assert biz["price"] == 118000 and biz["quantity"] == 4


@pytest.mark.asyncio
async def test_현재값과_동일하면_실패가_아니라_no_change(monkeypatch):
    """20900016 을 실패로 보면 오토튠이 매 사이클 같은 건을 무한 재시도한다."""

    async def fake_post(path, business):
        return {"code": 20900016, "msg": "Submitted information is the same"}

    c = _client()
    monkeypatch.setattr(c, "_post", fake_post)
    r = await c.update_listing(seller_bidding_no="1512", price=1000, quantity=1)

    assert r["success"] is True
    assert r["no_change"] is True


@pytest.mark.asyncio
async def test_그밖의_에러는_실패로_남는다(monkeypatch):
    async def fake_post(path, business):
        return {"code": 21003011, "msg": "User is placing an order"}

    c = _client()
    monkeypatch.setattr(c, "_post", fake_post)
    r = await c.update_listing(seller_bidding_no="1512", price=1000, quantity=1)

    assert r["success"] is False
    assert "order" in r["message"]


@pytest.mark.asyncio
async def test_수정_성공시_새_입찰번호를_돌려준다(monkeypatch):
    """수정은 기존 입찰을 내리고 새 번호로 재발급한다 — 안 받으면 다음 사이클이 깨진다."""

    async def fake_post(path, business):
        return {"code": 200, "data": {"sellerBiddingNo": "151220034899120694"}}

    c = _client()
    monkeypatch.setattr(c, "_post", fake_post)
    r = await c.update_listing(seller_bidding_no="151220034897187964",
                               price=155000, quantity=1)

    assert r["success"] is True
    assert r["sellerBiddingNo"] == "151220034899120694"


@pytest.mark.asyncio
async def test_no_change면_새_번호가_없다(monkeypatch):
    async def fake_post(path, business):
        return {"code": 20900016, "msg": "same"}

    c = _client()
    monkeypatch.setattr(c, "_post", fake_post)
    r = await c.update_listing(seller_bidding_no="1512", price=1000, quantity=1)

    assert r["success"] is True
    assert not r.get("sellerBiddingNo")
