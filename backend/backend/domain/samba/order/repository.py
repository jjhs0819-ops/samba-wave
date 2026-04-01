"""SambaWave Order repository."""

from typing import List

from sqlalchemy import or_
from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.order.model import SambaOrder


class SambaOrderRepository(BaseRepository[SambaOrder]):
    def __init__(self, session):
        super().__init__(session, SambaOrder)

    async def search(self, query: str) -> List[SambaOrder]:
        lower_q = f"%{query.lower()}%"
        stmt = (
            select(SambaOrder)
            .where(
                or_(
                    SambaOrder.order_number.ilike(lower_q),
                    SambaOrder.customer_name.ilike(lower_q),
                    SambaOrder.customer_phone.ilike(lower_q),
                    SambaOrder.product_name.ilike(lower_q),
                )
            )
            .order_by(SambaOrder.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_status(self, status: str) -> List[SambaOrder]:
        return await self.filter_by_async(
            status=status, order_by="created_at", order_by_desc=True
        )

    async def list_by_channel(self, channel_id: str) -> List[SambaOrder]:
        return await self.filter_by_async(
            channel_id=channel_id, order_by="created_at", order_by_desc=True
        )

    async def list_by_date_range(
        self, start_date: str, end_date: str
    ) -> List[SambaOrder]:
        stmt = (
            select(SambaOrder)
            .where(
                SambaOrder.created_at >= start_date,
                SambaOrder.created_at <= end_date,
            )
            .order_by(SambaOrder.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
