"""httpx SSL 컨텍스트 재사용 회귀 테스트.

배경: httpx.AsyncClient() 를 매 호출마다 새로 만들면 httpx 가 내부적으로
ssl.create_default_context() 를 호출해 CA 번들(certifi) 전체를 디스크에서
읽고 파싱한다. 실측 42ms/회이며 전부 동기 실행이라 asyncio 이벤트루프를
그대로 정지시킨다. 오토튠이 200건 배치를 돌리면 200 x 42ms = 8.4초 동안
API 가 어떤 요청도 처리하지 못한다(2026-08-19 운영 장애 원인).

대책: SSL 컨텍스트는 상태를 갖지 않고 스레드 안전하므로 (verify, cert,
trust_env) 조합별로 1개만 만들어 공유한다. 클라이언트 자체는 계속 새로
만든다 — abcmart 등이 호출마다 프록시를 교체하므로 클라이언트를 재사용하면
프록시 로테이션이 깨진다.
"""

import ssl
import time

import httpx

from backend.core.httpx_ssl import install_shared_ssl_context


def test_컨텍스트가_호출마다_동일_객체로_재사용된다():
    install_shared_ssl_context()

    from httpx._transports.default import create_ssl_context

    first = create_ssl_context(verify=True, cert=None, trust_env=True)
    second = create_ssl_context(verify=True, cert=None, trust_env=True)

    assert isinstance(first, ssl.SSLContext)
    assert first is second, "동일 인자면 같은 SSLContext 를 반환해야 한다"


def test_클라이언트_생성이_이벤트루프를_막지_않을_만큼_빨라진다():
    install_shared_ssl_context()

    # 워밍업 — 최초 1회는 실제 컨텍스트 생성 비용이 든다(캐시 채우기).
    _ = httpx.AsyncClient()

    started = time.perf_counter()
    clients = [httpx.AsyncClient() for _ in range(20)]
    elapsed_ms = (time.perf_counter() - started) / 20 * 1000

    assert clients  # 생성 자체는 정상
    # 수정 전 실측 42.0ms/회 → 공유 시 0.1ms/회. 5ms 는 넉넉한 상한.
    assert elapsed_ms < 5.0, f"클라이언트 생성이 여전히 느림: {elapsed_ms:.1f}ms/회"


def test_verify_False_는_검증을_끈_별도_컨텍스트를_준다():
    install_shared_ssl_context()

    from httpx._transports.default import create_ssl_context

    insecure = create_ssl_context(verify=False, cert=None, trust_env=True)
    secure = create_ssl_context(verify=True, cert=None, trust_env=True)

    assert insecure is not secure, "verify 값이 다르면 컨텍스트도 달라야 한다"
    assert insecure.verify_mode == ssl.CERT_NONE
    assert secure.verify_mode == ssl.CERT_REQUIRED


def test_SSLContext_를_직접_넘기면_그대로_통과시킨다():
    install_shared_ssl_context()

    from httpx._transports.default import create_ssl_context

    custom = ssl.create_default_context()
    assert create_ssl_context(verify=custom, cert=None, trust_env=True) is custom


def test_두_번_설치해도_중복_래핑되지_않는다():
    install_shared_ssl_context()
    from httpx._transports.default import create_ssl_context as once

    install_shared_ssl_context()
    from httpx._transports.default import create_ssl_context as twice

    assert once is twice, "재설치가 래퍼를 중첩시키면 안 된다"
