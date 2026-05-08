"""SambaWave Order repository."""

from typing import List

from sqlalchemy import func, or_
from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.order.model import SambaOrder


class SambaOrderRepository(BaseRepository[SambaOrder]):
    def __init__(self, session):
        super().__init__(session, SambaOrder)

    async def search(self, query: str) -> List[SambaOrder]:
        from backend.core.sql_safe import escape_like

        lower_q = f"%{escape_like(query.lower())}%"
        stmt = (
            select(SambaOrder)
            .where(
                or_(
                    SambaOrder.order_number.ilike(lower_q, escape="\\"),
                    SambaOrder.customer_name.ilike(lower_q, escape="\\"),
                    SambaOrder.customer_phone.ilike(lower_q, escape="\\"),
                    SambaOrder.product_name.ilike(lower_q, escape="\\"),
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
        # 고객결제일(paid_at) 기준, 없으면 created_at fallback
        date_col = func.coalesce(SambaOrder.paid_at, SambaOrder.created_at)
        stmt = (
            select(SambaOrder)
            .where(
                date_col >= start_date,
                date_col <= end_date,
            )
            .order_by(date_col.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
