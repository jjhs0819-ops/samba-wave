"""httpx SSL 컨텍스트 공유 설치기.

## 왜 필요한가

httpx.AsyncClient() 를 만들 때마다 httpx 는 내부적으로
ssl.create_default_context() 를 호출해 certifi CA 번들(약 150개 인증서)을
디스크에서 읽고 전부 파싱한다. 운영 컨테이너 실측 **42ms/회**이고, 전 구간이
동기 코드라 asyncio 이벤트루프를 그대로 정지시킨다.

삼바 백엔드에는 httpx.AsyncClient() 생성 지점이 195곳 있고 대부분 호출마다
새로 만든다. 오토튠이 200건 배치를 돌리면 200 x 42ms = **8.4초** 동안 API 가
어떤 HTTP 요청도 처리하지 못한다. 2026-08-19 조사에서 측정된 이벤트루프
블로킹(48회/17분, 평균 8.5초, 최대 16.7초)의 정체가 이것이었다.

## 무엇을 하는가

SSLContext 는 상태를 갖지 않고 스레드 안전해서 여러 커넥션이 공유하는 것이
표준 사용법이다. 따라서 (verify, trust_env) 조합마다 컨텍스트를 1개만 만들어
재사용한다. 실측 42.0ms → 0.1ms.

## 무엇을 하지 않는가

**클라이언트 자체는 계속 새로 만든다.** abcmart 등 일부 소싱처는 클라이언트를
만들 때마다 프록시를 교체(_next_proxy)하므로 클라이언트를 재사용하면 프록시
로테이션이 깨진다. 여기서는 CPU 비용만 없애고 커넥션·프록시·쿠키 동작은
1도 건드리지 않는다.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

# (verify, trust_env) → SSLContext. 프로세스당 최대 4개(True/False x True/False).
_context_cache: dict[tuple[bool, bool], ssl.SSLContext] = {}

_installed = False


def install_shared_ssl_context() -> None:
    """httpx 트랜스포트의 SSL 컨텍스트 생성을 캐시로 교체한다 (멱등).

    httpx 의 동기/비동기 트랜스포트가 모두 httpx._transports.default 모듈의
    create_ssl_context 이름을 참조하므로, 이 한 곳만 교체하면 클라이언트 생성
    지점 195곳이 전부 혜택을 본다(호출부 수정 불필요).
    """
    global _installed
    if _installed:
        return

    import httpx
    import httpx._transports.default as _httpx_transport

    # 이 패치는 httpx 내부 이름(_transports.default.create_ssl_context)에 기댄다.
    # 업그레이드로 그 이름이 사라지면 AttributeError 로 부팅이 막혀 바로 알 수 있지만,
    # 이름은 남은 채 내부에서 더 이상 호출하지 않게 바뀌면 패치가 '조용히' 무효가 되고
    # 42ms 블로킹이 아무 신호 없이 재발한다. 검증한 버전을 벗어나면 로그로 알린다.
    _VERIFIED_HTTPX = "0.28.1"
    if getattr(httpx, "__version__", None) != _VERIFIED_HTTPX:
        logging.getLogger(__name__).warning(
            "[httpx-ssl] 검증된 httpx %s 가 아닌 %s 입니다 — SSL 컨텍스트 캐시가 "
            "무효화됐을 수 있으니 클라이언트 생성 비용을 재측정하세요.",
            _VERIFIED_HTTPX,
            getattr(httpx, "__version__", "unknown"),
        )

    original = _httpx_transport.create_ssl_context

    def _cached_create_ssl_context(
        verify: Any = True,
        cert: Any = None,
        trust_env: bool = True,
    ) -> ssl.SSLContext:
        # 이미 컨텍스트를 직접 넘긴 경우 — 원본도 그대로 반환하므로 비용 없음.
        if isinstance(verify, ssl.SSLContext):
            return verify

        # 캐시 대상은 verify=bool + 클라이언트 인증서 없음인 경우로 한정한다.
        # 그 외(문자열 경로·클라이언트 인증서)는 원본에 그대로 위임해 동작 보존.
        if not isinstance(verify, bool) or cert is not None:
            return original(verify=verify, cert=cert, trust_env=trust_env)

        key = (verify, bool(trust_env))
        context = _context_cache.get(key)
        if context is None:
            context = original(verify=verify, cert=cert, trust_env=trust_env)
            _context_cache[key] = context
        return context

    # 원본 보존 — 디버깅/원복 시 식별용.
    _cached_create_ssl_context.__wrapped__ = original  # type: ignore[attr-defined]

    _httpx_transport.create_ssl_context = _cached_create_ssl_context
    _installed = True
