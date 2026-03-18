"""SambaWave Collector service."""

from typing import Any, Dict, List, Optional

from backend.domain.samba.collector.model import SambaCollectedProduct, SambaSearchFilter
from backend.domain.samba.collector.repository import (
    SambaCollectedProductRepository,
    SambaSearchFilterRepository,
)


class SambaCollectorService:
    def __init__(
        self,
        filter_repo: SambaSearchFilterRepository,
        product_repo: SambaCollectedProductRepository,
    ):
        self.filter_repo = filter_repo
        self.product_repo = product_repo

    # ==================== Search Filters ====================

    async def list_filters(
        self, skip: int = 0, limit: int = 50
    ) -> List[SambaSearchFilter]:
        return await self.filter_repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def create_filter(self, data: Dict[str, Any]) -> SambaSearchFilter:
        return await self.filter_repo.create_async(**data)

    async def update_filter(
        self, filter_id: str, data: Dict[str, Any]
    ) -> Optional[SambaSearchFilter]:
        return await self.filter_repo.update_async(filter_id, **data)

    async def delete_filter(self, filter_id: str) -> bool:
        return await self.filter_repo.delete_async(filter_id)

    # ==================== Collected Products ====================

    async def list_collected_products(
        self,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        source_site: Optional[str] = None,
    ) -> List[SambaCollectedProduct]:
        if status and source_site:
            return await self.product_repo.list_by_filters(
                status=status, source_site=source_site
            )
        if status:
            return await self.product_repo.list_by_status(status)
        if source_site:
            return await self.product_repo.list_by_filters(source_site=source_site)
        return await self.product_repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def get_collected_product(
        self, product_id: str
    ) -> Optional[SambaCollectedProduct]:
        return await self.product_repo.get_async(product_id)

    async def create_collected_product(
        self, data: Dict[str, Any]
    ) -> SambaCollectedProduct:
        return await self.product_repo.create_async(**data)

    async def update_collected_product(
        self, product_id: str, data: Dict[str, Any]
    ) -> Optional[SambaCollectedProduct]:
        return await self.product_repo.update_async(product_id, **data)

    async def delete_collected_product(self, product_id: str) -> bool:
        return await self.product_repo.delete_async(product_id)

    async def search_collected_products(
        self, query: str, limit: int = 100
    ) -> List[SambaCollectedProduct]:
        return await self.product_repo.search(query, limit)

    async def bulk_create_collected_products(
        self, items: List[Dict[str, Any]]
    ) -> List[SambaCollectedProduct]:
        return await self.product_repo.bulk_create_async(items)

    async def apply_policy_to_filter_products(
        self, filter_id: str, policy_id: str, policy_data: Optional[Dict[str, Any]] = None
    ) -> int:
        """그룹(필터)에 적용된 정책을 해당 그룹의 모든 상품에 전파."""
        products = await self.product_repo.list_by_filter(filter_id)
        updated = 0
        for p in products:
            update_data: Dict[str, Any] = {"applied_policy_id": policy_id}
            # 정책 데이터가 있으면 market_prices 계산
            if policy_data:
                margin = policy_data.get("margin_rate", 15) / 100
                shipping = policy_data.get("shipping_cost", 0)
                extra = policy_data.get("extra_charge", 0)
                base = p.sale_price or p.original_price or 0
                calculated = int(base * (1 + margin) + shipping + extra)
                update_data["market_prices"] = {"default": calculated}
            await self.product_repo.update_async(p.id, **update_data)
            updated += 1
        return updated
