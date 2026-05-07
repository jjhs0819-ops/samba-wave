"""보안 응답 헤더 미들웨어 — HSTS / CSP / X-Content-Type-Options 등."""

from __future__ import annotations

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# JSON API 응답에 적용할 가장 엄격한 CSP — 브라우저가 응답을 HTML 로 렌더할
# 가능성 자체를 차단. default-src 'none' 이 모든 fetch/script/style/img 등을
# 묵시적으로 차단하지만, 일부 구버전 브라우저가 default-src 를 제대로 상속하지
# 못하는 경우를 대비해 script-src/style-src 를 명시적으로 'none' 으로 강제.
_CSP_API = (
    "default-src 'none'; "
    "script-src 'none'; "
    "style-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'"
)

# 정적 자산 응답에 적용할 CSP — img / font / static 자산. 같은 origin 만 허용.
_CSP_STATIC = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)

# Swagger UI / ReDoc 같은 CDN inline-script 페이지는 별도 CSP 가 필요 — 운영
# 환경에서는 docs 가 비활성화되어 있어 현재는 면제 처리.

# CSP 를 면제할 path (HTML 문서 페이지 등)
_CSP_EXEMPT_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
)

# 정적 자산 prefix (별도 CSP 적용)
_STATIC_PREFIXES = ("/static/",)

_BASE_HEADERS: dict[str, str] = {
    # HTTPS 강제 (Caddy 가 1년 TLS — preload 등재 가능 수준)
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    # MIME sniffing 차단
    "X-Content-Type-Options": "nosniff",
    # iframe embed 차단 (CSP frame-ancestors 와 중복이지만 구식 브라우저 호환)
    "X-Frame-Options": "DENY",
    # 외부 사이트로 referer 노출 최소화
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # 카메라/마이크/위치정보 등 강력한 권한 명시 차단
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _csp_for(path: str) -> str | None:
    """요청 경로에 따라 적용할 CSP 문자열 반환. None 이면 CSP 헤더 미적용."""
    if path.startswith(_CSP_EXEMPT_PREFIXES):
        return None
    if path.startswith(_STATIC_PREFIXES):
        return _CSP_STATIC
    return _CSP_API


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """모든 응답에 표준 보안 헤더 + path 별 CSP 부착."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)

        # 이미 다운스트림에서 같은 헤더를 직접 설정했다면 덮어쓰지 않음
        for header, value in _BASE_HEADERS.items():
            response.headers.setdefault(header, value)

        csp = _csp_for(request.url.path)
        if csp is not None:
            response.headers.setdefault("Content-Security-Policy", csp)

        return response
