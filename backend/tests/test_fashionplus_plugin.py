"""패션플러스 마켓 플러그인 검증."""

import pytest

from backend.domain.samba.plugins.markets.fashionplus import (
    FashionPlusPlugin,
    extract_option_ids,
    is_self_sourced,
)


def test_레지스트리_식별자():
    plugin = FashionPlusPlugin()
    assert plugin.market_type == "fashionplus"
    assert plugin.policy_key == "패션플러스"


def test_패플_소싱분은_자기순환으로_차단():
    assert is_self_sourced({"source": "FASHIONPLUS"}) is True
    assert is_self_sourced({"source": "fashionplus"}) is True


def test_다른_소싱처는_통과():
    assert is_self_sourced({"source": "MUSINSA"}) is False
    assert is_self_sourced({}) is False


def test_등록응답에서_OptID_맵_추출():
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [
            {"OptID": 111, "Color": "BLACK", "Size": "270"},
            {"OptID": 222, "Color": "BLACK", "Size": "280"},
        ],
    }
    assert extract_option_ids(resp) == {"BLACK|270": 111, "BLACK|280": 222}


def test_OptID_없는_응답은_빈맵():
    assert extract_option_ids({"Status": "OK", "ItemID": 777}) == {}


@pytest.mark.asyncio
async def test_자기순환_상품은_전송하지_않는다():
    plugin = FashionPlusPlugin()
    result = await plugin.execute(
        session=None,
        product={"source": "FASHIONPLUS", "name": "x", "sale_price": 10000},
        creds={"custCode": "012555"},
        category_id="1010",
        account=None,
        existing_no="",
    )
    assert result["success"] is False
    assert "자기순환" in result["message"]


@pytest.mark.asyncio
async def test_삭제는_재고0_노출해제_삭제_3단으로_진행한다():
    """GoodsDelete 는 임시보관이라 재고0·노출해제를 먼저 해야 실제로 안 팔린다."""
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            return {"Status": "OK", "Message": ""}

    plugin = FashionPlusPlugin()
    result = await plugin.delete_with_client(FakeClient(), "777", options=[])
    assert called == ["scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is True
