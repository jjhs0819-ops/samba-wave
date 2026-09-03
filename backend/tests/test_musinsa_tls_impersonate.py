"""무신사 요청이 httpx 로 되돌아가는 회귀 차단 (2026-09-03, #774).

배경: 2026-09-03 14시경 무신사(Cloudflare)가 TLS 지문 기반 차단을 켰다.
같은 공인 IP·같은 쿠키인데 브라우저·Schannel curl 은 200, 컨테이너의
httpx/OpenSSL 은 전 API 403("Attention Required")이었다. 헤더·UA 로는 못 넘는
지문 차단이라 오토튠 무신사 갱신이 4시간 넘게 0건이었다(연속 차단 282회).

조치: 29CM/네이버스토어와 같이 curl_cffi AsyncSession(impersonate="chrome").
이 테스트는 무신사 경로 3곳(클라이언트·오토튠 공유풀·잡워커 벌크수집)이
httpx 로 되돌아가지 않도록 고정한다.
"""

from __future__ import annotations

import inspect
import io
import tokenize

from backend.domain.samba.collector import refresher as refresher_mod
from backend.domain.samba.job import worker as worker_mod
from backend.domain.samba.proxy import musinsa as musinsa_mod


def _code_only(src: str) -> str:
    """주석·독스트링을 걷어낸 실행 코드만 남긴다.

    이 파일들의 설명 주석에 'httpx' 가 그대로 등장하므로 문자열 검사만으로는
    오탐이 난다.
    """
    out: list[str] = []
    prev_type = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        # 문장 시작 위치의 문자열 = 독스트링
        if tok.type == tokenize.STRING and prev_type in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.NL,
            tokenize.DEDENT,
        ):
            continue
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            prev_type = tok.type
        out.append(tok.string)
    return " ".join(out)


def test_musinsa_module_has_no_httpx_client() -> None:
    """musinsa.py 안에서 httpx 클라이언트를 만들면 즉시 전 API 403 이 된다."""
    src = _code_only(inspect.getsource(musinsa_mod))
    assert "httpx" not in src


def test_musinsa_session_impersonates_chrome() -> None:
    """세션 팩토리는 Chrome 지문 위장 + httpx 와 같은 리다이렉트/타임아웃 규격."""
    captured: dict = {}

    class _FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    orig = musinsa_mod.AsyncSession
    try:
        musinsa_mod.AsyncSession = _FakeSession
        musinsa_mod._musinsa_session(
            30.0, connect=5.0, proxy_url="http://p:1", follow_redirects=True
        )
    finally:
        musinsa_mod.AsyncSession = orig

    assert captured["impersonate"] == "chrome"
    # httpx.Timeout(read, connect=connect) → curl_cffi (connect, read)
    assert captured["timeout"] == (5.0, 30.0)
    # curl_cffi 기본 allow_redirects=True — httpx 기본(False)과 반대라 명시 필수
    assert captured["allow_redirects"] is True
    assert captured["proxies"] == {"http": "http://p:1", "https": "http://p:1"}


def test_musinsa_session_default_no_redirect() -> None:
    """옵션 없이 부르면 httpx 기본과 같은 '리다이렉트 안 따라감' 이어야 한다."""
    captured: dict = {}

    class _FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    orig = musinsa_mod.AsyncSession
    try:
        musinsa_mod.AsyncSession = _FakeSession
        musinsa_mod._musinsa_session(15.0)
    finally:
        musinsa_mod.AsyncSession = orig

    assert captured["allow_redirects"] is False
    assert "proxies" not in captured


def test_autotune_shared_client_impersonates_chrome() -> None:
    """오토튠 공유 세션이 httpx 로 새면 오토튠 무신사만 통째로 403 된다."""
    raw = inspect.getsource(refresher_mod._get_musinsa_shared_client)
    assert '"impersonate": "chrome"' in raw
    assert "httpx" not in _code_only(raw)


def test_worker_musinsa_bulk_collect_impersonates_chrome() -> None:
    """잡워커 벌크 상세수집(전체/브랜드) 공유 세션도 같은 규격이어야 한다."""
    src = inspect.getsource(worker_mod)
    assert "_shared_http = _AsyncSession(" in src
    assert '_httpx.AsyncClient(timeout=_httpx.Timeout(30, connect=5.0))' not in src
    assert src.count('_AsyncSession(timeout=(5.0, 30), impersonate="chrome")') == 2
