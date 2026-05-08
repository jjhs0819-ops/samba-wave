"""슬로우API 기반 레이트 리미터 — 무차별 인증·자격증명 변경·프록시 자원 고갈 방어.

엔드포인트별 데코레이터로 적용:

    from backend.core.rate_limit import limiter, RATE_LOGIN

    @router.post("/login")
    @limiter.limit(RATE_LOGIN)
    async def login(request: Request, ...):
        ...

`request: Request` 파라미터가 시그니처에 있어야 slowapi 가 키(IP) 추출 가능.
이 파라미터를 rename/제거하면 limiter 가 silent 하게 stub 키로 동작 — 절대
변경 금지.

키 함수: Caddy 리버스 프록시 뒤라 모든 요청이 동일 컨테이너 IP 로 보임.
`X-Forwarded-For` 의 *마지막* IP (Caddy 가 가장 마지막에 추가한 신뢰 IP) 를
사용. 클라이언트가 `X-Forwarded-For: 1.2.3.4` 를 위조해 보내도 Caddy 가 자기
관찰 IP 를 끝에 append 하므로 위조값은 무시됨. 헤더가 없으면
`request.client.host` (Docker 네트워크 컨테이너 IP) fallback.

운영 인프라 가정: 단일 Caddy → 백엔드. 다단 프록시 (CDN→Caddy) 추가 시 신뢰
범위 재검토 필요.
"""

import logging

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

_logger = logging.getLogger(__name__)


def _is_printable_ascii(value: str) -> bool:
    """IP 후보 문자열이 printable ASCII (32-126) 만 포함하는지.

    rate-limit 키 분리 우회 방어 — `\\x00`/`\\x01` 등 제어문자가 포함되면
    `.strip()` 으로 제거되지 않아 동일 IP 가 다른 키로 갈라진다.
    IPv4/IPv6 (콜론·점·hex) 는 모두 printable 범위이므로 false-rejection 없음.
    """
    return bool(value) and all(32 <= ord(c) < 127 for c in value)


def _client_key(request: Request) -> str:
    """원본 클라이언트 IP — X-Forwarded-For 마지막 IP 우선, fallback request.client.host.

    위조 방어: split(',')[-1] 로 가장 마지막 IP 만 사용. Caddy 가 자기 관찰
    IP 를 끝에 append 하므로, 클라이언트가 헤더 첫 부분을 위조해도 무시됨.

    엣지케이스 처리:
    - 헤더 끝 trailing comma (`"1.2.3.4, "`) → 빈 문자열 → fallback
    - IPv6 bracket (`"[::1]"`) → strip 으로 정규화 (rate-limit 키 일관성)
    - 제어문자 포함 (`"10.0.0.1\\x00"`) → printable ASCII 검증 → fallback
    - request.client 가 .host 속성 누락 (테스트 mock 등) → getattr 안전 접근
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        last_ip = forwarded.split(",")[-1].strip().strip("[]")
        if _is_printable_ascii(last_ip):
            return last_ip
    if request.client is not None:
        host = getattr(request.client, "host", None)
        if host:
            normalized = str(host).strip("[]")
            if _is_printable_ascii(normalized):
                return normalized
    return "unknown"


# 단일 프로세스 in-memory storage. 운영 docker-compose 의 WEB_CONCURRENCY=1 전제.
# 멀티 워커/멀티 VM 확장 시 Redis storage 로 전환 필요:
#   storage_uri="redis://..."
# config_filename="" : slowapi 가 .env 파일을 시스템 인코딩으로 읽으려다
# Windows(cp949) 에서 UnicodeDecodeError 발생하는 것을 방지.
limiter = Limiter(
    key_func=_client_key, default_limits=[], storage_uri="memory://", config_filename=""
)


# 사전 정의 정책 — 호출부에서 일관성 유지하기 위해 상수로 묶음.
RATE_LOGIN: str = "10/minute"  # 무차별 인증 시도 차단 (로그인/check-login)
RATE_SET_COOKIE: str = "30/minute"  # 자격증명 갱신 — 정상 사용량 충분 + 남용 방지
RATE_PROXY_HEAVY: str = "300/minute"  # 외부 사이트 호출 (수집/검색/카테고리 스캔)
RATE_PROXY_LIGHT: str = "1200/minute"  # 가벼운 메타·진단 — 확장앱 동시 폴링 허용


def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
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
    except (AttributeError, TypeError) as err:
        # slowapi/limits API 변경 가능 — 응답 자체는 정상 반환하되 가시화
        _logger.warning(f"[rate_limit] Retry-After 계산 실패: {err}")
    return response
