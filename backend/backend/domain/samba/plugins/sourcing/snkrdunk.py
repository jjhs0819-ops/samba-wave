"""SNKRDUNK(스니덩크) 소싱처 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class SnkrdunkPlugin(SourcingPlugin):
    """SNKRDUNK 소싱처 플러그인.

    백엔드 HTTP 직접 호출. 일본 리셀 플랫폼이라 보수적 운영.
    concurrency=2: 차단 방지 보수값
    request_interval=1.0: 1초 간격
    """

    site_name = "SNKRDUNK"
    concurrency = 2
    request_interval = 1.0

    async def search(self, keyword: str, **filters) -> list[dict]:
        """SNKRDUNK 키워드 검색."""
        from backend.domain.samba.proxy.snkrdunk import SnkrdunkClient

        max_count = int(filters.get("max_count", 100))
        client = SnkrdunkClient()
        result = await self.safe_call(client.search(keyword, max_count=max_count))
        return result.get("products", [])

    async def get_detail(self, site_product_id: str) -> dict:
        """SNKRDUNK 상품 상세 조회."""
        from backend.domain.samba.proxy.snkrdunk import SnkrdunkClient

        client = SnkrdunkClient()
        return await self.safe_call(client.get_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — 상세 재조회 후 변경분 반환."""
        from backend.domain.samba.collector.refresher import (
            RefreshResult,
            count_stock_transitions,
        )
        from backend.domain.samba.proxy.snkrdunk import SnkrdunkClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "")
        extra = getattr(product, "extra_data", None) or {}
        snkr_type = extra.get("snkr_type") if isinstance(extra, dict) else None

        if not site_product_id:
            return RefreshResult(product_id=product_id, error="site_product_id 없음")

        try:
            client = SnkrdunkClient()
            fresh = await client.get_detail(site_product_id, snkr_type)
        except Exception as e:
            logger.warning(f"[SNKRDUNK] 갱신 실패 {site_product_id}: {e}")
            return RefreshResult(product_id=product_id, error=str(e))

        if fresh.get("error"):
            return RefreshResult(product_id=product_id, error=fresh["error"])

        new_sale_price = fresh.get("sale_price")
        new_original_price = fresh.get("original_price")
        new_options = fresh.get("options") or []

        old_sale_price = getattr(product, "sale_price", None)
        old_original_price = getattr(product, "original_price", None)

        price_changed = (
            new_sale_price is not None
            and new_sale_price != old_sale_price
            or new_original_price is not None
            and new_original_price != old_original_price
        )

        if not new_options:
            new_sale_status = "sold_out"
        elif all(opt.get("stock", 0) <= 0 for opt in new_options):
            new_sale_status = "sold_out"
        else:
            new_sale_status = "in_stock"

        old_options = getattr(product, "options", None) or []
        _stock_changes = count_stock_transitions(old_options, new_options)
        old_sale_status = getattr(product, "sale_status", "in_stock")
        stock_changed = _stock_changes > 0 or new_sale_status != old_sale_status

        return RefreshResult(
            product_id=product_id,
            new_sale_price=new_sale_price,
            new_original_price=new_original_price,
            new_sale_status=new_sale_status,
            new_options=new_options,
            changed=price_changed,
            stock_changed=stock_changed,
        )
