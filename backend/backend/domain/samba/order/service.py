"""SambaWave Order service."""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from backend.domain.samba.order.model import SambaOrder
from backend.domain.samba.order.repository import SambaOrderRepository


class SambaOrderService:
    def __init__(self, repo: SambaOrderRepository):
        self.repo = repo

    async def list_orders(
        self, skip: int = 0, limit: int = 50, status: Optional[str] = None
    ) -> List[SambaOrder]:
        if status:
            return await self.repo.list_by_status(status)
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def get_order(self, order_id: str) -> Optional[SambaOrder]:
        return await self.repo.get_async(order_id)

    async def create_order(self, data: Dict[str, Any]) -> SambaOrder:
        sale_price = float(data.get("sale_price", 0))
        cost = float(data.get("cost", 0))
        fee_rate = float(data.get("fee_rate", 0))

        revenue = data.get("revenue") or (sale_price * (1 - fee_rate / 100))
        profit = revenue - cost
        profit_rate = f"{(profit / revenue * 100):.2f}" if revenue > 0 else "0.00"

        data["revenue"] = revenue
        data["profit"] = profit
        data["profit_rate"] = profit_rate

        return await self.repo.create_async(**data)

    async def update_order(
        self, order_id: str, data: Dict[str, Any]
    ) -> Optional[SambaOrder]:
        return await self.repo.update_async(order_id, **data)

    async def update_order_status(
        self, order_id: str, new_status: str
    ) -> Optional[SambaOrder]:
        updates: Dict[str, Any] = {"status": new_status}
        now = datetime.now(UTC)

        if new_status == "shipped":
            updates["shipped_at"] = now
            updates["shipping_status"] = "shipped"
        elif new_status == "delivered":
            updates["delivered_at"] = now
            updates["shipping_status"] = "delivered"

        return await self.repo.update_async(order_id, **updates)

    async def delete_order(self, order_id: str) -> bool:
        return await self.repo.delete_async(order_id)

    async def search_orders(self, query: str) -> List[SambaOrder]:
        return await self.repo.search(query)
