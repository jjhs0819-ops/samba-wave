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
        self._sanitize_kream_data(data)
        self._fill_optional_images(data)
        return await self.product_repo.create_async(**data)

    async def update_collected_product(
        self, product_id: str, data: Dict[str, Any]
    ) -> Optional[SambaCollectedProduct]:
        self._sanitize_kream_data(data)
        self._fill_optional_images(data)
        # tags가 None으로 전달되면 기존 태그를 덮어쓰지 않도록 제거
        # (명시적으로 빈 리스트 []를 보내면 태그 초기화 허용)
        if "tags" in data and data["tags"] is None:
            del data["tags"]
        return await self.product_repo.update_async(product_id, **data)

    @staticmethod
    def _sanitize_kream_data(data: Dict[str, Any]) -> None:
        """비-KREAM 상품의 kream_data 오염 방지.

        확장앱이 무신사 고시정보를 kream_data로 보내는 경우,
        올바른 필드(material, color 등)로 분리하고 kream_data를 제거한다.
        """
        if data.get("source_site") == "KREAM":
            return
        kd = data.get("kream_data")
        if not isinstance(kd, dict):
            return
        field_map = {
            "color": "color",
            "material": "material",
            "brandNation": "origin",
        }
        for kd_key, field in field_map.items():
            if kd.get(kd_key) and not data.get(field):
                data[field] = kd[kd_key]
        data.pop("kream_data", None)

    @staticmethod
    def _fill_optional_images(data: Dict[str, Any]) -> None:
        """추가이미지가 부족하면 상세이미지로 보충 (최대 9장)."""
        images = data.get("images")
        detail_images = data.get("detail_images")
        if not isinstance(images, list) or not isinstance(detail_images, list):
            return
        if len(images) >= 9:
            return
        existing = set(images)
        for di in detail_images:
            if di not in existing and len(images) < 9:
                images.append(di)
                existing.add(di)
        data["images"] = images

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
