"""KREAM 소싱처 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class KreamPlugin(SourcingPlugin):
    """KREAM 소싱처 플러그인.

    확장앱 큐 방식으로 수집/갱신.
    concurrency=3: 확장앱 큐 병렬 처리
    """

    site_name = "KREAM"
    concurrency = 3
    request_interval = 0

    async def search(self, keyword: str, **filters) -> list[dict]:
        """KREAM 키워드 검색 — 확장앱 큐 방식."""
        from backend.domain.samba.proxy.kream import KreamClient

        client = KreamClient()
        return await client.search_products(keyword)

    async def get_detail(self, site_product_id: str) -> dict:
        """KREAM 상품 상세 조회 — 확장앱 큐 대기."""
        from backend.domain.samba.proxy.kream import KreamClient

        client = KreamClient()
        return await client.get_product_detail(site_product_id)

    async def scan_categories(self, keyword: str, **kwargs: object) -> dict:
        """KREAM 카테고리 스캔 — 검색 결과에서 카테고리 분포 집계."""
        from backend.domain.samba.proxy.kream import KreamClient

        client = KreamClient()
        return await client.scan_categories(keyword)

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — 기존 _parse_kream 위임."""
        from backend.domain.samba.collector.refresher import _parse_kream

        return await _parse_kream(product)
