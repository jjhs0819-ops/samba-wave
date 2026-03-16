"""SambaWave Return repository."""

from typing import List

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.returns.model import SambaReturn


class SambaReturnRepository(BaseRepository[SambaReturn]):
    def __init__(self, session):
        super().__init__(session, SambaReturn)

    async def list_by_order(self, order_id: str) -> List[SambaReturn]:
        return await self.filter_by_async(
            order_id=order_id, order_by="created_at", order_by_desc=True
        )

    async def list_by_status(self, status: str) -> List[SambaReturn]:
        return await self.filter_by_async(
            status=status, order_by="created_at", order_by_desc=True
        )

    async def list_by_type(self, type: str) -> List[SambaReturn]:
        return await self.filter_by_async(
            type=type, order_by="created_at", order_by_desc=True
        )
