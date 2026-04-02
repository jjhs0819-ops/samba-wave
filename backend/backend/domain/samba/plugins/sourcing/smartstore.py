"""스마트스토어 소싱처 플러그인."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class SmartStorePlugin(SourcingPlugin):
    """스마트스토어/네이버쇼핑 소싱처 플러그인.

    네이버 쇼핑 검색 API를 활용한 상품 검색과
    스마트스토어 상품 페이지 HTML 파싱을 통한 상세 조회를 제공한다.

    concurrency=3: 네이버 API는 비교적 안정적이므로 병렬 3개
    request_interval=0.3: 요청 간 300ms 딜레이
    """

    site_name = "SMARTSTORE"
    concurrency = 3
    request_interval = 0.3

    async def search(self, keyword: str, **filters) -> list[dict]:
        """스마트스토어 키워드 검색 (네이버 쇼핑 API)."""
        from backend.domain.samba.proxy.smartstore_sourcing import (
            SmartStoreSourcingClient,
        )

        client = SmartStoreSourcingClient()
        page = filters.get("page", 1)
        size = filters.get("size", 40)
        sort = filters.get("sort", "sim")
        return await self.safe_call(
            client.search_products(keyword, page=page, size=size, sort=sort)
        )

    async def get_detail(self, site_product_id: str) -> dict:
        """스마트스토어 상품 상세 조회."""
        from backend.domain.samba.proxy.smartstore_sourcing import (
            SmartStoreSourcingClient,
        )

        client = SmartStoreSourcingClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — 상세 페이지 재조회로 최신 데이터 추출."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.smartstore_sourcing import (
            SmartStoreSourcingClient,
        )

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )
        source_url = getattr(product, "source_url", "") or getattr(
            product, "sourceUrl", ""
        )

        # URL이 있으면 URL로, 없으면 ID로 조회
        lookup_key = source_url if source_url else site_product_id
        if not lookup_key:
            return RefreshResult(
                product_id=product_id,
                error="스마트스토어 상품 ID/URL 없음",
            )

        try:
            client = SmartStoreSourcingClient()
            detail = await self.safe_call(client.get_product_detail(lookup_key))

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"스마트스토어 상세 조회 실패: {lookup_key}",
                )

            new_sale_price = detail.get("salePrice", 0)
            new_original_price = detail.get("originalPrice", 0)
            is_sold_out = detail.get("isSoldOut", False)

            # 옵션 데이터 변환
            new_options = None
            raw_options = detail.get("options", [])
            if raw_options:
                new_options = [
                    {
                        "name": opt.get("name", ""),
                        "price": opt.get("price", 0),
                        "stock": opt.get("stock", 0),
                        "isSoldOut": opt.get("isSoldOut", False),
                    }
                    for opt in raw_options
                ]

            return RefreshResult(
                product_id=product_id,
                new_sale_price=float(new_sale_price) if new_sale_price else None,
                new_original_price=float(new_original_price)
                if new_original_price
                else None,
                new_sale_status="sold_out" if is_sold_out else "in_stock",
                new_options=new_options,
                new_images=detail.get("images"),
                new_detail_images=detail.get("detailImages"),
                changed=True,
            )

        except Exception as e:
            logger.error(f"[SMARTSTORE] 갱신 실패: {lookup_key} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"스마트스토어 갱신 실패: {e}",
            )
