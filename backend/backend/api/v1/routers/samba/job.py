"""작업 큐 API."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.job.repository import SambaJobRepository
from backend.domain.samba.job.service import SambaJobService

router = APIRouter(prefix="/jobs", tags=["samba-jobs"])


class JobCreate(BaseModel):
    job_type: str  # transmit | collect | refresh | ai_tag
    payload: dict = {}
    tenant_id: Optional[str] = None


@router.post("", status_code=201)
async def create_job(
    body: JobCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """잡 생성 — 즉시 응답, 백그라운드 워커가 처리."""
    svc = SambaJobService(SambaJobRepository(session))

    # 같은 소싱처 수집 Job이 이미 실행 중이면 거부
    if body.job_type == "collect":
        source_site = body.payload.get("source_site", "")
        if source_site:
            from backend.domain.samba.job.model import SambaJob
            from sqlmodel import select, col
            running = (await session.execute(
                select(SambaJob).where(
                    SambaJob.job_type == "collect",
                    col(SambaJob.status).in_(["pending", "running"]),
                    SambaJob.payload["source_site"].as_string() == source_site,
                )
            )).scalars().first()
            if running:
                raise HTTPException(
                    409,
                    f"{source_site} 수집이 이미 진행 중입니다 (Job: {running.id}). 완료 후 다시 시도해주세요.",
                )

    job = await svc.create_job({
        "job_type": body.job_type,
        "payload": body.payload,
        "tenant_id": body.tenant_id,
    })
    await session.commit()
    return {"id": job.id, "status": job.status, "job_type": job.job_type}


@router.get("")
async def list_jobs(
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """잡 목록 조회."""
    svc = SambaJobService(SambaJobRepository(session))
    return await svc.list_jobs(status=status, skip=skip, limit=limit)


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """잡 상태 + 진행률 조회."""
    svc = SambaJobService(SambaJobRepository(session))
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    return job


@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: str,
    since: int = Query(0, ge=0),
):
    """Job 실시간 로그 조회."""
    from backend.domain.samba.job.worker import get_job_logs
    return {"logs": get_job_logs(job_id, since)}


@router.delete("/{job_id}")
async def cancel_job(
    job_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """잡 취소 (pending/running 모두 가능)."""
    repo = SambaJobRepository(session)
    ok = await repo.cancel_job(job_id)
    if not ok:
        raise HTTPException(400, "취소할 수 없는 상태입니다 (pending/running만 취소 가능)")
    await session.commit()
    return {"ok": True}
