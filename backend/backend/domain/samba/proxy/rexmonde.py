"""REXMONDE(www.rexmonde.com) 소싱 API 클라이언트.

OK몰은 공식 API를 제공하지 않으므로 SSR HTML을 BeautifulSoup으로 파싱한다.
검색·카테고리 페이지·상품 상세 페이지를 다룬다.
"""

import logging

logger = logging.getLogger(__name__)


class RexmondeClient:
    """렉스몬드 HTTP 클라이언트 + HTML 파서 (스켈레톤)."""

    BASE = "https://www.rexmonde.com"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.rexmonde.com/",
    }

    async def search_products(
        self, keyword: str, page: int = 1, size: int = 80, **kwargs
    ) -> list[dict]:
        """검색·카테고리 페이지 HTML 파싱 — 본격 구현 예정."""
        return []

    async def get_product_detail(self, site_product_id: str) -> dict:
        """상품 상세 페이지 JSON-LD + 정보고시 파싱 — 본격 구현 예정."""
        return {}

    async def scan_categories(
        self, keyword: str, pages: int = 3, **kwargs
    ) -> dict:
        """카테고리 코드 분포 집계 — 본격 구현 예정."""
        return {"categories": [], "total": 0, "groupCount": 0}
