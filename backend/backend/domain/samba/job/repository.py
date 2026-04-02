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

    async def cancel_job(self, job_id: str) -> bool:
        """잡 취소 (pending/running 모두 가능)."""
        job = await self.get_async(job_id)
        if not job or job.status not in ("pending", "running"):
            return False
        job.status = "cancelled"
        job.completed_at = datetime.now(UTC)
        self.session.add(job)
        await self.session.flush()
        return True

    async def is_cancelled(self, job_id: str) -> bool:
        """잡이 취소 상태인지 확인 (워커에서 건별 체크용).
        Identity Map 우회: ORM select는 캐시된 객체를 반환하므로
        다른 세션(cancel-all)에서 변경한 status를 감지 못함 → raw SQL 사용.
        타임아웃/DB 에러 시 False 반환 (안전 우선 — 전송 계속)."""
        import asyncio
        from sqlalchemy import text

        try:
            result = await asyncio.wait_for(
                self.session.execute(
                    text("SELECT status FROM samba_jobs WHERE id = :id"),
                    {"id": job_id},
                ),
                timeout=5,
            )
            row = result.first()
            return row[0] == "cancelled" if row else False
        except (asyncio.TimeoutError, Exception):
            # DB 커넥션 문제 시 취소로 간주하지 않음 — 전송 계속
            return False

    async def recover_stuck_running(
        self,
        exclude_types: set[str] | None = None,
        threshold_sec: int = 0,
    ) -> int:
        """stuck된 running 잡을 pending으로 복구.

        exclude_types: 현재 워커가 실행 중인 타입은 제외
        threshold_sec: >0이면 started_at 기준 N초 이상 경과한 잡만 복구
        """
        from sqlalchemy import and_

        conditions = [SambaJob.status == "running"]
        if exclude_types:
            conditions.append(SambaJob.job_type.notin_(list(exclude_types)))
        if threshold_sec > 0:
            cutoff = datetime.now(UTC) - __import__("datetime").timedelta(
                seconds=threshold_sec
            )
            conditions.append(SambaJob.started_at < cutoff)
        stmt = select(SambaJob).where(and_(*conditions))
        result = await self.session.execute(stmt)
        stuck = list(result.scalars().all())
        for job in stuck:
            job.status = "pending"
            job.started_at = None
            job.progress = 0
            self.session.add(job)
        if stuck:
            await self.session.flush()
        return len(stuck)

    async def list_by_status(
        self,
        status: str | None = None,
        tenant_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ):
        """상태별 잡 목록."""
        stmt = select(SambaJob)
        if status:
            stmt = stmt.where(SambaJob.status == status)
        if tenant_id:
            stmt = stmt.where(SambaJob.tenant_id == tenant_id)
        stmt = stmt.order_by(SambaJob.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
