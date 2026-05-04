"""REXMONDE(구 OK몰) 소싱처 플러그인.

명품 패션 사이트 www.rexmonde.com (구 OK몰).
검색·상세조회·갱신은 RexmondeClient에 위임한다.
"""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class RexmondePlugin(SourcingPlugin):
    """렉스몬드(구 OK몰) 소싱처 플러그인."""

    site_name = "REXMONDE"
    concurrency = 5
    request_interval = 0.3

    async def search(self, keyword: str, **filters) -> list[dict]:
        """키워드 또는 카테고리 코드로 상품 검색 — 본격 구현 예정."""
        from backend.domain.samba.proxy.rexmonde import RexmondeClient

        client = RexmondeClient()
        return await self.safe_call(client.search_products(keyword, **filters))

    async def get_detail(self, site_product_id: str) -> dict:
        """상품 상세 정보 조회 — 본격 구현 예정."""
        from backend.domain.samba.proxy.rexmonde import RexmondeClient

        client = RexmondeClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """상품 가격·재고 정보 갱신 — 본격 구현 예정."""
        from backend.domain.samba.collector.refresher import RefreshResult

        return RefreshResult(
            product_id=getattr(product, "id", ""),
            error="REXMONDE refresh 미구현 (스켈레톤)",
        )
