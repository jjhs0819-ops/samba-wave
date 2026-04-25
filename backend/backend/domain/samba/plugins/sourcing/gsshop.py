"""GS샵 소싱처 플러그인.

GS샵은 TV홈쇼핑 기반 쇼핑몰로, 봇 차단이 강하므로
보수적 간격(concurrency=1, interval=1.0)으로 요청한다.
bestBenefitPrice(최대혜택가)를 new_cost에 반영하여
정책 적용 시 실질 매입가 기준으로 마진 계산이 가능하다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class GsShopSourcingPlugin(SourcingPlugin):
    """GS샵 소싱처 플러그인.

    concurrency=3: 프록시 로테이션 분산 (worker에서 proxy_pool 전달)
    request_interval=0.5: 요청 간 0.5초 딜레이
    """

    site_name = "GSSHOP"
    concurrency = 3
    request_interval = 0.5

    async def search(self, keyword: str, **filters) -> list[dict]:
        """GS샵 키워드 검색 — GsShopSourcingClient 경유 (올바른 URL 사용)."""
        from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient

        size = filters.get("size", 40)
        url = filters.get("url", "")  # 그룹 link URL
        client = GsShopSourcingClient()
        return await client.search_products(keyword, size=size, url=url)

    async def scan_categories(self, keyword: str, **kwargs: object) -> dict:
        """GS샵 카테고리 스캔 — 백화점 탭 사이드바 카테고리 분포 조회."""
        from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient

        client = GsShopSourcingClient()
        return await client.scan_categories(keyword)

    async def get_detail(self, site_product_id: str) -> dict:
        """GS샵 상품 상세 조회."""
        from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient

        client = GsShopSourcingClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — 상세 페이지 재조회로 최신 데이터 추출."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="GS샵 상품 ID 없음",
            )

        try:
            client = GsShopSourcingClient()
            detail = await self.safe_call(
                client.get_product_detail(site_product_id, refresh_only=True)
            )

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"GS샵 상세 조회 실패: {site_product_id}",
                )

            new_sale_price = detail.get("salePrice", 0)
            new_original_price = detail.get("originalPrice", 0)
            is_sold_out = detail.get("isOutOfStock", False) or detail.get(
                "isSoldOut", False
            )

            # bestBenefitPrice → new_cost (실질 매입가)
            best_benefit_price = detail.get("bestBenefitPrice", 0)

            # 옵션 데이터 변환
            new_options = None
            raw_options = detail.get("options", [])
            if raw_options:
                new_options = [
                    {
                        "name": opt.get("name", ""),
                        "price": opt.get("price", 0),
                        "stock": 0
                        if opt.get("isSoldOut")
                        else (opt.get("stock") or 99),
                        "isSoldOut": opt.get("isSoldOut", False),
                    }
                    for opt in raw_options
                ]

            from backend.domain.samba.collector.refresher import (
                count_stock_transitions,
            )

            old_options_gs = getattr(product, "options", None) or []
            _stock_changes = count_stock_transitions(old_options_gs, new_options or [])
            old_sale = getattr(product, "sale_price", 0) or 0
            old_status = getattr(product, "sale_status", "in_stock")
            new_sale_status = "sold_out" if is_sold_out else "in_stock"
            changed = (float(new_sale_price or 0) != float(old_sale or 0)) or (
                new_sale_status != old_status
            )

            return RefreshResult(
                product_id=product_id,
                new_sale_price=float(new_sale_price) if new_sale_price else None,
                new_original_price=(
                    float(new_original_price) if new_original_price else None
                ),
                new_cost=float(best_benefit_price) if best_benefit_price else None,
                new_sale_status=new_sale_status,
                new_options=new_options,
                new_images=detail.get("images"),
                new_detail_images=detail.get("detailImages"),
                new_free_shipping=detail.get("freeShipping"),
                new_same_day_delivery=detail.get("sameDayDelivery"),
                changed=changed,
                stock_changed=_stock_changes > 0,
            )

        except Exception as e:
            logger.error(f"[GSSHOP] 갱신 실패: {site_product_id} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"GS샵 갱신 실패: {e}",
            )
