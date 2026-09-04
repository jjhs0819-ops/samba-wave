"""토스 마켓 플러그인 검증 — 네트워크 없이 클라이언트를 주입한다."""

import pytest

from backend.domain.samba.plugins.markets.toss import TossPlugin
from backend.domain.samba.proxy.toss import TossApiError

SETTINGS = {
    "deliveryLocationId": 1,
    "exchangeRefundLocationId": 2,
    "stockQuantity": 99,
}
PRODUCT = {"name": "테스트상품", "sale_price": 10000, "options": []}


class FakeClient:
    def __init__(self, register=None, error=None):
        self.calls: list[tuple] = []
        self._register = register or {"id": 777}
        self._error = error

    async def register_product(self, payload):
        self.calls.append(("register", payload))
        if self._error:
            raise self._error
        return self._register

    async def update_product(self, product_id, payload):
        self.calls.append(("update", product_id))
        if self._error:
            raise self._error
        return {}

    async def delete_product(self, product_id):
        self.calls.append(("delete", product_id))
        if self._error:
            raise self._error
        return {}


def test_레지스트리_식별자():
    plugin = TossPlugin()
    assert plugin.market_type == "toss"
    assert plugin.policy_key == "토스"


@pytest.mark.asyncio
async def test_신규등록은_응답_id를_상품번호로_돌려준다():
    client = FakeClient(register={"id": 777})
    result = await TossPlugin().execute_with_client(
        client, PRODUCT, "12345", SETTINGS, existing_no=""
    )
    assert result["success"] is True
    assert result["product_no"] == "777"
    assert client.calls[0][0] == "register"


@pytest.mark.asyncio
async def test_기존번호가_있으면_수정을_호출한다():
    client = FakeClient()
    result = await TossPlugin().execute_with_client(
        client, PRODUCT, "12345", SETTINGS, existing_no="777"
    )
    assert result["success"] is True
    assert result["product_no"] == "777"
    assert client.calls == [("update", "777")]


@pytest.mark.asyncio
async def test_토스에러는_실패로_변환한다():
    client = FakeClient(error=TossApiError("[INVALID_REQUEST] 필수 값이 누락"))
    result = await TossPlugin().execute_with_client(
        client, PRODUCT, "12345", SETTINGS, existing_no=""
    )
    assert result["success"] is False
    assert "필수 값" in result["message"]
    assert result["error_type"]


@pytest.mark.asyncio
async def test_삭제는_클라이언트_삭제를_태운다():
    client = FakeClient()
    result = await TossPlugin().delete_with_client(client, "777")
    assert result["success"] is True
    assert client.calls == [("delete", "777")]


@pytest.mark.asyncio
async def test_삭제실패는_실패로_돌려준다():
    client = FakeClient(error=TossApiError("[NOT_FOUND] 없음"))
    result = await TossPlugin().delete_with_client(client, "777")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_키가_없으면_인증실패로_끝낸다():
    result = await TossPlugin().execute(
        session=None,
        product=PRODUCT,
        creds={},
        category_id="12345",
        account=None,
        existing_no="",
    )
    assert result["success"] is False
    assert result["error_type"] == "auth_failed"


class NoticeClient(FakeClient):
    """고시 항목을 내려주는 가짜 클라이언트."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.notice_calls = 0

    async def list_notice_items(self, category_code):
        self.notice_calls += 1
        return {
            "items": [
                {"id": 47, "title": "2. 색상"},
                {"id": 59, "title": "8. A/S 책임자와 전화번호"},
            ]
        }


@pytest.mark.asyncio
async def test_고시항목이_비면_조회해서_채운다():
    """고시 content 가 비면 토스가 등록을 거부한다."""
    from backend.domain.samba.proxy.toss import clear_notice_cache

    clear_notice_cache()
    client = NoticeClient()
    await TossPlugin().execute_with_client(
        client,
        {**PRODUCT, "color": "화이트"},
        "12345",
        {**SETTINGS, "noticeCategoryCode": "SHOES", "asPhone": "010-1111-2222"},
        existing_no="",
    )
    payload = client.calls[0][1]
    items = {i["id"]: i["content"] for i in payload["notice"]["items"]}
    assert items == {47: "화이트", 59: "010-1111-2222"}


@pytest.mark.asyncio
async def test_고시조회는_카테고리코드별로_캐시한다():
    from backend.domain.samba.proxy.toss import clear_notice_cache

    clear_notice_cache()
    client = NoticeClient()
    settings = {**SETTINGS, "noticeCategoryCode": "SHOES"}
    for _ in range(3):
        await TossPlugin().execute_with_client(
            client, PRODUCT, "12345", settings, existing_no=""
        )
    assert client.notice_calls == 1
