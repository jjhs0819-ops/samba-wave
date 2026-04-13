"""SambaWave Return repository."""

from datetime import datetime
from typing import List, Optional

from sqlmodel import select

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

    async def list_filtered(
        self,
        skip: int = 0,
        limit: int = 500,
        order_id: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
    ) -> List[SambaReturn]:
        """필터 + 날짜 범위 목록 조회."""
        stmt = select(SambaReturn)
        if order_id:
            stmt = stmt.where(SambaReturn.order_id == order_id)
        if status:
            stmt = stmt.where(SambaReturn.status == status)
        if type:
            stmt = stmt.where(SambaReturn.type == type)
        if start_dt:
            stmt = stmt.where(SambaReturn.created_at >= start_dt)
        if end_dt:
            stmt = stmt.where(SambaReturn.created_at <= end_dt)
        stmt = stmt.order_by(SambaReturn.created_at.desc())
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
