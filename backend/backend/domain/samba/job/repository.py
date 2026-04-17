"""작업 큐 리포지토리."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.shared.base_repository import BaseRepository
from .model import JobStatus, SambaJob

UTC = timezone.utc


class SambaJobRepository(BaseRepository[SambaJob]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, SambaJob)

    # ── 원자적 잡 획득 (멀티 worker race condition 방지) ──

    async def claim_pending_job(
        self,
        exclude_types: set[str] | None = None,
    ) -> Optional[SambaJob]:
        """Pending 잡 1개를 원자적으로 claim (FOR UPDATE SKIP LOCKED).

        다른 worker가 이미 lock 잡은 row는 건너뛰므로 중복 실행 불가.
        write session 컨텍스트 안에서 호출해야 하며, 호출부에서 commit() 필요.
        """
        stmt = (
            select(SambaJob)
            .where(SambaJob.status == JobStatus.PENDING)
            .order_by(SambaJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if exclude_types:
            stmt = stmt.where(SambaJob.job_type.notin_(list(exclude_types)))

        result = await self.session.execute(stmt)
        job = result.scalars().first()
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(UTC)
            self.session.add(job)
            await self.session.flush()
        return job

    # ── 레거시 메서드 (하위 호환용, 다른 호출부가 있을 수 있음) ──

    async def pick_next_pending(self) -> Optional[SambaJob]:
        """가장 오래된 pending 잡 1개를 running으로 변경 후 반환.

        [DEPRECATED] claim_pending_job()을 사용하세요 — FOR UPDATE SKIP LOCKED 적용.
        """
        stmt = (
            select(SambaJob)
            .where(SambaJob.status == JobStatus.PENDING)
            .order_by(SambaJob.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        job = result.scalars().first()
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(UTC)
            self.session.add(job)
            await self.session.flush()
        return job

    async def list_pending(self, limit: int = 5) -> list[SambaJob]:
        """pending 잡을 오래된 순으로 조회 (running 변경 포함).

        [DEPRECATED] claim_pending_job()을 사용하세요 — FOR UPDATE SKIP LOCKED 적용.
        """
        stmt = (
            select(SambaJob)
            .where(SambaJob.status == JobStatus.PENDING)
            .order_by(SambaJob.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = JobStatus.RUNNING
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
        """잡 완료 처리 — attempt 리셋 포함."""
        job = await self.get_async(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.progress = 100
            job.attempt = 0  # 성공 → attempt 리셋
            job.completed_at = datetime.now(UTC)
            if result:
                job.result = result
            self.session.add(job)
            await self.session.flush()

    async def fail_job(self, job_id: str, error: str):
        """잡 실패 처리."""
        job = await self.get_async(job_id)
        if job:
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(UTC)
            self.session.add(job)
            await self.session.flush()

    async def cancel_job(self, job_id: str) -> bool:
        """잡 취소 (pending/running 모두 가능)."""
        job = await self.get_async(job_id)
        if not job or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        self.session.add(job)
        await self.session.flush()
        return True

    async def is_cancelled(self, job_id: str) -> bool:
        """잡이 취소 상태인지 확인 (워커에서 건별 체크용).
        완전히 새 세션으로 조회 — 워커 세션 오염 방지 + ORM 캐시 우회.
        타임아웃/DB 에러 시 False 반환 (안전 우선 — 전송/수집 계속)."""
        import asyncio
        from sqlalchemy import text
        from backend.db.orm import get_write_session

        try:
            async with get_write_session() as fresh_session:
                result = await asyncio.wait_for(
                    fresh_session.execute(
                        text("SELECT status FROM samba_jobs WHERE id = :id"),
                        {"id": job_id},
                    ),
                    timeout=5,
                )
                row = result.first()
                return row[0] == JobStatus.CANCELLED if row else False
        except (asyncio.TimeoutError, Exception):
            return False

    async def recover_stuck_running(
        self,
        exclude_ids: set[str] | None = None,
        threshold_sec: int = 0,
    ) -> int:
        """stuck된 running 잡을 pending으로 복구.

        FOR UPDATE SKIP LOCKED 적용 — 다른 worker가 처리 중인 잡은 건너뜀.

        exclude_ids: 현재 워커가 실행 중인 잡 ID 제외
        threshold_sec: >0이면 started_at 기준 N초 이상 경과한 잡만 복구
        """
        from datetime import timedelta

        from sqlalchemy import and_

        conditions = [SambaJob.status == JobStatus.RUNNING]
        if exclude_ids:
            conditions.append(SambaJob.id.notin_(list(exclude_ids)))
        if threshold_sec > 0:
            cutoff = datetime.now(UTC) - timedelta(seconds=threshold_sec)
            conditions.append(SambaJob.started_at < cutoff)

        # FOR UPDATE SKIP LOCKED — 다른 worker가 lock 잡은 running 잡은 skip
        stmt = (
            select(SambaJob).where(and_(*conditions)).with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        stuck = list(result.scalars().all())
        for job in stuck:
            job.status = JobStatus.PENDING
            job.started_at = None
            # current/progress 보존 — 전송 잡이 이어서 재개할 수 있도록
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
