"""SambaWave Analytics API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency

router = APIRouter(prefix="/analytics", tags=["samba-analytics"])


def _get_service(session: AsyncSession):
    from backend.domain.samba.analytics.service import SambaAnalyticsService
    from backend.domain.samba.channel.repository import SambaChannelRepository
    from backend.domain.samba.order.repository import SambaOrderRepository
    from backend.domain.samba.product.repository import SambaProductRepository

    return SambaAnalyticsService(
        SambaOrderRepository(session),
        SambaProductRepository(session),
        SambaChannelRepository(session),
    )


@router.get("/today")
async def get_today_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_today_stats()


@router.get("/range")
async def get_stats_by_date_range(
    start_date: str = Query(..., description="시작일 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="종료일 (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력해주세요.",
        )
    svc = _get_service(session)
    return await svc.get_stats_by_date_range(start, end)


@router.get("/channels")
async def get_sales_by_channel(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_sales_by_channel()


@router.get("/products")
async def get_sales_by_product(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_sales_by_product()


@router.get("/daily")
async def get_daily_trend(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_daily_trend(days=days)


@router.get("/monthly")
async def get_monthly_comparison(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_monthly_comparison()


@router.get("/kpi")
async def get_kpi_summary(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_kpi_summary()


@router.get("/order-status")
async def get_order_status_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    return await svc.get_order_status_stats()


@router.get("/sourcing-roi")
async def get_sourcing_roi(
    start_date: str = Query(None, description="시작일 (YYYY-MM-DD)"),
    end_date: str = Query(None, description="종료일 (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """소싱처별 ROI 분석."""
    svc = _get_service(session)
    sd = datetime.fromisoformat(start_date) if start_date else None
    ed = datetime.fromisoformat(end_date) if end_date else None
    return await svc.get_sourcing_roi(sd, ed)


@router.get("/best-sellers")
async def get_best_sellers(
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """매출 상위 상품 (베스트셀러)."""
    svc = _get_service(session)
    return await svc.get_best_sellers(limit=limit, days=days)


@router.get("/worst-sellers")
async def get_worst_sellers(
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """이윤 최하위 상품 (워스트셀러)."""
    svc = _get_service(session)
    return await svc.get_worst_sellers(limit=limit, days=days)


@router.get("/brands")
async def get_sales_by_brand(
    start_date: str = Query(None, description="시작일 (YYYY-MM-DD)"),
    end_date: str = Query(None, description="종료일 (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """브랜드별 매출 분석."""
    svc = _get_service(session)
    sd = datetime.fromisoformat(start_date) if start_date else None
    ed = datetime.fromisoformat(end_date) if end_date else None
    return await svc.get_sales_by_brand(sd, ed)
