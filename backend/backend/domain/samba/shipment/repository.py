"""SambaWave Shipment repository."""

from typing import List

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.shipment.model import SambaShipment


class SambaShipmentRepository(BaseRepository[SambaShipment]):
    def __init__(self, session):
        super().__init__(session, SambaShipment)

    async def list_by_product(self, product_id: str) -> List[SambaShipment]:
        return await self.filter_by_async(
            product_id=product_id, order_by="created_at", order_by_desc=True
        )

    async def list_by_status(self, status: str) -> List[SambaShipment]:
        return await self.filter_by_async(
            status=status, order_by="created_at", order_by_desc=True
        )
