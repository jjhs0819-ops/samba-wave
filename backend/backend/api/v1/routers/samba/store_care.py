"""스토어케어 API — 가구매 스케줄 + 이력."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.store_care.repository import (
    StoreCareScheduleRepository,
    StoreCarePurchaseRepository,
)
from backend.domain.samba.store_care.service import StoreCareService

router = APIRouter(prefix="/store-care", tags=["samba-store-care"])


def _svc(session: AsyncSession) -> StoreCareService:
    """세션으로부터 서비스 인스턴스 생성."""
    return StoreCareService(
        StoreCareScheduleRepository(session),
        StoreCarePurchaseRepository(session),
    )


# ── 통계 ──


@router.get("/stats")
async def get_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """오늘 가구매 통계."""
    svc = _svc(session)
    return await svc.today_stats()


# ── 스케줄 ──


class ScheduleCreate(BaseModel):
    market_type: str
    account_id: str
    account_label: str = ""
    interval_hours: int = 6
    daily_target: int = 3
    product_selection: str = "random"
    product_ids: Optional[list] = None
    min_price: int = 10000
    max_price: int = 300000


class ScheduleUpdate(BaseModel):
    interval_hours: Optional[int] = None
    daily_target: Optional[int] = None
    product_selection: Optional[str] = None
    product_ids: Optional[list] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    status: Optional[str] = None


@router.get("/schedules")
async def list_schedules(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """활성 스케줄 목록 조회."""
    svc = _svc(session)
    return await svc.list_schedules()


@router.post("/schedules", status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """스케줄 생성."""
    svc = _svc(session)
    return await svc.create_schedule(body.model_dump())


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """스케줄 수정."""
    svc = _svc(session)
    data = body.model_dump(exclude_unset=True)
    return await svc.update_schedule(schedule_id, data)


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(
    schedule_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """스케줄 일시정지/재개 토글."""
    svc = _svc(session)
    result = await svc.toggle_schedule(schedule_id)
    if not result:
        raise HTTPException(404, "스케줄을 찾을 수 없습니다")
    return result


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """스케줄 삭제."""
    svc = _svc(session)
    await svc.delete_schedule(schedule_id)
    return {"ok": True}


# ── 구매 이력 ──


@router.get("/purchases")
async def list_purchases(
    limit: int = Query(50, ge=1, le=500),
    market_type: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """최근 구매 이력 조회."""
    svc = _svc(session)
    return await svc.list_purchases(limit=limit, market_type=market_type)
