"""REXMONDE(구 OK몰) 소싱처 플러그인.

명품 패션 사이트 www.rexmonde.com (구 OK몰).
검색·상세조회·갱신은 RexmondeClient에 위임한다.
"""

from __future__ import annotations

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
        """키워드 또는 카테고리 코드(5자리 이상 숫자)로 상품 검색."""
        from backend.domain.samba.proxy.rexmonde import RexmondeClient

        client = RexmondeClient()
        return await self.safe_call(client.search_products(keyword, **filters))

    async def get_detail(self, site_product_id: str) -> dict:
        """상품 상세 정보 조회."""
        from backend.domain.samba.proxy.rexmonde import RexmondeClient

        client = RexmondeClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """상품 가격·재고 정보 갱신.

        - 명시적 404(`__product_not_found__`) → sold_out + deleted_from_source=True
        - JSON-LD 미발견(빈 dict) → 일시 오류로 보고 재시도 가능 상태 유지
        - saleStatus="sold_out" → new_sale_status="sold_out" (cost는 갱신)
        - 정상 → new_sale_price·new_cost·new_name·new_brand·new_images 백필
        """
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.rexmonde import RexmondeClient

        product_id = getattr(product, "id", "") or ""
        site_product_id = getattr(product, "site_product_id", "") or ""

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="REXMONDE site_product_id 누락",
            )

        client = RexmondeClient()
        detail = await self.safe_call(client.get_product_detail(site_product_id))

        # 명시적 404 — 소싱처에서 상품이 삭제됨
        if detail.get("__product_not_found__"):
            return RefreshResult(
                product_id=product_id,
                new_sale_status="sold_out",
                deleted_from_source=True,
            )

        # JSON-LD 파싱 실패 등 일시 오류 — error만 기록하고 상태는 그대로
        if not detail:
            return RefreshResult(
                product_id=product_id,
                error="REXMONDE 상세 응답 파싱 실패",
            )

        sale_price = detail.get("sale_price") or 0
        sale_status = detail.get("saleStatus") or "in_stock"

        return RefreshResult(
            product_id=product_id,
            new_sale_price=float(sale_price) if sale_price else None,
            new_cost=float(sale_price) if sale_price else None,
            new_sale_status=sale_status,
            new_name=detail.get("name") or None,
            new_brand=detail.get("brand") or None,
            new_images=detail.get("gallery_images") or None,
        )
