"""작업 큐 리포지토리."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.shared.base_repository import BaseRepository
from .model import SambaJob

UTC = timezone.utc


class SambaJobRepository(BaseRepository[SambaJob]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, SambaJob)

    async def pick_next_pending(self) -> Optional[SambaJob]:
        """가장 오래된 pending 잡 1개를 running으로 변경 후 반환."""
        stmt = (
            select(SambaJob)
            .where(SambaJob.status == "pending")
            .order_by(SambaJob.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        job = result.scalars().first()
        if job:
            job.status = "running"
            job.started_at = datetime.now(UTC)
            self.session.add(job)
            await self.session.flush()
        return job

    async def list_pending(self, limit: int = 5) -> list[SambaJob]:
        """pending 잡을 오래된 순으로 조회 (running 변경 포함)."""
        stmt = (
            select(SambaJob)
            .where(SambaJob.status == "pending")
            .order_by(SambaJob.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = "running"
            job.started_at = datetime.now(UTC)
            self.session.add(job)
        if jobs:
            await self.session.flush()
        return jobs

    async def update_progress(self, job_id: str, current: int, total: int):
        """진행률 업데이트."""
        job = await self.get_async(job_id)
        if job:
            job.current = current
            job.total = total
            job.progress = int((current / total) * 100) if total > 0 else 0
            self.session.add(job)
            await self.session.flush()

    async def complete_job(self, job_id: str, result: dict | None = None):
        """잡 완료 처리."""
        job = await self.get_async(job_id)
        if job:
            job.status = "completed"
            job.progress = 100
            job.completed_at = datetime.now(UTC)
            if result:
                job.result = result
            self.session.add(job)
            await self.session.flush()

    async def fail_job(self, job_id: str, error: str):
        """잡 실패 처리."""
        job = await self.get_async(job_id)
        if job:
            job.status = "failed"
            job.error = error
            job.completed_at = datetime.now(UTC)
            self.session.add(job)
            await self.session.flush()

    async def list_by_status(self, status: str | None = None, tenant_id: str | None = None, skip: int = 0, limit: int = 50):
        """상태별 잡 목록."""
        stmt = select(SambaJob)
        if status:
            stmt = stmt.where(SambaJob.status == status)
        if tenant_id:
            stmt = stmt.where(SambaJob.tenant_id == tenant_id)
        stmt = stmt.order_by(SambaJob.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
