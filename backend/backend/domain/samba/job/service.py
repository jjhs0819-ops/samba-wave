"""작업 큐 서비스."""

from .model import SambaJob
from .repository import SambaJobRepository


class SambaJobService:
    def __init__(self, repo: SambaJobRepository):
        self.repo = repo

    async def create_job(self, data: dict) -> SambaJob:
        """새 잡 생성."""
        return await self.repo.create_async(**data)

    async def get_job(self, job_id: str) -> SambaJob | None:
        """잡 조회."""
        return await self.repo.get_async(job_id)

    async def list_jobs(self, status: str | None = None, tenant_id: str | None = None, skip: int = 0, limit: int = 50):
        """잡 목록 조회."""
        return await self.repo.list_by_status(status, tenant_id, skip, limit)

    async def cancel_job(self, job_id: str) -> bool:
        """pending 상태의 잡 취소."""
        job = await self.repo.get_async(job_id)
        if job and job.status == "pending":
            await self.repo.update_async(job_id, status="failed", error="사용자 취소")
            return True
        return False
