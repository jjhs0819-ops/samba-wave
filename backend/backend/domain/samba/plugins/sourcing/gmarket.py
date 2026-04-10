"""지마켓 소싱처 플러그인."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class GMarketPlugin(SourcingPlugin):
    """지마켓 소싱처 플러그인.

    지마켓은 React SPA 기반으로 직접 크롤링이 어렵다.
    서버 렌더링 HTML의 초기 데이터를 파싱하며,
    필요 시 확장앱 큐 방식으로 전환할 수 있다.

    concurrency=1: 차단 강도가 높아 동시 1개만 요청
    request_interval=1.0: 요청 간 1초 딜레이 (보수적)
    """

    site_name = "GMARKET"
    concurrency = 1
    request_interval = 1.0

    async def search(self, keyword: str, **filters) -> list[dict]:
        """지마켓 키워드 검색."""
        from backend.domain.samba.proxy.gmarket import GMarketClient

        client = GMarketClient()
        page = filters.get("page", 1)
        size = filters.get("size", 40)
        return await self.safe_call(
            client.search_products(keyword, page=page, size=size, **filters)
        )

    async def get_detail(self, site_product_id: str) -> dict:
        """지마켓 상품 상세 조회."""
        from backend.domain.samba.proxy.gmarket import GMarketClient

        client = GMarketClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — 상세 페이지 재조회로 최신 데이터 추출."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.gmarket import GMarketClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="지마켓 상품 ID 없음",
            )

        try:
            client = GMarketClient()
            detail = await self.safe_call(client.get_product_detail(site_product_id))

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"지마켓 상세 조회 실패: {site_product_id}",
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
                        "price": opt.get("priceAdjust", 0),
                        "stock": 0 if opt.get("isSoldOut") else 99,
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
            logger.error(f"[GMARKET] 갱신 실패: {site_product_id} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"지마켓 갱신 실패: {e}",
            )
