"""토스쇼핑 Open API 클라이언트 — 인증/봉투/변환 검증(네트워크 없음).

라이브 실측(2026-09-04, 우경이 계정)으로 확정한 사양을 고정한다:
  1) 토큰: POST https://oauth2.cert.toss.im/token, form 인코딩 + snake_case
     (client_id/client_secret). 문서의 camelCase(clientId)는 invalid_client 로 거부됨.
  2) 호출 헤더: Authorization: Bearer {token}. 문서의 접두사 없는 표기는 401.
  3) 토큰 수명: expires_in 3599초(문서의 1년이 아님) → 캐시는 만료 여유를 둬야 함.
  4) ★함정★ 실패해도 HTTP 200 으로 내려온다. resultType=FAIL 로 판정해야 한다.
"""

import json

import httpx
import pytest

from backend.domain.samba.proxy.toss import TossApiError, TossClient

TOKEN_HOST = "oauth2.cert.toss.im"


def _client(handler) -> TossClient:
    """MockTransport 를 물린 클라이언트."""
    TossClient.clear_token_cache()
    c = TossClient("AK", "SK")
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c._get_client = lambda: mock  # type: ignore[method-assign]
    return c


def _token_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "TOK",
            "scope": "toss-shopping-fep:write",
            "token_type": "Bearer",
            "expires_in": 3599,
        },
    )


def _envelope(success) -> dict:
    return {"resultType": "SUCCESS", "success": success, "error": None}


# ----------------------------------------------------------------- 인증


async def test_토큰은_form_snake_case로_발급한다():
    seen = {}

    def handler(request):
        if request.url.host == TOKEN_HOST:
            seen["ctype"] = request.headers.get("content-type", "")
            seen["body"] = request.content.decode()
            return _token_ok(request)
        return httpx.Response(200, json=_envelope({}))

    c = _client(handler)
    await c.get_product("1")

    assert "application/x-www-form-urlencoded" in seen["ctype"]
    assert "client_id=AK" in seen["body"]
    assert "client_secret=SK" in seen["body"]
    assert "grant_type=client_credentials" in seen["body"]
    assert "scope=toss-shopping-fep" in seen["body"]
    # camelCase 로 보내면 토스가 invalid_client 로 거부한다
    assert "clientId" not in seen["body"]


async def test_인증헤더는_Bearer_접두사를_붙인다():
    seen = {}

    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=_envelope({}))

    c = _client(handler)
    await c.get_product("1")

    assert seen["auth"] == "Bearer TOK"


async def test_토큰은_만료전까지_재사용한다():
    calls = {"token": 0}

    def handler(request):
        if request.url.host == TOKEN_HOST:
            calls["token"] += 1
            return _token_ok(request)
        return httpx.Response(200, json=_envelope({}))

    c = _client(handler)
    await c.get_product("1")
    await c.get_product("2")

    assert calls["token"] == 1


# ----------------------------------------------------------------- 응답 봉투


async def test_HTTP200이어도_resultType_FAIL이면_에러다():
    """★핵심 함정★ 토스는 실패도 200 으로 내려준다."""

    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        return httpx.Response(
            200,
            json={
                "resultType": "FAIL",
                "success": None,
                "error": {
                    "errorType": 0,
                    "errorCode": "NOT_FOUND",
                    "reason": "존재하지 않는 상품 정보입니다. (999)",
                    "data": {},
                    "title": None,
                },
            },
        )

    c = _client(handler)
    with pytest.raises(TossApiError) as e:
        await c.get_product("999")

    assert "NOT_FOUND" in str(e.value)
    assert "존재하지 않는 상품" in str(e.value)


async def test_success_봉투를_벗겨서_반환한다():
    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        return httpx.Response(200, json=_envelope({"id": 12345}))

    c = _client(handler)
    assert await c.get_product("12345") == {"id": 12345}


# ----------------------------------------------------------------- 상품 CRUD


async def test_상품등록은_v3_경로로_POST한다():
    seen = {}

    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json=_envelope({"id": 777}))

    c = _client(handler)
    result = await c.register_product({"name": "테스트"})

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v3/shopping-fep/products/v2"
    assert result["id"] == 777


async def test_상품수정은_productId_경로로_PUT한다():
    seen = {}

    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json=_envelope({}))

    c = _client(handler)
    await c.update_product("777", {"name": "수정"})

    assert seen["method"] == "PUT"
    assert seen["path"] == "/api/v3/shopping-fep/products/777/v2"


async def test_상품삭제는_숨기기_후_삭제한다():
    """노출중인 상품은 바로 삭제할 수 없다 — hide 를 먼저 태워야 한다."""
    paths = []

    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        paths.append(request.url.path)
        return httpx.Response(200, json=_envelope({}))

    c = _client(handler)
    await c.delete_product("777")

    assert paths == [
        "/api/v3/shopping-fep/products/hide",
        "/api/v3/shopping-fep/products/remove",
    ]


async def test_재고변경은_품절해제까지_한번에_보낸다():
    seen = {}

    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_envelope({}))

    c = _client(handler)
    await c.update_stock(product_id="777", item_id="888", remaining_count=0)

    assert seen["path"] == (
        "/api/v3/shopping-fep/product-items/888/stocks/normal-stock/remaining-count"
    )
    assert seen["body"] == {"productId": 777, "remainingCount": 0}


async def test_판매가변경은_productItemId_경로로_PUT한다():
    seen = {}

    def handler(request):
        if request.url.host == TOKEN_HOST:
            return _token_ok(request)
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_envelope({}))

    c = _client(handler)
    await c.update_sale_price(product_id="777", item_id="888", sale_price=19900)

    assert seen["path"] == "/api/v3/shopping-fep/product-items/888/sale-price"
    assert seen["body"] == {"productId": 777, "salePrice": 19900}
