"""무신사 로그인 판정이 죽은 회원 API로 되돌아가는 회귀 차단 (2026-09-03).

배경: 무신사가 회원 API `api2/member/v1/me` 를 없앴다 — 쿠키 유무와 무관하게 항상 404
(member/v2, user/v1, facade-member, my./member.one 변형 전부 404). 그 결과
`check_login_status` 는 항상 "로그인 안 됨", `set_cookie_and_verify` 는 검증을 못 한 채
"쿠키가 설정되었습니다" 만 답했다 — 만료된 쿠키를 정상으로 통과시키는 상태였다.

조치: 상품 상세의 회원 전용 필드로 판정. 실측(2026-09-03)
    쿠키O → memberGrade={"level":9,"levelName":"블랙다이아몬드"}, point.memberPoint=702429
    쿠키X → memberGrade=null, point.memberPoint=0

아래 테스트는 세션 팩토리를 가짜로 갈아끼워 fetch_member_state 를 실제로 실행한다.
"""

from __future__ import annotations

import inspect
import io
import tokenize
from typing import Any

import backend.domain.samba.proxy.musinsa as musinsa_mod
from backend.domain.samba.proxy.musinsa import MusinsaClient


def _code_only(src: str) -> str:
    """주석·독스트링을 걷어낸 실행 코드만 남긴다 (설명문의 URL 오탐 방지)."""
    out: list[str] = []
    prev = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.NL,
            tokenize.DEDENT,
        ):
            continue
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            prev = tok.type
        out.append(tok.string)
    return " ".join(out)


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    """URL별 응답을 정해 두고 돌려주는 가짜 curl_cffi 세션."""

    def __init__(self, routes: dict[str, _FakeResponse], calls: list[str]):
        self._routes = routes
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, **kw):
        self._calls.append(url)
        for frag, resp in self._routes.items():
            if frag in url:
                return resp
        return _FakeResponse(404, {})


def _install(monkeypatch, routes: dict[str, _FakeResponse]) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        musinsa_mod,
        "_musinsa_session",
        lambda *a, **k: _FakeSession(routes, calls),
    )
    return calls


_PROBE = MusinsaClient.MEMBER_PROBE_GOODS_NO


def test_dead_member_api_not_referenced() -> None:
    """죽은 회원 API 로 되돌아가면 로그인 판정이 통째로 거짓이 된다."""
    src = _code_only(inspect.getsource(musinsa_mod))
    assert "member/v1/me" not in src
    assert "BASE_MEMBER" not in src


async def test_logged_in_reads_grade_and_point(monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            f"/{_PROBE}": _FakeResponse(
                200,
                {
                    "data": {
                        "memberGrade": {"level": 9, "levelName": "블랙다이아몬드"},
                        "point": {"memberPoint": 702429},
                    }
                },
            )
        },
    )
    state = await MusinsaClient("SESSION=live").fetch_member_state()
    assert state == {
        "isLoggedIn": True,
        "gradeName": "블랙다이아몬드",
        "memberPoint": 702429,
    }


async def test_expired_cookie_is_not_logged_in(monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            f"/{_PROBE}": _FakeResponse(
                200, {"data": {"memberGrade": None, "point": {"memberPoint": 0}}}
            )
        },
    )
    state = await MusinsaClient("SESSION=expired").fetch_member_state()
    assert state["isLoggedIn"] is False
    assert state["gradeName"] == ""

    verified = await MusinsaClient("SESSION=expired").set_cookie_and_verify("SESSION=expired")
    assert verified["isLoggedIn"] is False
    assert "만료" in verified["message"]


async def test_probe_falls_back_to_live_goods_no(monkeypatch) -> None:
    """프로브 상품이 단종되면 검색으로 살아있는 상품을 집어 재시도한다."""
    calls = _install(
        monkeypatch,
        {
            f"/{_PROBE}": _FakeResponse(404, {}),
            "plp/goods": _FakeResponse(200, {"data": {"list": [{"goodsNo": 9999999}]}}),
            "/9999999": _FakeResponse(
                200,
                {"data": {"memberGrade": {"levelName": "골드"}, "point": {"memberPoint": 100}}},
            ),
        },
    )
    state = await MusinsaClient("SESSION=live").fetch_member_state()
    assert state["isLoggedIn"] is True and state["gradeName"] == "골드"
    assert any("plp/goods" in u for u in calls), "검색 폴백이 호출되지 않았다"


async def test_unknown_when_probe_unavailable(monkeypatch) -> None:
    """판정 자체가 불가하면 '로그인 아님'이 아니라 unknown 으로 구분한다."""
    _install(monkeypatch, {})  # 전부 404
    assert await MusinsaClient("SESSION=live").fetch_member_state() == {}
    res = await MusinsaClient("SESSION=live").check_login_status()
    assert res["isLoggedIn"] is False and res["unknown"] is True


async def test_empty_cookie_short_circuits(monkeypatch) -> None:
    calls = _install(monkeypatch, {})
    state = await MusinsaClient("").fetch_member_state()
    assert state == {"isLoggedIn": False, "gradeName": "", "memberPoint": 0}
    assert calls == [], "쿠키가 없으면 무신사로 나가지 않아야 한다"
