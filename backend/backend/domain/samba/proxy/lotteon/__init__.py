"""롯데ON 소싱용 웹 스크래핑 클라이언트 패키지.

하위 호환성을 위해 LotteonSourcingClient, RateLimitError, set_lotteon_cookie,
_lotteon_cookie_cache, _filter_by_brands, _LOTTEON_SCAT_NAMES 를 모두 re-export한다.
"""

from __future__ import annotations

import httpx

from backend.domain.samba.proxy.lotteon.category_map import _LOTTEON_SCAT_NAMES
from backend.domain.samba.proxy.lotteon.detail_client import (
    DetailClientMixin,
    _lotteon_cookie_cache,
    set_lotteon_cookie,
)
from backend.domain.samba.proxy.lotteon.detail_parsers import DetailParsersMixin
from backend.domain.samba.proxy.lotteon.search_client import (
    RateLimitError,
    SearchClientMixin,
)
from backend.domain.samba.proxy.lotteon.search_parsers import SearchParsersMixin


def _filter_by_brands(items: list[dict], selected_brands: list[str]) -> list[dict]:
    """브랜드 필터링 — 선택된 브랜드 목록에 정확 일치하는 상품만 반환.

    공백 정규화 후 비교하여 "나이키 골프"와 "나이키골프"를 동일하게 처리.
    selected_brands가 비어있으면 필터링 없이 전체 반환.
    """
    if not items or not selected_brands:
        return items

    brand_set = {b.replace(" ", "").strip() for b in selected_brands if b}
    if not brand_set:
        return items

    return [
        it
        for it in items
        if (it.get("brand") or "").replace(" ", "").strip() in brand_set
    ]


class LotteonSourcingClient(
    SearchParsersMixin,
    SearchClientMixin,
    DetailParsersMixin,
    DetailClientMixin,
):
    """롯데ON 소싱용 웹 스크래핑 클라이언트 (검색, 상세).

    롯데ON 상품 페이지를 HTML 파싱하여 상품 검색/상세 정보를 추출한다.
    JSON-LD(schema.org Product) 마크업을 우선 파싱하고,
    없으면 __NEXT_DATA__ 또는 메타 태그에서 폴백한다.
    """

    BASE = "https://www.lotteon.com"
    SEARCH_URL = "https://www.lotteon.com/csearch/search/search"
    PRODUCT_URL = "https://www.lotteon.com/p/product"
    IMAGE_CDN = "contents.lotteon.com"
    PBF_BASE = "https://pbf.lotteon.com"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.lotteon.com/",
    }

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(20.0, connect=10.0)

    def _timeout_obj(self) -> httpx.Timeout:
        """타임아웃 객체 반환."""
        return self._timeout


__all__ = [
    "LotteonSourcingClient",
    "RateLimitError",
    "set_lotteon_cookie",
    "_lotteon_cookie_cache",
    "_filter_by_brands",
    "_LOTTEON_SCAT_NAMES",
]
