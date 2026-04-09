"""나이키 소싱처 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class NikePlugin(SourcingPlugin):
    """나이키 소싱처 플러그인.

    concurrency=3: 동시 3개 요청
    request_interval=0.5: 요청 간 500ms 딜레이 (차단 방지)
    """

    site_name = "NIKE"
    concurrency = 3
    request_interval = 0.5

    async def search(self, keyword: str, **filters) -> list[dict]:
        """나이키 키워드 검색."""
        from backend.domain.samba.proxy.nike import NikeClient

        max_count = int(filters.get("max_count", 100))
        client = NikeClient()
        result = await self.safe_call(client.search(keyword, max_count=max_count))
        return result.get("products", [])

    async def get_detail(self, site_product_id: str) -> dict:
        """나이키 상품 상세 조회."""
        from backend.domain.samba.proxy.nike import NikeClient

        client = NikeClient()
        return await self.safe_call(client.get_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — NikeClient로 재조회 후 변경분 반환."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.nike import NikeClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "")

        if not site_product_id:
            return RefreshResult(product_id=product_id, error="site_product_id 없음")

        try:
            client = NikeClient()
            fresh = await client.get_detail(site_product_id)
        except Exception as e:
            logger.warning(f"[Nike] 갱신 실패 {site_product_id}: {e}")
            return RefreshResult(product_id=product_id, error=str(e))

        if fresh.get("error"):
            return RefreshResult(product_id=product_id, error=fresh["error"])

        new_sale_price = fresh.get("sale_price")
        new_original_price = fresh.get("original_price")
        new_options = fresh.get("options")  # 사이즈 목록

        old_sale_price = getattr(product, "sale_price", None)
        old_original_price = getattr(product, "original_price", None)

        price_changed = (
            new_sale_price is not None
            and new_sale_price != old_sale_price
            or new_original_price is not None
            and new_original_price != old_original_price
        )
        # 재고 품절 감지: 사이즈 옵션이 비어있으면 품절
        new_sale_status = "sold_out" if new_options == [] else "in_stock"
        stock_changed = new_sale_status == "sold_out"

        return RefreshResult(
            product_id=product_id,
            new_sale_price=new_sale_price,
            new_original_price=new_original_price,
            new_sale_status=new_sale_status,
            new_options=new_options,
            changed=price_changed,
            stock_changed=stock_changed,
        )
