"""슬로우API 기반 레이트 리미터 — 무차별 인증·자격증명 변경·프록시 자원 고갈 방어.

엔드포인트별 데코레이터로 적용:

    from backend.core.rate_limit import limiter, RATE_LOGIN

    @router.post("/login")
    @limiter.limit(RATE_LOGIN)
    async def login(request: Request, ...):
        ...

`request: Request` 파라미터가 시그니처에 있어야 slowapi 가 키(IP) 추출 가능.

키 함수: Caddy 리버스 프록시 뒤에서 모든 요청은 동일 컨테이너 IP 로 보이므로
`X-Forwarded-For` 의 첫 번째 IP (원본 클라이언트) 를 우선 사용. 헤더 누락 시
fallback 으로 `request.client.host`. 외부 클라이언트가 직접 헤더를 위조할 수
있지만 ApiGatewayMiddleware 의 X-Api-Key 검증을 통과한 후이고, Caddy 자체가
X-Forwarded-For 를 항상 덧붙이는 구조라 신뢰 가능.
"""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse


def _client_key(request: Request) -> str:
    """원본 클라이언트 IP — X-Forwarded-For 우선, fallback request.client.host."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


# 단일 프로세스 in-memory storage. 멀티 워커/멀티 VM 확장 시 Redis storage 로 전환:
#   storage_uri="redis://..."
limiter = Limiter(key_func=_client_key, default_limits=[])


# 사전 정의 정책 — 호출부에서 일관성 유지하기 위해 상수로 묶음.
RATE_LOGIN = "10/minute"          # 무차별 인증 시도 차단 (로그인/check-login)
RATE_SET_COOKIE = "30/minute"     # 자격증명 갱신 — 정상 사용량 충분 + 남용 방지
RATE_PROXY_HEAVY = "300/minute"   # 외부 사이트 호출 (수집/검색/카테고리 스캔)
RATE_PROXY_LIGHT = "1200/minute"  # 가벼운 메타·진단 — 확장앱 동시 폴링 허용


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 + Retry-After 헤더 강제."""
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
            "limit": str(exc.detail),
        },
    )
    # slowapi.RateLimitExceeded.limit 은 Limit 객체, 그 안의 .limit 가
    # limits.RateLimitItem (예: 10/minute → get_expiry()=60).
    try:
        expiry = exc.limit.limit.get_expiry()
        response.headers["Retry-After"] = str(int(expiry))
    except Exception:
        # 정책 객체 변경 등 예외는 무시 — 응답 자체는 정상 반환
        pass
    return response
