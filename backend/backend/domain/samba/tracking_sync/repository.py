"""송장 자동전송 잡 repository."""

from typing import List, Optional

from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.tracking_sync.model import (
    STATUS_PENDING,
    STATUS_SCRAPED,
    SambaTrackingSyncJob,
)


class SambaTrackingSyncJobRepository(BaseRepository[SambaTrackingSyncJob]):
    def __init__(self, session):
        super().__init__(session, SambaTrackingSyncJob)

    async def get_by_request_id(
        self, request_id: str
    ) -> Optional[SambaTrackingSyncJob]:
        stmt = select(SambaTrackingSyncJob).where(
            SambaTrackingSyncJob.request_id == request_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_active_by_order_id(
        self, order_id: str
    ) -> Optional[SambaTrackingSyncJob]:
        # 가장 최근 잡 1건 — 동일 주문 중복 큐잉 방지
        stmt = (
            select(SambaTrackingSyncJob)
            .where(SambaTrackingSyncJob.order_id == order_id)
            .order_by(SambaTrackingSyncJob.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_pending(self, limit: int = 100) -> List[SambaTrackingSyncJob]:
        stmt = (
            select(SambaTrackingSyncJob)
            .where(SambaTrackingSyncJob.status == STATUS_PENDING)
            .order_by(SambaTrackingSyncJob.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_scraped_not_sent(
        self, limit: int = 100
    ) -> List[SambaTrackingSyncJob]:
        stmt = (
            select(SambaTrackingSyncJob)
            .where(SambaTrackingSyncJob.status == STATUS_SCRAPED)
            .order_by(SambaTrackingSyncJob.scraped_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
