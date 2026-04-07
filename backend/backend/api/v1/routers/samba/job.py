"""작업 큐 API."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.job.model import JobStatus
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

            running = (
                (
                    await session.execute(
                        select(SambaJob).where(
                            SambaJob.job_type == "collect",
                            col(SambaJob.status).in_(
                                [JobStatus.PENDING, JobStatus.RUNNING]
                            ),
                            SambaJob.payload["source_site"].as_string() == source_site,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if running:
                raise HTTPException(
                    409,
                    f"{source_site} 수집이 이미 진행 중입니다 (Job: {running.id}). 완료 후 다시 시도해주세요.",
                )

    # 전송 잡: 최근 실패/취소 잡이 있으면 이어하기 (current 위치부터 재개)
    if body.job_type == "transmit":
        from backend.domain.samba.job.model import SambaJob
        from sqlmodel import select, col

        prev = (
            (
                await session.execute(
                    select(SambaJob)
                    .where(
                        SambaJob.job_type == "transmit",
                        col(SambaJob.status).in_(
                            [JobStatus.FAILED, JobStatus.CANCELLED]
                        ),
                        SambaJob.total > 0,
                        SambaJob.current > 0,
                    )
                    .order_by(SambaJob.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if (
            prev
            and prev.payload
            and prev.payload.get("product_ids") == body.payload.get("product_ids")
        ):
            # 같은 상품 목록 → 기존 잡을 pending으로 리셋하여 이어하기
            prev.status = JobStatus.PENDING
            prev.started_at = None
            prev.error = None
            prev.completed_at = None
            # current는 유지 → 워커가 이어서 처리
            session.add(prev)
            await session.commit()
            return {
                "id": prev.id,
                "status": JobStatus.PENDING,
                "job_type": "transmit",
                "resumed_from": prev.current,
            }

    job = await svc.create_job(
        {
            "job_type": body.job_type,
            "payload": body.payload,
            "tenant_id": body.tenant_id,
        }
    )
    await session.commit()
    return {"id": job.id, "status": job.status, "job_type": job.job_type}


@router.get("")
async def list_jobs(
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """잡 목록 조회 (payload 제외 — 경량 응답)."""
    svc = SambaJobService(SambaJobRepository(session))
    jobs = await svc.list_jobs(status=status, skip=skip, limit=limit)
    return [
        {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status,
            "progress": j.progress,
            "current": j.current,
            "total": j.total,
            "error": j.error,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "completed_at": j.completed_at,
        }
        for j in jobs
    ]


# ── 정적 경로 라우트 (/{job_id}보다 먼저 등록해야 라우트 충돌 방지) ──


@router.get("/shipment-logs")
async def get_shipment_log_buffer(
    since_idx: int = Query(0, ge=0),
):
    """전송 로그 링 버퍼 조회 — 창 닫아도 유지."""
    from backend.domain.samba.job.worker import get_shipment_logs

    logs, current_idx = get_shipment_logs(since_idx)
    return {"logs": logs, "current_idx": current_idx}


@router.post("/shipment-logs/clear")
async def clear_shipment_log_buffer():
    """전송 로그 링 버퍼 초기화."""
    from backend.domain.samba.job.worker import clear_shipment_logs

    clear_shipment_logs()
    return {"ok": True}


@router.post("/cancel-all")
async def cancel_all_jobs(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """대기 중(pending) + 실행 중(running) 잡 전부 취소 — 전송도 즉시 중단."""
    from sqlalchemy import text
    from backend.domain.samba.emergency import trigger_emergency_stop
    from backend.domain.samba.shipment.service import request_cancel_transmit

    # 1) 인메모리 플래그로 즉시 중단 (진행 중 전송 포함)
    request_cancel_transmit()
    trigger_emergency_stop()

    # 2) DB 상태 일괄 취소
    r = await session.execute(
        text(
            f"UPDATE samba_jobs SET status = '{JobStatus.CANCELLED}', completed_at = now() "
            f"WHERE status IN ('{JobStatus.PENDING}', '{JobStatus.RUNNING}')"
        )
    )
    await session.commit()

    # 3) 플래그 즉시 해제하지 않음 — 워커가 감지할 시간 확보
    # _run_transmit 시작 시 잔존 플래그를 자체 해제하므로 다음 전송에 영향 없음

    return {"ok": True, "cancelled": r.rowcount}


# ── 경로 파라미터 라우트 (정적 경로 뒤에 배치) ──


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
    from backend.domain.samba.shipment.service import request_cancel_transmit

    repo = SambaJobRepository(session)
    ok = await repo.cancel_job(job_id)
    if not ok:
        raise HTTPException(
            400, "취소할 수 없는 상태입니다 (pending/running만 취소 가능)"
        )
    await session.commit()
    # 실행 중인 전송 잡이면 인메모리 취소 플래그로 즉시 중단
    request_cancel_transmit(job_id)
    return {"ok": True}
