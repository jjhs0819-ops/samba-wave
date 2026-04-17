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

    # 수집 잡: 대기 큐 위치 계산 (같은 소싱처 PENDING/RUNNING 수)
    queue_position = 0
    if body.job_type == "collect":
        source_site = body.payload.get("source_site", "")
        if source_site:
            from backend.domain.samba.job.model import SambaJob
            from sqlmodel import select, col
            from sqlalchemy import func

            queue_position = (
                (
                    await session.execute(
                        select(func.count())
                        .select_from(SambaJob)
                        .where(
                            SambaJob.job_type == "collect",
                            col(SambaJob.status).in_(
                                [JobStatus.PENDING, JobStatus.RUNNING]
                            ),
                        )
                    )
                ).scalar()
            ) or 0

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
                        col(SambaJob.status).in_([JobStatus.FAILED]),
                        SambaJob.total > 0,
                        SambaJob.current > 0,
                        SambaJob.current < SambaJob.total,  # 전체 완료된 Job 제외
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
    resp: dict = {"id": job.id, "status": job.status, "job_type": job.job_type}
    if queue_position > 0:
        resp["queue_position"] = queue_position
    return resp


@router.get("")
async def list_jobs(
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """잡 목록 조회 (payload 제외 — 경량 응답).

    Write DB 사용 — Read Replica 복제 지연으로 cancel 직후 stale 상태 반환 방지.
    """
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


@router.get("/collect-logs")
async def get_collect_log_buffer(
    since_idx: int = Query(0, ge=0),
):
    """수집 로그 링 버퍼 조회 — 창 닫아도 유지."""
    from backend.domain.samba.job.worker import get_collect_logs

    logs, current_idx = get_collect_logs(since_idx)
    return {"logs": logs, "current_idx": current_idx}


@router.post("/collect-logs/clear")
async def clear_collect_log_buffer():
    """수집 로그 링 버퍼 초기화."""
    from backend.domain.samba.job.worker import clear_collect_logs

    clear_collect_logs()
    return {"ok": True}


@router.get("/collect-queue-status")
async def get_collect_queue_status(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """수집 Job 큐 상태 — 진행/대기 그룹 이름 포함."""
    from sqlmodel import select, col
    from backend.domain.samba.job.model import SambaJob
    from backend.domain.samba.collector.model import SambaSearchFilter

    stmt = (
        select(SambaJob)
        .where(
            SambaJob.job_type == "collect",
            col(SambaJob.status).in_([JobStatus.RUNNING, JobStatus.PENDING]),
        )
        .order_by(SambaJob.created_at.asc())
    )
    result = await session.execute(stmt)
    jobs = result.scalars().all()

    # filter_id → SearchFilter 이름 일괄 조회
    filter_ids = [
        (j.payload or {}).get("filter_id", "")
        for j in jobs
        if (j.payload or {}).get("filter_id")
    ]
    filter_map: dict[str, tuple[str, str]] = {}
    if filter_ids:
        f_result = await session.execute(
            select(
                SambaSearchFilter.id,
                SambaSearchFilter.name,
                SambaSearchFilter.source_site,
            ).where(col(SambaSearchFilter.id).in_(filter_ids))
        )
        for fid, fname, fsite in f_result.all():
            filter_map[fid] = (fname or "", fsite or "")

    running = []
    pending = []
    for j in jobs:
        payload = j.payload or {}
        fid = payload.get("filter_id", "")
        fname, fsite = filter_map.get(fid, ("", payload.get("source_site", "")))
        item = {"filter_name": fname, "source_site": fsite}
        if j.status == JobStatus.RUNNING:
            running.append(item)
        else:
            pending.append(item)

    return {"running": running, "pending": pending}


@router.get("/transmit-queue-status")
async def get_transmit_queue_status(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """전송 Job 큐 상태 — 마켓명·계정·진행률 포함."""
    from sqlmodel import select, col
    from backend.domain.samba.job.model import SambaJob
    from backend.domain.samba.account.model import SambaMarketAccount

    stmt = (
        select(SambaJob)
        .where(
            SambaJob.job_type == "transmit",
            col(SambaJob.status).in_([JobStatus.RUNNING, JobStatus.PENDING]),
        )
        .order_by(SambaJob.created_at.asc())
    )
    result = await session.execute(stmt)
    jobs = result.scalars().all()

    # target_account_ids → 마켓 계정 이름 일괄 조회
    all_acc_ids: set[str] = set()
    for j in jobs:
        all_acc_ids.update((j.payload or {}).get("target_account_ids", []))

    acc_map: dict[str, str] = {}
    if all_acc_ids:
        acc_result = await session.execute(
            select(
                SambaMarketAccount.id,
                SambaMarketAccount.market_name,
                SambaMarketAccount.account_label,
            ).where(col(SambaMarketAccount.id).in_(list(all_acc_ids)))
        )
        for aid, mname, alabel in acc_result.all():
            acc_map[aid] = f"{mname}({alabel})" if alabel else mname

    running = []
    pending = []
    for j in jobs:
        payload = j.payload or {}
        target_ids = payload.get("target_account_ids", [])
        markets = ", ".join(
            dict.fromkeys(acc_map.get(a, "") for a in target_ids if acc_map.get(a))
        )
        item = {
            "markets": markets or "알 수 없음",
            "product_count": len(payload.get("product_ids", [])),
            "current": j.current or 0,
            "total": j.total or 0,
        }
        if j.status == JobStatus.RUNNING:
            running.append(item)
        else:
            pending.append(item)

    return {"running": running, "pending": pending}


@router.post("/cancel-collect")
async def cancel_collect_jobs(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """수집 잡만 취소 — 전송/오토튠은 영향 없음."""
    from sqlalchemy import text

    r = await session.execute(
        text(
            f"UPDATE samba_jobs SET status = '{JobStatus.CANCELLED}', completed_at = now() "
            f"WHERE job_type = 'collect' AND status IN ('{JobStatus.PENDING}', '{JobStatus.RUNNING}')"
        )
    )
    await session.commit()
    return {"ok": True, "cancelled": r.rowcount}


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

    # 플래그 해제하지 않음 — 워커가 감지 후 직접 해제
    return {"ok": True, "cancelled": r.rowcount}


@router.get("/last-resumable-transmit")
async def get_last_resumable_transmit(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """재개 가능한 최근 transmit 잡 조회 (payload 포함)."""
    from backend.domain.samba.job.model import SambaJob
    from sqlmodel import select, col

    job = (
        (
            await session.execute(
                select(SambaJob)
                .where(
                    SambaJob.job_type == "transmit",
                    col(SambaJob.status).in_([JobStatus.FAILED, JobStatus.CANCELLED]),
                    SambaJob.total > 0,
                    SambaJob.current > 0,
                    SambaJob.current < SambaJob.total,
                )
                .order_by(SambaJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if not job:
        return None
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "payload": job.payload,
        "current": job.current,
        "total": job.total,
        "created_at": job.created_at,
    }


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
