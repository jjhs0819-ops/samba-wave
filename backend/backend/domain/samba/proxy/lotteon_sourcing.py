"""롯데ON 소싱용 웹 스크래핑 클라이언트 — 하위 호환 re-export.

실제 구현은 backend.domain.samba.proxy.lotteon 패키지로 이전되었다.
기존 import 경로를 유지하기 위한 shim 파일.
"""

from backend.domain.samba.proxy.lotteon import (  # noqa: F401
    LotteonSourcingClient,
    RateLimitError,
    _LOTTEON_SCAT_NAMES,
    _filter_by_brands,
    _lotteon_cookie_cache,
    set_lotteon_cookie,
)

__all__ = [
    "LotteonSourcingClient",
    "RateLimitError",
    "set_lotteon_cookie",
    "_lotteon_cookie_cache",
    "_filter_by_brands",
    "_LOTTEON_SCAT_NAMES",
]
