"""SambaWave Product service."""

import math
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from backend.domain.samba.product.model import SambaProduct
from backend.domain.samba.product.repository import SambaProductRepository


class SambaProductService:
    def __init__(self, repo: SambaProductRepository):
        self.repo = repo

    async def list_products(
        self, skip: int = 0, limit: int = 50, status: Optional[str] = None
    ) -> List[SambaProduct]:
        if status:
            return await self.repo.list_by_status(status)
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def get_product(self, product_id: str) -> Optional[SambaProduct]:
        return await self.repo.get_async(product_id)

    async def create_product(self, data: Dict[str, Any]) -> SambaProduct:
        return await self.repo.create_async(**data)

    async def update_product(
        self, product_id: str, data: Dict[str, Any]
    ) -> Optional[SambaProduct]:
        return await self.repo.update_async(product_id, **data)

    async def delete_product(self, product_id: str) -> bool:
        return await self.repo.delete_async(product_id)

    async def search_products(self, query: str, limit: int = 100) -> List[SambaProduct]:
        return await self.repo.search(query, limit)

    @staticmethod
    def calculate_channel_price(cost: float, margin_rate: float) -> int:
        if margin_rate >= 100:
            return math.ceil(cost * 2)
        return math.ceil(cost / (1 - margin_rate / 100))

    @staticmethod
    def calculate_profit(
        sale_price: float, cost: float, fee_rate: float
    ) -> Dict[str, float]:
        revenue = sale_price * (1 - fee_rate / 100)
        profit = revenue - cost
        profit_rate = round((profit / revenue) * 100, 2) if revenue > 0 else 0
        return {"revenue": revenue, "profit": profit, "profit_rate": profit_rate}

    async def track_price_change(
        self, product_id: str, current_price: float
    ) -> Optional[Dict[str, Any]]:
        product = await self.repo.get_async(product_id)
        if not product:
            return None

        price_change = current_price - product.source_price
        change_percent = (
            round((price_change / product.source_price) * 100, 2)
            if product.source_price
            else 0
        )

        await self.repo.update_async(
            product_id,
            price_before_change=product.source_price,
            source_price=current_price,
            price_changed_at=datetime.now(UTC),
        )

        return {"price_change": price_change, "change_percent": change_percent}
