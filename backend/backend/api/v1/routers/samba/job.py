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


@router.delete("/{job_id}")
async def cancel_job(
    job_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """잡 취소 (pending 상태만)."""
    svc = SambaJobService(SambaJobRepository(session))
    ok = await svc.cancel_job(job_id)
    if not ok:
        raise HTTPException(400, "취소할 수 없는 상태입니다 (pending만 취소 가능)")
    await session.commit()
    return {"ok": True}
