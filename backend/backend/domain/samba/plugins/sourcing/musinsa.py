"""무신사 소싱처 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class MusinsaPlugin(SourcingPlugin):
    """무신사 소싱처 플러그인.

    concurrency=1: Rate limit 대응 (동시 1개만)
    request_interval=0.2: 요청 간 200ms 딜레이
    """

    site_name = "MUSINSA"
    concurrency = 1
    request_interval = 0.2

    async def search(self, keyword: str, **filters) -> list[dict]:
        """무신사 키워드 검색."""
        from backend.domain.samba.proxy.musinsa import MusinsaClient

        client = MusinsaClient()
        return await self.safe_call(client.search_products(keyword, **filters))

    async def get_detail(self, site_product_id: str) -> dict:
        """무신사 상품 상세 조회."""
        from backend.domain.samba.proxy.musinsa import MusinsaClient

        client = MusinsaClient()
        return await self.safe_call(client.get_goods_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — refresher._parse_musinsa 로직 위임."""
        # 초기 단계: 기존 _parse_musinsa 함수에 위임 (동작 변경 없음)
        from backend.domain.samba.collector.refresher import _parse_musinsa

        return await _parse_musinsa(product)
