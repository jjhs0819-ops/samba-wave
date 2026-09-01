"""BUYMA webhook 서명 검증 테스트.

이 경로는 게이트웨이 키 검증이 면제돼 있고(BUYMA가 X-Api-Key를 안 보냄),
order/create 페이로드에 구매자 실명·주소·전화가 들어온다. 즉 서명 검증이
이 라우트의 유일한 방어선이라, 검증이 뚫리면 아무나 가짜 주문을 우리 DB에
넣을 수 있다. 그래서 거부 경로를 테스트로 못박아 둔다.

DB는 붙이지 않는다 — 계정 조회만 스텁으로 대체하면 서명 판정 로직 전체를
그대로 태울 수 있고, 그게 여기서 지켜야 할 부분이다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.v1.routers.samba.proxy.buyma_webhook import buyma_webhook_router
from backend.db.orm import get_write_session_dependency

SECRET = "app-secret-abc123"
OTHER_SECRET = "someone-elses-secret"


class _FakeAccount:
    id = "ma_test_buyma"
    tenant_id = None
    api_secret = SECRET
    account_label = "BUYMA(테스트)"


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeSession:
    """계정 조회만 응답하는 세션 스텁. 서명 거부 경로는 여기까지만 오면 끝난다."""

    def __init__(self, accounts):
        self.accounts = accounts
        self.added: list = []
        self.commits = 0

    async def execute(self, _stmt):
        return _Result(self.accounts)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


def _make_app(accounts) -> tuple[FastAPI, _FakeSession]:
    session = _FakeSession(accounts)
    app = FastAPI()
    app.include_router(buyma_webhook_router, prefix="/samba")
    app.dependency_overrides[get_write_session_dependency] = lambda: session
    return app, session


async def _post(app, body: bytes, headers: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post("/samba/buyma/webhook", content=body, headers=headers)


BODY = json.dumps({"id": 771829, "status": "new"}).encode()


@pytest.mark.asyncio
async def test_서명_헤더_없으면_401():
    app, session = _make_app([_FakeAccount()])
    resp = await _post(app, BODY, {"X-Buyma-Event": "order/create"})
    assert resp.status_code == 401
    assert session.commits == 0, "서명 없는 요청이 DB에 커밋되면 안 된다"


@pytest.mark.asyncio
async def test_서명_틀리면_401():
    app, session = _make_app([_FakeAccount()])
    resp = await _post(
        app,
        BODY,
        {
            "X-Buyma-Event": "order/create",
            "X-Buyma-Hmac-Sha256": _sign(OTHER_SECRET, BODY),
        },
    )
    assert resp.status_code == 401
    assert session.commits == 0


@pytest.mark.asyncio
async def test_바디가_변조되면_401():
    """서명은 진짜 시크릿으로 만들었지만 바디를 바꿔치기한 경우."""
    app, session = _make_app([_FakeAccount()])
    resp = await _post(
        app,
        b'{"id": 999999, "status": "new"}',
        {
            "X-Buyma-Event": "order/create",
            "X-Buyma-Hmac-Sha256": _sign(SECRET, BODY),
        },
    )
    assert resp.status_code == 401
    assert session.commits == 0


@pytest.mark.asyncio
async def test_시크릿_없는_계정만_있으면_401():
    """api_secret 미설정 계정을 빈 문자열로 서명 비교하면 안 된다."""

    class _NoSecret(_FakeAccount):
        api_secret = ""

    app, session = _make_app([_NoSecret()])
    resp = await _post(
        app,
        BODY,
        {"X-Buyma-Event": "order/create", "X-Buyma-Hmac-Sha256": _sign("", BODY)},
    )
    assert resp.status_code == 401
    assert session.commits == 0


@pytest.mark.asyncio
async def test_서명_맞으면_통과():
    """미지원 이벤트로 보내 DB 분기 없이 서명 통과만 확인."""
    app, _ = _make_app([_FakeAccount()])
    resp = await _post(
        app,
        BODY,
        {
            "X-Buyma-Event": "order/some_future_event",
            "X-Buyma-Hmac-Sha256": _sign(SECRET, BODY),
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_계정이_여러개여도_맞는_시크릿을_찾는다():
    """캐논·임형준처럼 앱이 둘 이상일 때 두 번째 계정 것도 통과해야 한다."""

    class _First(_FakeAccount):
        id = "ma_other"
        api_secret = OTHER_SECRET

    app, _ = _make_app([_First(), _FakeAccount()])
    resp = await _post(
        app,
        BODY,
        {
            "X-Buyma-Event": "order/some_future_event",
            "X-Buyma-Hmac-Sha256": _sign(SECRET, BODY),
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_서명은_맞지만_JSON이_깨졌으면_400():
    body = b"{not json"
    app, session = _make_app([_FakeAccount()])
    resp = await _post(
        app,
        body,
        {
            "X-Buyma-Event": "order/create",
            "X-Buyma-Hmac-Sha256": _sign(SECRET, body),
        },
    )
    assert resp.status_code == 400
    assert session.commits == 0
