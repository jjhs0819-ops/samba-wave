"""아디다스 소싱처 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class AdidasPlugin(SourcingPlugin):
    """아디다스 소싱처 플러그인.

    concurrency=3: 동시 3개 요청
    request_interval=0.5: 요청 간 500ms 딜레이
    """

    site_name = "ADIDAS"
    concurrency = 3
    request_interval = 0.5

    async def search(self, keyword: str, **filters) -> list[dict]:
        """아디다스 키워드 검색."""
        from backend.domain.samba.proxy.adidas import AdidasClient

        max_count = int(filters.get("max_count", 100))
        client = AdidasClient()
        result = await self.safe_call(client.search(keyword, max_count=max_count))
        return result.get("products", [])

    async def get_detail(self, site_product_id: str) -> dict:
        """아디다스 상품 상세 조회."""
        from backend.domain.samba.proxy.adidas import AdidasClient

        client = AdidasClient()
        return await self.safe_call(client.get_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — AdidasClient로 재조회 후 변경분 반환."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.adidas import AdidasClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "")

        if not site_product_id:
            return RefreshResult(product_id=product_id, error="site_product_id 없음")

        try:
            client = AdidasClient()
            fresh = await client.get_detail(site_product_id)
        except Exception as e:
            logger.warning(f"[Adidas] 갱신 실패 {site_product_id}: {e}")
            return RefreshResult(product_id=product_id, error=str(e))

        if not fresh or fresh.get("error"):
            return RefreshResult(
                product_id=product_id, error=fresh.get("error", "상세 조회 실패")
            )

        new_sale_price = fresh.get("sale_price")
        new_original_price = fresh.get("original_price")

        old_sale_price = getattr(product, "sale_price", None)

        price_changed = new_sale_price is not None and new_sale_price != old_sale_price

        new_options = fresh.get("options")
        new_sale_status = "in_stock"
        if new_options is not None and len(new_options) > 0:
            all_sold_out = all(
                o.get("isSoldOut", False) or o.get("stock", 0) == 0 for o in new_options
            )
            if all_sold_out:
                new_sale_status = "sold_out"

        # 옵션별 0 경계 전환을 stock_changed로 인정 — 일부 옵션만 품절/재입고된 경우도 감지
        from backend.domain.samba.collector.refresher import count_stock_transitions

        old_options = getattr(product, "options", None) or []
        _stock_changes = count_stock_transitions(old_options, new_options or [])
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
