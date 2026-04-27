"""API Gateway Key 검증 미들웨어 — 외부 앱의 무단 API 접근 차단."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 키 검증을 건너뛸 경로 (health check, 루트)
_EXEMPT_PATHS = {
    "/",
    "/api/v1/health",
    "/api/v1/samba/sourcing-accounts/extension-key",
    "/api/v1/license/verify",
}

# 키 검증을 건너뛸 prefix (정적 자산 — 모델 프리셋 PNG 등)
# 화이트리스트 누락 시 프론트가 무한 재요청하며 워커 event loop 소모 → health timeout 유발
_EXEMPT_PREFIXES = (
    "/static/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/samba/proxy/bg-jobs/",  # bg-worker 내부 호출 — 워커 토큰으로 자체 인증
)


class ApiGatewayMiddleware(BaseHTTPMiddleware):
    """X-Api-Key 헤더를 검증하여 허가된 클라이언트만 API 접근 허용."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # CORS preflight는 통과
        if request.method == "OPTIONS":
            return await call_next(request)

        # 면제 경로는 통과
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)
        if request.url.path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        # 키가 설정되지 않은 경우(개발환경) 통과
        if not self.api_key:
            return await call_next(request)

        # X-Api-Key 헤더 검증
        request_key = request.headers.get("X-Api-Key", "")
        if request_key != self.api_key:
            logger.warning(
                f"[api-gateway] 차단: {request.method} {request.url.path} "
                f"(IP: {request.client.host if request.client else 'unknown'})"
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "유효하지 않은 API 키입니다."},
            )

        return await call_next(request)
