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


# ── 수정 라운드 1: 유령(삼바 삭제·마켓 생존) 방지 검증 ──


def test_OptID_숫자해석_불가는_건너뛰고_예외를_안_던진다():
    """GoodsAdd 원격 성공 후의 파싱 예외는 재시도→중복등록으로 이어지므로 삼킨다."""
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [
            {"OptID": "abc", "Color": "BLACK", "Size": "270"},
            {"OptID": 222, "Color": "BLACK", "Size": "280"},
        ],
    }
    assert extract_option_ids(resp) == {"BLACK|280": 222}


@pytest.mark.asyncio
async def test_1단2단_실패해도_3단은_호출되고_결과는_실패다():
    """1·2단이 is_ok 실패여도 3단은 계속 진행하되 success 는 False."""
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            if op in ("scm_option_upt", "goods_dsp"):
                return {"Status": "ERROR", "Message": "boom"}
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=[]
    )
    assert called == ["scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is False
    assert "1단" in result["message"]
    assert "2단" in result["message"]


@pytest.mark.asyncio
async def test_2단_예외에도_3단은_계속_진행하고_실패로_보고한다():
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            if op == "goods_dsp":
                raise RuntimeError("연결 끊김")
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=[]
    )
    assert called == ["scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is False
    assert "2단" in result["message"]


@pytest.mark.asyncio
async def test_부분_매핑이면_실패로_내리고_미전송_개수를_남긴다():
    """매핑 안 된 옵션은 재고0 이 안 나가 계속 팔린다 — 성공으로 박제 금지."""
    payloads: list[tuple[str, dict]] = []

    class FakeClient:
        async def call(self, op, payload):
            payloads.append((op, payload))
            return {"Status": "OK", "Message": ""}

    options = [
        {"color": "BLACK", "size": "270", "stock": 5, "opt_id": 111},
        {"color": "BLACK", "size": "280", "stock": 5},
        {"color": "BLACK", "size": "290", "stock": 5},
    ]
    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=options
    )
    assert result["success"] is False
    assert "옵션 2건 재고0 미전송" in result["message"]
    # 매핑된 옵션의 재고0 요청은 실제로 나가야 한다
    stock_rows = [p for op, p in payloads if op == "scm_option_upt"]
    assert len(stock_rows) == 1
    assert stock_rows[0]["OptID"] == 111
    assert stock_rows[0]["StockQty"] == 0


@pytest.mark.asyncio
async def test_삭제시_호출측_옵션_dict를_변형하지_않는다():
    class FakeClient:
        async def call(self, op, payload):
            return {"Status": "OK", "Message": ""}

    options = [{"color": "BLACK", "size": "270", "stock": 5, "opt_id": 111}]
    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=options
    )
    assert result["success"] is True
    assert options[0]["stock"] == 5


@pytest.mark.asyncio
async def test_수정시_OptID_매핑_0건이면_실패로_보고한다():
    """options 는 있는데 매핑이 비면 재고가 전혀 안 갱신된다 — 성공 금지."""

    class FakeClient:
        async def call(self, op, payload):
            return {"Status": "OK", "Message": ""}

    product = {
        "sale_price": 10000,
        "options": [{"color": "BLACK", "size": "270", "stock": 5}],
        # _fp_option_ids 없음 → 전송 행 0건
    }
    result = await FashionPlusPlugin()._update(FakeClient(), product, "777")
    assert result["success"] is False
    assert "재고 미갱신" in result["message"]
    assert "가격은 갱신됨" in result["message"]


@pytest.mark.asyncio
async def test_수정시_옵션없는_상품은_가격만으로_성공한다():
    class FakeClient:
        async def call(self, op, payload):
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin()._update(
        FakeClient(), {"sale_price": 10000}, "777"
    )
    assert result["success"] is True
