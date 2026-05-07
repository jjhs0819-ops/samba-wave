"""슬로우API 기반 레이트 리미터 — 무차별 인증·자격증명 변경·프록시 자원 고갈 방어.

엔드포인트별 데코레이터로 적용:

    from backend.core.rate_limit import limiter, RATE_LOGIN

    @router.post("/login")
    @limiter.limit(RATE_LOGIN)
    async def login(request: Request, ...):
        ...

`request: Request` 파라미터가 시그니처에 있어야 slowapi 가 키(IP) 추출 가능.

기본 키 함수: 원격 IP. 프록시 뒤(Caddy)에서 `X-Forwarded-For` 사용은
ApiGatewayMiddleware 가 trust 한 후 starlette 가 client.host 로 노출.
"""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse


# 단일 프로세스 in-memory storage. 멀티 워커/멀티 VM 확장 시 Redis storage 로 전환:
#   storage_uri="redis://..."
limiter = Limiter(key_func=get_remote_address, default_limits=[])


# 사전 정의 정책 — 호출부에서 일관성 유지하기 위해 상수로 묶음.
RATE_LOGIN = "10/minute"          # 무차별 인증 시도 차단 (로그인/check-login)
RATE_SET_COOKIE = "30/minute"     # 자격증명 갱신 — 정상 사용량 충분 + 남용 방지
RATE_PROXY_HEAVY = "300/minute"   # 외부 사이트 호출 (수집/검색/카테고리 스캔)
RATE_PROXY_LIGHT = "1200/minute"  # 가벼운 메타·진단 — 확장앱 동시 폴링 허용


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """슬로우API 기본 핸들러 + Retry-After 헤더 강제."""
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
            "limit": str(exc.detail),
        },
    )
    # slowapi 는 자동으로 Retry-After 를 붙이지 않음 — 수동 추가
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        response.headers["Retry-After"] = str(int(retry_after))
    return response
