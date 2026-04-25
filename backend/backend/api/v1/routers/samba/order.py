"""SambaWave Order API router."""

import asyncio
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tenant.middleware import get_optional_tenant_id
from backend.domain.samba.order.model import SambaOrder
from backend.domain.samba.order.repository import SambaOrderRepository
from backend.domain.samba.order.service import SambaOrderService
from backend.dtos.samba.order import (
    FetchProductImageRequest,
    OrderCreate,
    OrderStatusUpdate,
    OrderUpdate,
)
from backend.utils.logger import logger

router = APIRouter(prefix="/orders", tags=["samba-orders"])

ACTIVE_ORDER_STATUSES = (
    "new_order",
    "invoice_printed",
    "pending",
    "preparing",
    "wait_ship",
    "arrived",
)
PENDING_ORDER_STATUSES = ("pending", "preparing")


class PaginatedOrdersResponse(BaseModel):
    items: list[SambaOrder]
    total_count: int
    total_sale: float
    pending_count: int


def _read_service(session: AsyncSession) -> SambaOrderService:
    return SambaOrderService(SambaOrderRepository(session))


def _write_service(session: AsyncSession) -> SambaOrderService:
    return SambaOrderService(SambaOrderRepository(session))


async def _resolve_market_filter_channel_ids(
    session: AsyncSession,
    market_filter: Optional[str],
    tenant_id: Optional[str],
) -> list[str]:
    if not market_filter or not market_filter.startswith("type:"):
        return []

    from sqlalchemy import or_, select

    from backend.domain.samba.account.model import SambaMarketAccount

    market_type = market_filter[5:]
    stmt = select(SambaMarketAccount.id).where(
        SambaMarketAccount.market_type == market_type
    )
    if tenant_id is not None:
        stmt = stmt.where(
            or_(
                SambaMarketAccount.tenant_id == tenant_id,
                SambaMarketAccount.tenant_id == None,  # noqa: E711
            )
        )
    result = await session.execute(stmt)
    return [row[0] for row in result.all() if row[0]]


async def _build_order_filters(
    session: AsyncSession,
    tenant_id: Optional[str],
    *,
    market_filter: str = "",
    site_filter: str = "",
    account_filter: str = "",
    market_status: str = "",
    status_filter: str = "",
    input_filter: str = "",
    search_text: str = "",
    search_category: str = "customer",
) -> list[Any]:
    from sqlalchemy import and_, or_

    filters: list[Any] = []

    if tenant_id is not None:
        filters.append(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )

    if market_filter:
        if market_filter.startswith("acc:"):
            filters.append(SambaOrder.channel_id == market_filter[4:])
        elif market_filter.startswith("type:"):
            channel_ids = await _resolve_market_filter_channel_ids(
                session, market_filter, tenant_id
            )
            if channel_ids:
                filters.append(SambaOrder.channel_id.in_(channel_ids))
            else:
                filters.append(SambaOrder.channel_id == "__no_matching_channel__")

    if site_filter:
        filters.append(SambaOrder.source_site == site_filter)
    if account_filter:
        filters.append(SambaOrder.sourcing_account_id == account_filter)
    if market_status:
        filters.append(SambaOrder.shipping_status == market_status)

    if status_filter:
        if status_filter == "active":
            filters.append(SambaOrder.status.in_(ACTIVE_ORDER_STATUSES))
        elif status_filter == "pending":
            filters.append(SambaOrder.status.in_(PENDING_ORDER_STATUSES))
        else:
            filters.append(SambaOrder.status == status_filter)

    if input_filter == "has_order":
        filters.append(
            and_(
                SambaOrder.sourcing_order_number != None,  # noqa: E711
                SambaOrder.sourcing_order_number != "",
            )
        )
    elif input_filter == "no_order":
        filters.append(
            or_(
                SambaOrder.sourcing_order_number == None,  # noqa: E711
                SambaOrder.sourcing_order_number == "",
            )
        )
    elif input_filter in {"direct", "kkadaegi", "gift"}:
        filters.append(SambaOrder.action_tag == input_filter)

    normalized_search = search_text.strip()
    if normalized_search:
        lower_q = f"%{normalized_search.lower()}%"
        if search_category == "product":
            filters.append(SambaOrder.product_name.ilike(lower_q))
        elif search_category == "product_id":
            filters.append(SambaOrder.product_id.ilike(lower_q))
        elif search_category == "order_number":
            filters.append(SambaOrder.order_number.ilike(lower_q))
        else:
            filters.append(SambaOrder.customer_name.ilike(lower_q))

    return filters


def _build_order_sort(sort_by: str):
    from sqlalchemy import func

    date_col = func.coalesce(SambaOrder.paid_at, SambaOrder.created_at)
    sort_map = {
        "date_asc": date_col.asc(),
        "profit_desc": SambaOrder.profit.desc(),
        "profit_asc": SambaOrder.profit.asc(),
        "price_desc": SambaOrder.sale_price.desc(),
        "price_asc": SambaOrder.sale_price.asc(),
    }
    return sort_map.get(sort_by, date_col.desc())


async def _run_paginated_order_query(
    session: AsyncSession,
    base_filters: list[Any],
    *,
    skip: int,
    limit: int,
    sort_by: str,
    extra_filters: Optional[list[Any]] = None,
) -> PaginatedOrdersResponse:
    from sqlalchemy import case, func, select

    sale_expr = func.coalesce(SambaOrder.total_payment_amount, SambaOrder.sale_price, 0)
    query_filters = [*base_filters, *(extra_filters or [])]

    total_stmt = select(
        func.count().label("total_count"),
        func.coalesce(func.sum(sale_expr), 0).label("total_sale"),
        func.coalesce(
            func.sum(case((SambaOrder.status.in_(PENDING_ORDER_STATUSES), 1), else_=0)),
            0,
        ).label("pending_count"),
    )
    if query_filters:
        total_stmt = total_stmt.where(*query_filters)
    total_row = (await session.execute(total_stmt)).one()

    items_stmt = select(SambaOrder)
    if query_filters:
        items_stmt = items_stmt.where(*query_filters)
    items_stmt = (
        items_stmt.order_by(_build_order_sort(sort_by)).offset(skip).limit(limit)
    )
    items = list((await session.execute(items_stmt)).scalars().all())

    return PaginatedOrdersResponse(
        items=items,
        total_count=int(total_row.total_count or 0),
        total_sale=float(total_row.total_sale or 0),
        pending_count=int(total_row.pending_count or 0),
    )


@router.get("", response_model=list[SambaOrder])
async def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    from sqlmodel import select

    # tenant_id가 있으면 해당 테넌트 주문만 조회
    if tenant_id is not None:
        stmt = (
            select(SambaOrder)
            .order_by(SambaOrder.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
        if status:
            stmt = stmt.where(SambaOrder.status == status)
        result = await session.execute(stmt)
        return result.scalars().all()
    svc = _read_service(session)
    return await svc.list_orders(skip=skip, limit=limit, status=status)


@router.get("/dashboard-stats")
async def dashboard_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """대시보드 집계 — DB에서 SUM/COUNT 후 결과만 반환 (빠름)."""
    from sqlalchemy import select, func, case, and_, extract, text, or_
    from datetime import datetime, timedelta, timezone as tz

    # 이행매출 대상 상태 (주문상태 드롭박스 기준)
    FULFILLMENT_STATUSES = (
        "pending",
        "wait_ship",
        "processing",
        "arrived",
        "ship_failed",
        "shipping",
        "shipped",
        "delivered",
        "exchanged",
        "exchanging",
        "exchange_requested",
    )

    # KST 기준 (UTC+9)
    KST = tz(timedelta(hours=9))
    now = datetime.now(KST).replace(tzinfo=None)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 1:
        last_month_start = this_month_start.replace(year=now.year - 1, month=12)
    else:
        last_month_start = this_month_start.replace(month=now.month - 1)
    week_ago = (now - timedelta(days=6)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # 날짜 기준: 고객결제일(paid_at)만 사용, KST 변환
    order_date = SambaOrder.paid_at + text("INTERVAL '9 hours'")

    # 금월 집계
    this_month_q = select(
        func.count().label("count"),
        func.coalesce(func.sum(SambaOrder.sale_price), 0).label("sales"),
        func.coalesce(
            func.sum(
                case(
                    (
                        SambaOrder.status.in_(FULFILLMENT_STATUSES),
                        SambaOrder.sale_price,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("fulfillment_sales"),
        func.sum(
            case(
                (SambaOrder.status.in_(FULFILLMENT_STATUSES), 1),
                else_=0,
            )
        ).label("fulfillment_count"),
    ).where(
        SambaOrder.paid_at != None, order_date >= this_month_start
    )  # noqa: E711
    if tenant_id is not None:
        this_month_q = this_month_q.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    tm = (await session.execute(this_month_q)).one()

    # 전월 집계
    last_month_q = select(
        func.count().label("count"),
        func.coalesce(func.sum(SambaOrder.sale_price), 0).label("sales"),
        func.coalesce(
            func.sum(
                case(
                    (
                        SambaOrder.status.in_(FULFILLMENT_STATUSES),
                        SambaOrder.sale_price,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("fulfillment_sales"),
        func.sum(
            case(
                (SambaOrder.status.in_(FULFILLMENT_STATUSES), 1),
                else_=0,
            )
        ).label("fulfillment_count"),
    ).where(
        SambaOrder.paid_at != None,
        and_(order_date >= last_month_start, order_date < this_month_start),
    )  # noqa: E711
    if tenant_id is not None:
        last_month_q = last_month_q.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    lm = (await session.execute(last_month_q)).one()

    # 최근 7일 일별 집계
    daily_q = (
        select(
            func.date(order_date).label("day"),
            func.count().label("count"),
            func.coalesce(func.sum(SambaOrder.sale_price), 0).label("sales"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            SambaOrder.status.in_(FULFILLMENT_STATUSES),
                            SambaOrder.sale_price,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("fulfillment_sales"),
            func.sum(
                case(
                    (SambaOrder.status.in_(FULFILLMENT_STATUSES), 1),
                    else_=0,
                )
            ).label("fulfillment_count"),
        )
        .where(SambaOrder.paid_at != None, order_date >= week_ago)  # noqa: E711
        .group_by(func.date(order_date))
    )
    if tenant_id is not None:
        daily_q = daily_q.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    daily_rows = (await session.execute(daily_q)).all()
    weekly = []
    for i in range(7):
        d = week_ago + timedelta(days=i)
        day_str = d.strftime("%Y-%m-%d")
        row = next((r for r in daily_rows if str(r.day) == day_str), None)
        weekly.append(
            {
                "date": day_str,
                "sales": float(row.sales) if row else 0,
                "count": int(row.count) if row else 0,
                "fulfillmentSales": float(row.fulfillment_sales) if row else 0,
                "fulfillmentCount": int(row.fulfillment_count) if row else 0,
            }
        )

    # 월별 집계 (연간 12개월)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_q = (
        select(
            extract("month", order_date).label("month"),
            func.coalesce(func.sum(SambaOrder.sale_price), 0).label("sales"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            SambaOrder.status.in_(FULFILLMENT_STATUSES),
                            SambaOrder.sale_price,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("fulfillment_sales"),
        )
        .where(
            SambaOrder.paid_at != None,  # noqa: E711
            and_(
                order_date >= year_start,
                extract("year", order_date) == now.year,
            ),
        )
        .group_by(extract("month", order_date))
    )
    if tenant_id is not None:
        monthly_q = monthly_q.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    monthly_rows = (await session.execute(monthly_q)).all()
    monthly = []
    for m in range(1, 13):
        row = next((r for r in monthly_rows if int(r.month) == m), None)
        monthly.append(
            {
                "month": m,
                "sales": float(row.sales) if row else 0,
                "fulfillmentSales": float(row.fulfillment_sales) if row else 0,
            }
        )

    tm_fulfillment_rate = (
        round(int(tm.fulfillment_count or 0) / int(tm.count) * 100) if tm.count else 0
    )
    lm_fulfillment_rate = (
        round(int(lm.fulfillment_count or 0) / int(lm.count) * 100) if lm.count else 0
    )
    sales_change = (
        round(((float(tm.sales) - float(lm.sales)) / float(lm.sales)) * 100, 1)
        if lm.sales
        else 0
    )

    return {
        "thisMonth": {
            "count": int(tm.count),
            "sales": float(tm.sales),
            "fulfillmentSales": float(tm.fulfillment_sales or 0),
            "fulfillmentCount": int(tm.fulfillment_count or 0),
            "fulfillment": tm_fulfillment_rate,
        },
        "lastMonth": {
            "count": int(lm.count),
            "sales": float(lm.sales),
            "fulfillmentSales": float(lm.fulfillment_sales or 0),
            "fulfillmentCount": int(lm.fulfillment_count or 0),
            "fulfillment": lm_fulfillment_rate,
        },
        "salesChange": sales_change,
        "weekly": weekly,
        "monthly": monthly,
    }


@router.get("/search", response_model=list[SambaOrder])
async def search_orders(
    q: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.search_orders(q)


@router.get("/by-date-range-paged", response_model=PaginatedOrdersResponse)
async def list_orders_by_date_range_paged(
    start: str = Query(..., description="start date YYYY-MM-DD"),
    end: str = Query(..., description="end date YYYY-MM-DD"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    market_filter: str = Query(""),
    site_filter: str = Query(""),
    account_filter: str = Query(""),
    market_status: str = Query(""),
    status_filter: str = Query(""),
    input_filter: str = Query(""),
    search_text: str = Query(""),
    search_category: str = Query("customer"),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    from backend.utils import kst_date_range_to_utc

    start_dt, end_dt = kst_date_range_to_utc(start, end)
    filters = await _build_order_filters(
        session,
        tenant_id,
        market_filter=market_filter,
        site_filter=site_filter,
        account_filter=account_filter,
        market_status=market_status,
        status_filter=status_filter,
        input_filter=input_filter,
        search_text=search_text,
        search_category=search_category,
    )
    return await _run_paginated_order_query(
        session,
        filters,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        extra_filters=[
            SambaOrder.paid_at != None,  # noqa: E711
            SambaOrder.paid_at >= start_dt,
            SambaOrder.paid_at <= end_dt,
        ],
    )


@router.get("/by-collected-product-paged", response_model=PaginatedOrdersResponse)
async def list_orders_by_collected_product_paged(
    collected_product_id: str = Query(..., description="collected product ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    market_filter: str = Query(""),
    site_filter: str = Query(""),
    account_filter: str = Query(""),
    market_status: str = Query(""),
    status_filter: str = Query(""),
    input_filter: str = Query(""),
    search_text: str = Query(""),
    search_category: str = Query("customer"),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    filters = await _build_order_filters(
        session,
        tenant_id,
        market_filter=market_filter,
        site_filter=site_filter,
        account_filter=account_filter,
        market_status=market_status,
        status_filter=status_filter,
        input_filter=input_filter,
        search_text=search_text,
        search_category=search_category,
    )
    return await _run_paginated_order_query(
        session,
        filters,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        extra_filters=[SambaOrder.collected_product_id == collected_product_id],
    )


@router.get("/by-date-range", response_model=list[SambaOrder])
async def list_orders_by_date_range(
    start: str = Query(..., description="시작일 YYYY-MM-DD"),
    end: str = Query(..., description="종료일 YYYY-MM-DD"),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """기간별 주문 조회 — paid_at(고객결제일) 기준, 제한 없이 전체 반환."""
    from sqlalchemy import select as sa_select, or_
    from backend.utils import kst_date_range_to_utc

    start_dt, end_dt = kst_date_range_to_utc(start, end)

    stmt = (
        sa_select(SambaOrder)
        .where(
            SambaOrder.paid_at != None,  # noqa: E711
            SambaOrder.paid_at >= start_dt,
            SambaOrder.paid_at <= end_dt,
        )
        .order_by(SambaOrder.paid_at.desc())
    )
    if tenant_id is not None:
        stmt = stmt.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/by-collected-product", response_model=list[SambaOrder])
async def list_orders_by_collected_product(
    collected_product_id: str = Query(..., description="수집상품 ID (cp_ULID)"),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """수집상품 ID로 해당 상품의 전체 주문 이력 조회."""
    from sqlalchemy import select as sa_select, func as sa_func, or_

    date_col = sa_func.coalesce(SambaOrder.paid_at, SambaOrder.created_at)
    stmt = (
        sa_select(SambaOrder)
        .where(SambaOrder.collected_product_id == collected_product_id)
        .order_by(date_col.desc())
    )
    if tenant_id is not None:
        stmt = stmt.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/find-by-number")
async def find_by_order_number(
    order_number: str = Query(...),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """상품주문번호로 주문 조회."""
    svc = _read_service(session)
    order = await svc.repo.find_by_async(order_number=order_number)
    if not order:
        return None
    # 테넌트 소유권 검증
    if tenant_id is not None and order.tenant_id != tenant_id:
        raise HTTPException(403, "해당 주문에 대한 권한이 없습니다")
    return {"id": order.id, "order_number": order.order_number}


@router.get("/alarm-settings")
async def get_alarm_settings(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """취소알람 수집 주기 및 영업시간 설정 조회."""
    from backend.api.v1.routers.samba.proxy import _get_setting

    data = await _get_setting(session, "cancel_alarm_settings") or {}
    return {
        "hour": data.get("hour", 0),
        "min": data.get("min", 5),
        "sleep_start": data.get("sleep_start", "23:00"),
        "sleep_end": data.get("sleep_end", "07:00"),
    }


@router.post("/alarm-settings")
async def save_alarm_settings(
    body: dict,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """취소알람 수집 주기 및 영업시간 설정 저장."""
    from backend.api.v1.routers.samba.proxy import _set_setting

    await _set_setting(
        session,
        "cancel_alarm_settings",
        {
            "hour": int(body.get("hour", 0)),
            "min": int(body.get("min", 5)),
            "sleep_start": body.get("sleep_start", "23:00"),
            "sleep_end": body.get("sleep_end", "07:00"),
        },
    )
    return {"ok": True}


@router.get("/{order_id}", response_model=SambaOrder)
async def get_order(
    order_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _read_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    # 테넌트 소유권 검증
    if tenant_id is not None and order.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="해당 주문에 대한 권한이 없습니다")
    return order


@router.post("", response_model=SambaOrder, status_code=201)
async def create_order(
    body: OrderCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    return await svc.create_order(body.model_dump(exclude_unset=True))


@router.patch("/{order_id}/link-product")
async def link_order_to_product(
    order_id: str,
    body: dict,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """주문에 수집상품 ID 연결 (지연 채움)."""
    cpid = body.get("collected_product_id", "")
    if not cpid:
        raise HTTPException(400, "collected_product_id 필수")
    from sqlalchemy import text as _t

    await session.execute(
        _t(
            "UPDATE samba_order SET collected_product_id = :cpid WHERE id = :oid AND collected_product_id IS NULL"
        ),
        {"cpid": cpid, "oid": order_id},
    )
    await session.commit()
    return {"ok": True}


@router.post("/backfill-product-links")
async def backfill_product_links(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """기존 주문의 collected_product_id 일괄 백필."""
    from sqlalchemy import text as _t

    # market_product_nos에서 역매핑 캐시 빌드
    cp_rows = await session.execute(
        _t(
            "SELECT id, market_product_nos FROM samba_collected_product "
            "WHERE market_product_nos IS NOT NULL"
        )
    )
    mpn_map: dict[str, str] = {}
    for cpid, mpnos in cp_rows.fetchall():
        if not mpnos or not isinstance(mpnos, dict):
            continue
        for _v in mpnos.values():
            if not _v:
                continue
            if isinstance(_v, dict):
                for sv in [
                    _v.get("smartstoreChannelProductNo"),
                    _v.get("originProductNo"),
                    _v.get("channelProductNo"),
                ]:
                    if sv:
                        mpn_map[str(sv)] = cpid
            else:
                mpn_map[str(_v)] = cpid

    # collected_product_id가 없는 주문 조회
    null_orders = await session.execute(
        _t(
            "SELECT id, product_id FROM samba_order "
            "WHERE collected_product_id IS NULL AND product_id IS NOT NULL"
        )
    )
    linked = 0
    for oid, pid in null_orders.fetchall():
        cpid = mpn_map.get(str(pid))
        if cpid:
            await session.execute(
                _t(
                    "UPDATE samba_order SET collected_product_id = :cpid WHERE id = :oid"
                ),
                {"cpid": cpid, "oid": oid},
            )
            linked += 1
    await session.commit()
    return {"linked": linked, "total_cache": len(mpn_map)}


@router.put("/{order_id}", response_model=SambaOrder)
async def update_order(
    order_id: str,
    body: OrderUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    order = await svc.update_order(order_id, body.model_dump(exclude_unset=True))
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    return order


@router.put("/{order_id}/status", response_model=SambaOrder)
async def update_order_status(
    order_id: str,
    body: OrderStatusUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    order = await svc.update_order_status(order_id, body.status)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    return order


@router.delete("/{order_id}")
async def delete_order(
    order_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    deleted = await svc.delete_order(order_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    return {"ok": True}


# ══════════════════════════════════════════════
# 취소승인
# ══════════════════════════════════════════════


@router.post("/{order_id}/approve-cancel")
async def approve_cancel(
    order_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """취소요청 주문에 대해 마켓 취소승인 실행."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")

    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")

    # 마켓 계정 조회
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    if account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증정보 없음")

        client = SmartStoreClient(client_id, client_secret)
        try:
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

        # DB 상태 업데이트
        await svc.update_order(
            order_id,
            {
                "shipping_status": "취소완료",
            },
        )
        logger.info(f"[취소승인] {order.order_number} 취소승인 완료")
        return {"ok": True, "message": "취소승인 완료"}

    elif account.market_type == "ebay":
        # eBay는 seller_cancel_order로 이미 취소 처리됨 → DB 상태만 동기화
        await svc.update_order(
            order_id,
            {"shipping_status": "취소완료", "status": "cancelled"},
        )
        # samba_return 상태도 업데이트
        from backend.domain.samba.returns.repository import SambaReturnRepository

        ret_repo = SambaReturnRepository(session)
        rets = await ret_repo.filter_by_async(order_id=order_id)
        for ret in rets:
            await ret_repo.update_async(
                ret.id,
                status="completed",
                market_order_status="취소완료",
            )
        logger.info(f"[취소승인] eBay {order.order_number} 취소완료 동기화")
        return {"ok": True, "message": "eBay 취소완료 처리"}

    else:
        raise HTTPException(
            status_code=400, detail=f"{account.market_type} 취소승인 미지원"
        )


# ══════════════════════════════════════════════
# 판매자 주도 취소 (재고부족, 가격변동 등)
# ══════════════════════════════════════════════


class SellerCancelBody(BaseModel):
    reason_code: str = (
        "111"  # 111=품절, 132=가격오등록, 133=리셀러, 135=고객변심, 137=택배불가
    )
    reason_text: Optional[str] = None


@router.post("/{order_id}/seller-cancel")
async def seller_cancel(
    order_id: str,
    body: SellerCancelBody,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """판매자 주도 주문 취소 (재고부족/가격변동 등)."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    if account.market_type == "lotteon":
        from backend.domain.samba.proxy.lotteon import LotteonClient

        extras = account.additional_fields or {}
        api_key = extras.get("apiKey", "") or account.api_key or ""
        if not api_key:
            raise HTTPException(status_code=400, detail="롯데ON API Key 없음")

        client = LotteonClient(api_key)
        try:
            await client.test_auth()
            success, message = await client.seller_cancel_order(
                od_no=order.od_no or order.order_number,
                reason_code=body.reason_code,
                reason_text=body.reason_text or "고객변심",
                od_seq=int(order.od_seq or 1),
                proc_seq=int(order.proc_seq or 1),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"판매자 취소 실패: {e}")

        if not success:
            raise HTTPException(status_code=500, detail=f"판매자 취소 실패: {message}")

        await svc.update_order(
            order_id,
            {"shipping_status": "취소완료", "status": "cancelled"},
        )
        # 롯데ON은 단일 itemList 요청으로 같은 odNo의 모든 옵션이 함께 취소됨.
        # 삼바 DB도 같은 odNo의 다른 옵션 레코드를 일괄 cancelled 처리해 UI 정합성 유지.
        od_no_val = order.od_no
        sibling_count = 0
        if od_no_val:
            from sqlmodel import select

            sibling_stmt = (
                select(SambaOrder)
                .where(SambaOrder.od_no == od_no_val)
                .where(SambaOrder.channel_id == order.channel_id)
                .where(SambaOrder.id != order_id)
                .where(SambaOrder.status != "cancelled")
            )
            sibling_rows = (await session.execute(sibling_stmt)).scalars().all()
            for sib in sibling_rows:
                await svc.update_order(
                    sib.id,
                    {"shipping_status": "취소완료", "status": "cancelled"},
                )
            sibling_count = len(sibling_rows)
        if sibling_count:
            logger.info(
                f"[판매자취소] 롯데ON {order.order_number} 동일 주문 옵션 {sibling_count}건 동반 취소"
            )
        logger.info(
            f"[판매자취소] 롯데ON {order.order_number} 완료 ({body.reason_code})"
        )
        user_msg = (
            "이미 취소된 주문 — DB 상태 갱신 완료"
            if message == "이미 취소된 주문"
            else "판매자 취소 완료"
        )
        return {"ok": True, "message": user_msg, "detail": message}

    elif account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient
        from backend.domain.samba.forbidden.repository import SambaSettingsRepository

        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증정보 없음")

        client = SmartStoreClient(client_id, client_secret)
        try:
            await client.request_cancel(
                product_order_id=order.order_number,
                cancel_reason="INTENT_CHANGED",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"판매자 취소 실패: {e}")

        await svc.update_order(
            order_id,
            {"shipping_status": "취소완료", "status": "cancelled"},
        )
        logger.info(
            f"[판매자취소] 스마트스토어 {order.order_number} 완료 (INTENT_CHANGED)"
        )
        return {"ok": True, "message": "판매자 취소 완료"}

    elif account.market_type == "playauto":
        # 플레이오토 EMP API는 주문확인 상태변경 미지원 (송장입력만 가능)
        # DB 상태만 변경하여 이행 불가 건 구분용으로 사용
        await svc.update_order(
            order_id,
            {"shipping_status": "주문확인"},
        )
        logger.info(f"[주문확인] 플레이오토 {order.order_number} 주문확인 완료 (DB)")
        return {"ok": True, "message": "주문확인 완료"}

    elif account.market_type == "ebay":
        from backend.domain.samba.proxy.ebay import EbayApiError, EbayClient

        extras = account.additional_fields or {}
        app_id = extras.get("clientId") or extras.get("appId") or account.api_key or ""
        cert_id = (
            extras.get("clientSecret")
            or extras.get("certId")
            or account.api_secret
            or ""
        )
        refresh_token = extras.get("oauthToken") or extras.get("authToken", "") or ""
        if not (app_id and cert_id and refresh_token):
            raise HTTPException(status_code=400, detail="eBay 인증정보 없음")

        client = EbayClient(
            app_id=app_id,
            dev_id="",
            cert_id=cert_id,
            refresh_token=refresh_token,
            sandbox=bool(extras.get("sandbox", False)),
        )
        # order_number에 legacyOrderId 저장되어 있음
        try:
            reason_map = {
                "111": "OUT_OF_STOCK_OR_CANNOT_FULFILL",
                "SOLD_OUT": "OUT_OF_STOCK_OR_CANNOT_FULFILL",
                "112": "BUYER_CANCEL_OR_ADDRESS_ISSUE",
                "113": "BUYER_ASKED_CANCEL",
            }
            ebay_reason = reason_map.get(
                body.reason_code, "OUT_OF_STOCK_OR_CANNOT_FULFILL"
            )
            await client.seller_cancel_order(
                legacy_order_id=order.order_number,
                reason=ebay_reason,
            )
        except EbayApiError as e:
            raise HTTPException(status_code=500, detail=f"eBay 취소 실패: {e}")

        await svc.update_order(
            order_id,
            {"shipping_status": "취소요청", "status": "cancel_requested"},
        )
        logger.info(f"[판매자취소] eBay {order.order_number} 취소 요청 완료")
        return {"ok": True, "message": "eBay 판매자 취소 요청 완료"}

    raise HTTPException(
        status_code=400, detail=f"{account.market_type} 판매자 취소 미지원"
    )


@router.post("/{order_id}/confirm")
async def confirm_order(
    order_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """주문확인(발주확인) 수동 처리 — 원소싱처 재고/가격 확인 후 사용자가 실행."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    if account.market_type == "lotteon":
        from backend.domain.samba.proxy.lotteon import LotteonClient

        extras = account.additional_fields or {}
        api_key = extras.get("apiKey", "") or account.api_key or ""
        if not api_key:
            raise HTTPException(status_code=400, detail="롯데ON API Key 없음")

        # SellerIfCompleteInform은 odNo/odSeq/procSeq만 필요 (비클레임은 기본 1/1)
        client = LotteonClient(api_key)
        try:
            await client.test_auth()
            ok = await client.confirm_orders(
                [
                    {
                        "odNo": order.od_no or order.order_number,
                        "odSeq": int(order.od_seq or 1),
                        "procSeq": int(order.proc_seq or 1),
                    }
                ]
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"주문확인 실패: {e}")

        if not ok:
            raise HTTPException(
                status_code=500,
                detail="롯데ON 주문확인 실패 — SellerIfCompleteInform 응답 rsltCd≠0000 (서버 로그 확인)",
            )

        await svc.update_order(order_id, {"shipping_status": "출고지시"})
        logger.info(f"[주문확인] 롯데ON {order.order_number} 완료")
        return {"ok": True, "message": "주문확인 완료"}

    raise HTTPException(
        status_code=400, detail=f"{account.market_type} 주문확인 미지원"
    )


@router.post("/{order_id}/market-delete")
async def market_delete_order_product(
    order_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """주문 카드의 '마켓상품삭제' — 해당 주문 상품을 마켓에서 완전 삭제(판매종료가 아닌 삭제)."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    if not order.product_id:
        raise HTTPException(status_code=400, detail="마켓 상품번호가 없습니다")
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    if account.market_type == "lotteon":
        from backend.domain.samba.proxy.lotteon import LotteonClient

        extras = account.additional_fields or {}
        api_key = extras.get("apiKey", "") or account.api_key or ""
        if not api_key:
            raise HTTPException(status_code=400, detail="롯데ON API Key 없음")

        spd_no = order.product_id
        client = LotteonClient(api_key)
        try:
            await client.test_auth()
            result = await client.delete_product(spd_no)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"마켓상품삭제 실패: {e}")

        logger.info(
            f"[마켓상품삭제] 롯데ON spdNo={spd_no} order={order.order_number} result={result}"
        )
        return {"ok": True, "message": "마켓 상품 삭제 완료", "detail": result}

    if account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증 정보 없음")

        # originProductNo: collected_product의 market_product_nos에서 우선 조회
        origin_product_no = ""
        if order.collected_product_id:
            from backend.domain.samba.collector.repository import (
                SambaCollectorRepository,
            )

            cp_repo = SambaCollectorRepository(session)
            cp = await cp_repo.get_async(order.collected_product_id)
            if cp and cp.market_product_nos:
                origin_product_no = (cp.market_product_nos or {}).get(
                    order.channel_id, ""
                )

        # fallback: channelProductNo (order.product_id)
        if not origin_product_no:
            origin_product_no = order.product_id or ""

        if not origin_product_no:
            raise HTTPException(
                status_code=400, detail="스마트스토어 상품번호를 찾을 수 없습니다"
            )

        client = SmartStoreClient(client_id, client_secret)
        try:
            result = await client.delete_product(origin_product_no)
            logger.info(
                f"[마켓상품삭제] 스마트스토어 삭제 성공 productNo={origin_product_no} "
                f"order={order.order_number}"
            )
            return {"ok": True, "message": "마켓 상품 삭제 완료", "detail": result}
        except Exception as del_err:
            # 진행중 주문 등으로 삭제 불가 시 → 전 옵션 재고 0 (품절) 폴백
            logger.warning(
                f"[마켓상품삭제] 스마트스토어 삭제 실패({del_err}), 품절 폴백 시도: {origin_product_no}"
            )

        try:
            existing = await client.get_product(origin_product_no)
            origin = existing.get("originProduct", {})
            for k in ["productNo", "channelProducts", "regDate", "modifiedDate"]:
                origin.pop(k, None)

            # 전 옵션 재고 0 + usable=False
            origin["stockQuantity"] = 0
            opt_info = origin.get("detailAttribute", {}).get("optionInfo") or {}
            combos = opt_info.get("optionCombinations") or opt_info.get(
                "combinations", []
            )
            for combo in combos:
                combo["stockQuantity"] = 0
                combo["usable"] = False

            put_data: dict[str, Any] = {"originProduct": origin}
            if "smartstoreChannelProduct" in existing:
                put_data["smartstoreChannelProduct"] = existing[
                    "smartstoreChannelProduct"
                ]

            await client.update_product(origin_product_no, put_data)
            logger.info(
                f"[마켓상품삭제] 스마트스토어 품절 폴백 완료 productNo={origin_product_no}"
            )
            return {
                "ok": True,
                "message": "마켓 삭제 불가 — 전 옵션 품절처리 완료",
                "fallback": True,
            }
        except Exception as fb_err:
            raise HTTPException(
                status_code=500,
                detail=f"마켓상품삭제 및 품절처리 모두 실패: {fb_err}",
            )

    raise HTTPException(
        status_code=400, detail=f"{account.market_type} 마켓상품삭제 미지원"
    )


class CancelSourceOrderRequest(BaseModel):
    order_number: str
    reason: str = "단순변심"


@router.post("/cancel-source-order")
async def cancel_source_order(
    req: CancelSourceOrderRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """소싱처 원주문 취소 (무신사 등 소비자 주문취소)."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    settings_repo = SambaSettingsRepository(session)

    # 현재는 무신사만 지원
    cookie_row = await settings_repo.find_by_async(key="musinsa_cookie")
    musinsa_cookie = cookie_row.value if cookie_row else ""
    if not musinsa_cookie:
        raise HTTPException(status_code=400, detail="무신사 쿠키가 설정되지 않았습니다")

    from backend.domain.samba.proxy.musinsa import MusinsaClient

    client = MusinsaClient(cookie=musinsa_cookie)

    try:
        result = await client.cancel_order(req.order_number, req.reason)
        return result
    except Exception as e:
        logger.error(f"[원주문취소] 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════
# 교환 처리 (재배송 / 거부 / 반품변경)
# ══════════════════════════════════════════════


class ExchangeActionBody(BaseModel):
    action: str  # "reship" | "reject" | "convert_return"
    reason: Optional[str] = None
    clm_no: Optional[str] = None  # 롯데ON 교환 클레임번호
    tracking_number: Optional[str] = None  # 롯데ON 교환 재배송 송장번호
    shipping_company: Optional[str] = None  # 롯데ON 교환 재배송 택배사


@router.post("/{order_id}/exchange-action")
async def exchange_action(
    order_id: str,
    body: ExchangeActionBody,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """교환요청에 대한 처리 (재배송/거부/반품변경)."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    if account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증정보 없음")

        client = SmartStoreClient(client_id, client_secret)
        action_labels = {
            "reship": "교환재배송",
            "reject": "교환거부",
            "convert_return": "반품변경",
        }
        label = action_labels.get(body.action, body.action)

        try:
            if body.action == "reship":
                await client.approve_exchange(order.order_number)
                new_status = "교환완료"
            elif body.action == "reject":
                await client.reject_exchange(
                    order.order_number, body.reason or "판매자 교환 거부"
                )
                new_status = "교환거부"
            elif body.action == "convert_return":
                await client.convert_exchange_to_return(order.order_number)
                new_status = "반품변경"
            else:
                raise HTTPException(
                    status_code=400, detail=f"알 수 없는 액션: {body.action}"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{label} 실패: {e}")

        await svc.update_order(order_id, {"shipping_status": new_status})
        logger.info(f"[교환처리] {order.order_number} {label} 완료")
        return {"ok": True, "message": f"{label} 완료"}

    elif account.market_type == "lotteon":
        from backend.domain.samba.proxy.lotteon import LotteonClient

        extras = account.additional_fields or {}
        api_key = extras.get("apiKey", "") or account.api_key or ""
        if not api_key:
            raise HTTPException(status_code=400, detail="롯데ON API 키 없음")

        client = LotteonClient(api_key=api_key)
        await client.test_auth()

        # 교환 클레임 정보 자동 탐색 (clmNo, procSeq, orglProcSeq)
        clm_no = body.clm_no or ""
        found_claim: dict = {}
        try:
            exchange_claims = await client.get_exchanges(days=30)
            for claim in exchange_claims:
                if str(claim.get("odNo", "")) == str(order.od_no or order.order_number):
                    if not clm_no:
                        clm_no = claim.get("clmNo", "")
                    found_claim = claim
                    logger.info(
                        f"[교환처리] clmNo 탐색 성공: {clm_no} stepCd={claim.get('odPrgsStepCd', '')}"
                    )
                    break
        except Exception as ce:
            logger.warning(f"[교환처리] 클레임 탐색 실패: {ce}")

        if body.action == "reship":
            # 교환 재배송: 승인 → 발송 처리
            tracking_number = body.tracking_number or ""
            shipping_company = body.shipping_company or ""
            sitm_no = order.shipment_id or ""
            spd_no = order.product_id or ""
            quantity = order.quantity or 1

            if not tracking_number:
                raise HTTPException(
                    status_code=400, detail="교환 재배송 송장번호가 필요합니다"
                )

            # 교환 승인 (회수 지시) — 접수(03) 상태인 경우 먼저 승인
            step_cd = str(found_claim.get("odPrgsStepCd", "") or "")
            if step_cd == "03" and clm_no:
                proc_seq = str(found_claim.get("procSeq", 1))
                orgl_proc_seq = str(found_claim.get("orglProcSeq", 1))
                clm_rsn_cd = str(found_claim.get("clmRsnCd", "204"))
                try:
                    approved = await client.approve_exchange(
                        od_no=order.od_no or order.order_number,
                        clm_no=clm_no,
                        items=[
                            {
                                "odSeq": int(order.od_seq or 1),
                                "procSeq": int(proc_seq),
                                "orglProcSeq": int(orgl_proc_seq),
                                "slrRsnCd": clm_rsn_cd,
                            }
                        ],
                    )
                    if approved:
                        logger.info(f"[교환처리] {order.order_number} 교환 승인 완료")
                except Exception as ae:
                    logger.warning(f"[교환처리] 교환 승인 실패 (계속 진행): {ae}")

            try:
                sent = await client.ship_order_exchange(
                    od_no=order.od_no or order.order_number,
                    od_seq=order.od_seq or "1",
                    proc_seq=order.proc_seq or "1",
                    sitm_no=sitm_no,
                    spd_no=spd_no,
                    clm_no=clm_no,
                    quantity=quantity,
                    shipping_company=shipping_company,
                    tracking_number=tracking_number,
                )
                if not sent:
                    raise HTTPException(
                        status_code=500, detail="롯데ON 교환 재배송 전송 실패"
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"교환 재배송 실패: {e}")

            await svc.update_order(
                order_id,
                {
                    "shipping_status": "교환재배송",
                    "tracking_number": tracking_number,
                    "shipping_company": shipping_company,
                },
            )
            logger.info(f"[교환처리] {order.order_number} 롯데ON 교환재배송 완료")
            return {"ok": True, "message": "교환 재배송 처리 완료"}

        elif body.action == "convert_return":
            # 교환→반품 변경: 롯데ON API 미지원 → 삼바 내부 처리만
            # 반품교환 레코드 타입을 exchange→return으로 변경
            from backend.domain.samba.returns.repository import SambaReturnRepository

            return_repo = SambaReturnRepository(session)
            ret = await return_repo.find_by_async(order_id=order_id)
            if ret:
                await return_repo.update_async(
                    ret.id,
                    type="return",
                    market_order_status="반품요청",
                    status="pending",
                )
            await svc.update_order(
                order_id, {"shipping_status": "반품요청", "status": "return_requested"}
            )
            logger.info(
                f"[교환처리] {order.order_number} 교환→반품 변경 완료 (삼바 내부)"
            )
            return {
                "ok": True,
                "message": "교환→반품 변경 완료 (롯데ON 판매자센터에서도 별도 처리 필요)",
            }

        elif body.action == "reject":
            # 교환 거부: 삼바 내부 상태 업데이트 (롯데ON 교환 거부 API 스펙 확인 후 연동 필요)
            from backend.domain.samba.returns.repository import SambaReturnRepository

            return_repo = SambaReturnRepository(session)
            ret = await return_repo.find_by_async(order_id=order_id)
            if ret:
                await return_repo.update_async(
                    ret.id,
                    status="rejected",
                    market_order_status="교환거부",
                )
            await svc.update_order(order_id, {"shipping_status": "교환거부"})
            logger.info(f"[교환처리] {order.order_number} 교환거부 완료 (삼바 내부)")
            return {
                "ok": True,
                "message": "교환거부 완료 (롯데ON 판매자센터에서도 별도 처리 필요)",
            }

        else:
            raise HTTPException(
                status_code=400, detail=f"롯데ON 교환처리 미지원 액션: {body.action}"
            )

    else:
        raise HTTPException(
            status_code=400, detail=f"{account.market_type} 교환처리 미지원"
        )


# ══════════════════════════════════════════════
# 반품 처리 (승인 / 거부)
# ══════════════════════════════════════════════


class ReturnActionBody(BaseModel):
    action: str  # "approve" | "reject"
    reason: Optional[str] = None


@router.post("/{order_id}/return-action")
async def return_action(
    order_id: str,
    body: ReturnActionBody,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """반품요청에 대한 처리 (승인/거부)."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    if account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증정보 없음")

        client = SmartStoreClient(client_id, client_secret)
        label = "반품승인" if body.action == "approve" else "반품거부"

        try:
            if body.action == "approve":
                try:
                    await client.approve_return(order.order_number)
                except Exception as first_err:
                    if "환불보류" in str(first_err):
                        # 환불보류 해제 후 재시도
                        logger.info(
                            f"[반품처리] {order.order_number} 환불보류 감지 → 보류해제 후 재시도"
                        )
                        await client.release_return_hold(order.order_number)
                        await client.approve_return(order.order_number)
                    else:
                        raise
                new_status = "반품승인"
            elif body.action == "reject":
                await client.reject_return(
                    order.order_number, body.reason or "판매자 반품 거부"
                )
                new_status = "반품거부"
            else:
                raise HTTPException(
                    status_code=400, detail=f"알 수 없는 액션: {body.action}"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{label} 실패: {e}")

        await svc.update_order(order_id, {"shipping_status": new_status})

        # 반품교환(samba_return) 레코드도 상태 업데이트
        from backend.domain.samba.returns.repository import SambaReturnRepository
        from datetime import UTC, datetime

        return_repo = SambaReturnRepository(session)
        existing_returns = await return_repo.filter_by_async(order_id=order_id)
        if existing_returns:
            ret = existing_returns[0]
            if body.action == "approve":
                await return_repo.update_async(
                    ret.id,
                    status="completed",
                    market_order_status="반품완료",
                    completion_date=datetime.now(UTC),
                )
            elif body.action == "reject":
                await return_repo.update_async(
                    ret.id,
                    status="rejected",
                    market_order_status="반품거부",
                )

        logger.info(f"[반품처리] {order.order_number} {label} 완료")
        return {"ok": True, "message": f"{label} 완료"}

    elif account.market_type == "lotteon":
        from backend.domain.samba.proxy.lotteon import LotteonClient

        api_key = (
            (account.additional_fields or {}).get("apiKey", "") or account.api_key or ""
        )
        if not api_key:
            raise HTTPException(status_code=400, detail="롯데ON API 키 없음")

        client = LotteonClient(api_key=api_key)
        label = "반품승인" if body.action == "approve" else "반품거부"

        try:
            if body.action == "approve":
                # 반품 클레임 목록에서 해당 주문 item 조회
                raw_returns = await client.get_returns(days=30)
                _lo_od_no = order.od_no or order.order_number
                claim_items = [i for i in raw_returns if i.get("odNo") == _lo_od_no]
                if not claim_items:
                    raise HTTPException(
                        status_code=400,
                        detail="롯데ON 반품 클레임 정보 없음 (최근 30일 내 조회되지 않음)",
                    )
                ci = claim_items[0]
                clm_no = ci.get("clmNo", "")
                od_seq = int(ci.get("odSeq") or 1)
                proc_seq = int(ci.get("procSeq") or od_seq)
                orgl_proc_seq = int(ci.get("orglProcSeq") or proc_seq)
                items_payload = [
                    {
                        "odSeq": od_seq,
                        "procSeq": proc_seq,
                        "orglProcSeq": orgl_proc_seq,
                        "spdNo": ci.get("spdNo", ""),
                        "spdNm": ci.get("spdNm", ""),
                        "sitmNo": ci.get("sitmNo", ""),
                        "sitmNm": ci.get("sitmNm", ""),
                    }
                ]
                await client.approve_return(_lo_od_no, clm_no, items_payload)
                new_status = "반품승인"
            elif body.action == "reject":
                await client.reject_return(_lo_od_no, body.reason or "")
                new_status = "반품거부"
            else:
                raise HTTPException(
                    status_code=400, detail=f"알 수 없는 액션: {body.action}"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{label} 실패: {e}")

        await svc.update_order(order_id, {"shipping_status": new_status})

        # samba_return 상태 업데이트
        from backend.domain.samba.returns.repository import SambaReturnRepository
        from datetime import UTC, datetime

        return_repo = SambaReturnRepository(session)
        existing_returns = await return_repo.filter_by_async(order_id=order_id)
        if existing_returns:
            ret = existing_returns[0]
            if body.action == "approve":
                await return_repo.update_async(
                    ret.id,
                    status="completed",
                    market_order_status="반품완료",
                    completion_date=datetime.now(UTC),
                )
            elif body.action == "reject":
                await return_repo.update_async(
                    ret.id,
                    status="rejected",
                    market_order_status="반품거부",
                )

        logger.info(f"[반품처리][롯데ON] {order.order_number} {label} 완료")
        return {"ok": True, "message": f"{label} 완료"}

    elif account.market_type == "ebay":
        # eBay 반품은 SambaReturn.market_order_status 에 저장된 returnId 필요
        from backend.domain.samba.proxy.ebay import EbayApiError, EbayClient
        from backend.domain.samba.returns.repository import SambaReturnRepository

        extras = account.additional_fields or {}
        app_id = extras.get("clientId") or extras.get("appId") or account.api_key or ""
        cert_id = (
            extras.get("clientSecret")
            or extras.get("certId")
            or account.api_secret
            or ""
        )
        refresh_token = extras.get("oauthToken") or extras.get("authToken", "") or ""
        if not (app_id and cert_id and refresh_token):
            raise HTTPException(status_code=400, detail="eBay 인증정보 없음")

        # returnId 는 samba_return.notes 또는 market_order_status에 저장 권장
        ret_repo = SambaReturnRepository(session)
        existing = await ret_repo.filter_by_async(order_id=order_id)
        if not existing:
            raise HTTPException(
                status_code=400, detail="해당 주문에 반품 데이터가 없습니다"
            )
        return_id = existing[0].memo or existing[0].market_order_status or ""
        # memo/market_order_status 에 returnId 저장 관례. 비어있으면 사용자 입력 필요
        if not return_id:
            raise HTTPException(
                status_code=400,
                detail="eBay returnId 없음 (samba_return.memo에 저장 필요)",
            )

        client = EbayClient(
            app_id=app_id,
            dev_id="",
            cert_id=cert_id,
            refresh_token=refresh_token,
            sandbox=bool(extras.get("sandbox", False)),
        )
        try:
            if body.action == "approve":
                await client.approve_return(return_id)
                new_status = "반품승인"
                ret_update = {"status": "completed", "market_order_status": "반품승인"}
            elif body.action == "reject":
                await client.reject_return(return_id, body.reason or "Seller decline")
                new_status = "반품거부"
                ret_update = {"status": "rejected", "market_order_status": "반품거부"}
            else:
                raise HTTPException(
                    status_code=400, detail=f"eBay 반품 액션 미지원: {body.action}"
                )
        except EbayApiError as e:
            raise HTTPException(status_code=500, detail=f"eBay 반품처리 실패: {e}")

        await svc.update_order(order_id, {"shipping_status": new_status})
        await ret_repo.update_async(existing[0].id, **ret_update)
        logger.info(f"[반품처리][eBay] {order.order_number} {body.action} 완료")
        return {"ok": True, "message": f"eBay 반품 {body.action} 완료"}

    else:
        raise HTTPException(
            status_code=400, detail=f"{account.market_type} 반품처리 미지원"
        )


# ══════════════════════════════════════════════
# 송장번호 전송 (발송처리)
# ══════════════════════════════════════════════


class ShipRequest(BaseModel):
    shipping_company: str
    tracking_number: str


@router.post("/{order_id}/ship")
async def ship_order(
    order_id: str,
    body: ShipRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """송장번호 저장 + 마켓 발송처리."""
    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(404, "주문을 찾을 수 없습니다")

    # DB 저장 (마켓 전송 성공 여부와 무관하게 항상 저장)
    await svc.update_order(
        order_id,
        {
            "shipping_company": body.shipping_company,
            "tracking_number": body.tracking_number,
        },
    )

    # 마켓 송장 전송
    market_sent = False
    market_msg = ""

    try:
        if order.channel_id and order.order_number:
            from backend.domain.samba.account.repository import (
                SambaMarketAccountRepository,
            )

            account_repo = SambaMarketAccountRepository(session)
            account = await account_repo.get_async(order.channel_id)

            if account and account.market_type == "lotteon":
                from backend.domain.samba.proxy.lotteon import LotteonClient
                from backend.domain.samba.forbidden.repository import (
                    SambaSettingsRepository,
                )

                lo_api_key = (
                    (account.additional_fields or {}).get("apiKey", "")
                    or account.api_key
                    or ""
                )
                if not lo_api_key:
                    _lo_repo = SambaSettingsRepository(session)
                    _lo_row = await _lo_repo.find_by_async(key="store_lotteon")
                    if _lo_row and isinstance(_lo_row.value, dict):
                        lo_api_key = _lo_row.value.get("apiKey", "")
                if lo_api_key:
                    client = LotteonClient(lo_api_key)
                    await client.test_auth()
                    sent = await client.ship_order(
                        od_no=order.od_no or order.order_number,
                        od_seq=order.od_seq or "1",
                        proc_seq=order.proc_seq or "1",
                        sitm_no=order.sitm_no or order.shipment_id or "",
                        spd_no=order.product_id or "",
                        quantity=order.quantity or 1,
                        shipping_company=body.shipping_company,
                        tracking_number=body.tracking_number,
                    )
                    if sent:
                        market_sent = True
                        market_msg = "롯데ON 송장 등록 완료"
                        await svc.update_order(
                            order_id,
                            {"shipping_status": "송장전송완료", "status": "shipping"},
                        )
                    else:
                        market_msg = "롯데ON 송장 등록 실패 (로그 확인)"

            elif account and account.market_type == "smartstore":
                from backend.domain.samba.proxy.smartstore import SmartStoreClient
                from backend.domain.samba.forbidden.repository import (
                    SambaSettingsRepository,
                )

                _ss_extras = account.additional_fields or {}
                ss_client_id = _ss_extras.get("clientId", "") or account.api_key or ""
                ss_client_secret = (
                    _ss_extras.get("clientSecret", "") or account.api_secret or ""
                )
                if not ss_client_id or not ss_client_secret:
                    _ss_repo = SambaSettingsRepository(session)
                    _ss_row = await _ss_repo.find_by_async(key="store_smartstore")
                    if _ss_row and isinstance(_ss_row.value, dict):
                        ss_client_id = ss_client_id or _ss_row.value.get("clientId", "")
                        ss_client_secret = ss_client_secret or _ss_row.value.get(
                            "clientSecret", ""
                        )
                if ss_client_id and ss_client_secret:
                    client = SmartStoreClient(ss_client_id, ss_client_secret)
                    await client.ship_product_order(
                        order.order_number,
                        body.shipping_company,
                        body.tracking_number,
                    )
                    market_sent = True
                    market_msg = "스마트스토어 송장 전송 완료"
                    await svc.update_order(
                        order_id, {"shipping_status": "송장전송완료"}
                    )

            elif account and account.market_type == "ebay":
                from backend.domain.samba.proxy.ebay import (
                    EbayApiError,
                    EbayClient,
                )

                extras = account.additional_fields or {}
                app_id = (
                    extras.get("clientId")
                    or extras.get("appId")
                    or account.api_key
                    or ""
                )
                cert_id = (
                    extras.get("clientSecret")
                    or extras.get("certId")
                    or account.api_secret
                    or ""
                )
                refresh_token = (
                    extras.get("oauthToken") or extras.get("authToken", "") or ""
                )
                if app_id and cert_id and refresh_token:
                    ebay_client = EbayClient(
                        app_id=app_id,
                        dev_id="",
                        cert_id=cert_id,
                        refresh_token=refresh_token,
                        sandbox=bool(extras.get("sandbox", False)),
                    )
                    # 배송사 한글→eBay carrier code 매핑
                    # eBay US는 한국 택배사 미지원 — 전부 KoreaPost로 매핑
                    # (USPS/UPS/FedEx/DHL만 공식 지원, 한국 택배사는 KoreaPost가 유일)
                    carrier_map = {
                        "USPS": "USPS",
                        "UPS": "UPS",
                        "FedEx": "FEDEX",
                        "DHL": "DHL",
                    }
                    ebay_carrier = carrier_map.get(body.shipping_company, "KoreaPost")
                    try:
                        # ext_order_number에 orderId, order_number에 legacyOrderId
                        ebay_order_id = order.ext_order_number or order.order_number
                        await ebay_client.ship_order(
                            order_id=ebay_order_id,
                            tracking_number=body.tracking_number,
                            carrier_code=ebay_carrier,
                        )
                        market_sent = True
                        market_msg = "eBay 송장 전송 완료"
                        await svc.update_order(
                            order_id,
                            {
                                "shipping_status": "송장전송완료",
                                "status": "shipping",
                            },
                        )
                    except EbayApiError as e:
                        market_msg = f"eBay 송장 실패: {e}"
    except Exception as e:
        market_msg = f"송장 전송 실패: {e}"
        logger.warning(f"[송장전송] {order.order_number}: {e}")

    return {
        "ok": True,
        "market_sent": market_sent,
        "message": market_msg or "송장번호 저장 완료",
    }


# ══════════════════════════════════════════════
# URL에서 상품 대표이미지 추출
# ══════════════════════════════════════════════


@router.post("/fetch-product-image")
async def fetch_product_image(
    body: FetchProductImageRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """URL에서 상품 대표이미지를 추출해 반환."""
    from urllib.parse import urlparse

    import httpx

    url = body.url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "올바른 URL을 입력해주세요")

    parsed = urlparse(url)
    host = parsed.hostname or ""

    try:
        # ── 무신사 ──
        if "musinsa.com" in host:
            # URL에서 상품번호 추출: /products/1234 또는 /app/goods/1234
            m = re.search(r"(?:/products/|/app/goods/|/goods/)(\d+)", url)
            if not m:
                raise HTTPException(400, "무신사 상품번호를 URL에서 추출할 수 없습니다")
            goods_no = m.group(1)

            from backend.domain.samba.proxy.musinsa import MusinsaClient

            # 쿠키 로드
            from backend.domain.samba.forbidden.repository import (
                SambaSettingsRepository,
            )

            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="musinsa_cookie")
            cookie = ""
            if row and row.value:
                cookie = str(row.value)
            client = MusinsaClient(cookie=cookie)
            detail = await client.get_goods_detail(goods_no)
            images = detail.get("images", [])
            if images:
                return {"image_url": images[0]}
            raise HTTPException(404, "무신사 상품에서 이미지를 찾을 수 없습니다")

        # ── KREAM ──
        elif "kream.co.kr" in host:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as hc:
                resp = await hc.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                )
                text = resp.text
            m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', text)
            if m:
                return {"image_url": m.group(1).split("?")[0]}
            raise HTTPException(404, "KREAM 상품에서 이미지를 찾을 수 없습니다")

        # ── 범용 fallback (og:image) ──
        else:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as hc:
                resp = await hc.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                )
                text = resp.text
            # og:image 추출
            m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', text)
            if not m:
                # content가 앞에 오는 경우도 처리
                m = re.search(
                    r'<meta[^>]+content="([^"]*)"[^>]+property="og:image"', text
                )
            if m:
                return {"image_url": m.group(1)}
            raise HTTPException(404, "해당 페이지에서 대표이미지를 찾을 수 없습니다")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[fetch-product-image] 이미지 추출 실패: {e}")
        raise HTTPException(500, f"이미지 추출 중 오류: {str(e)}")


# ══════════════════════════════════════════════
# 마켓 주문 동기화
# ══════════════════════════════════════════════


class SyncOrdersRequest(BaseModel):
    days: int = 7
    account_id: Optional[str] = None  # 특정 계정만 동기화


@router.post("/sync-from-markets")
async def sync_orders_from_markets(
    body: SyncOrdersRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """활성 마켓 계정에서 주문 데이터를 가져와 DB에 저장."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    account_repo = SambaMarketAccountRepository(session)

    # 특정 계정 또는 전체 활성 계정
    if body.account_id:
        target = await account_repo.get_async(body.account_id)
        if not target:
            active_accounts = []
        else:
            # 테넌트 소유권 검증
            if tenant_id is not None and target.tenant_id != tenant_id:
                raise HTTPException(403, "해당 계정에 대한 권한이 없습니다")
            active_accounts = [target]
    else:
        # 테넌트 필터링: tenant_id가 있으면 해당 테넌트 계정만 조회
        if tenant_id is not None:
            active_accounts = await account_repo.filter_by_async(
                is_active=True, order_by="created_at", order_by_desc=True
            )
            # in-memory 필터링으로 tenant_id 또는 None(공용) 계정만 유지
            active_accounts = [
                a
                for a in active_accounts
                if a.tenant_id == tenant_id or a.tenant_id is None
            ]
        else:
            active_accounts = await account_repo.filter_by_async(
                is_active=True, order_by="created_at", order_by_desc=True
            )

    svc = _write_service(session)
    results: list[dict[str, Any]] = []
    total_synced = 0

    # ORM 객체를 딕셔너리로 미리 추출 — rollback 후 lazy loading MissingGreenlet 방지
    account_snapshots = [
        {
            "id": a.id,
            "market_type": a.market_type,
            "market_name": a.market_name,
            "seller_id": a.seller_id or "",
            "api_key": a.api_key,
            "api_secret": a.api_secret,
            "additional_fields": a.additional_fields or {},
            "tenant_id": a.tenant_id,
        }
        for a in active_accounts
    ]

    # 소싱처별 원문 URL 템플릿 (상수)
    _sourcing_urls = {
        "MUSINSA": "https://www.musinsa.com/products/{}",
        "KREAM": "https://kream.co.kr/products/{}",
        "FashionPlus": "https://www.fashionplus.co.kr/goods/detail/{}",
        "ABCmart": "https://www.a-rt.com/product?prdtNo={}",
        "GrandStage": "https://www.a-rt.com/product?prdtNo={}",
        "REXMONDE": "https://www.okmall.com/products/detail/{}",
        "LOTTEON": "https://www.lotteon.com/p/product/{}",
        "GSShop": "https://www.gsshop.com/prd/prd.gs?prdid={}",
        "ElandMall": "https://www.elandmall.com/goods/goods.action?goodsNo={}",
        "SSF": "https://www.ssfshop.com/goods/{}",
        "SSG": "https://www.ssg.com/item/itemView.ssg?itemId={}",
        "Nike": "https://www.nike.com/kr/t/{}",
        "Adidas": "https://www.adidas.co.kr/{}.html",
    }

    for account in account_snapshots:
        market_type = account["market_type"]
        extras = account["additional_fields"]
        seller_id = account["seller_id"]
        label = f"{account['market_name']}({seller_id})"

        try:
            orders_data: list[dict[str, Any]] = []
            unconfirmed_ids: list[str] = []

            if market_type == "smartstore":
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                client_id = extras.get("clientId", "") or account["api_key"] or ""
                client_secret = (
                    extras.get("clientSecret", "") or account["api_secret"] or ""
                )
                if not client_id or not client_secret:
                    # fallback: 공유 설정
                    settings_repo = SambaSettingsRepository(session)
                    row = await settings_repo.find_by_async(key="store_smartstore")
                    if row and isinstance(row.value, dict):
                        client_id = client_id or row.value.get("clientId", "")
                        client_secret = client_secret or row.value.get(
                            "clientSecret", ""
                        )
                if not client_id or not client_secret:
                    results.append(
                        {"account": label, "status": "skip", "message": "인증정보 없음"}
                    )
                    continue
                client = SmartStoreClient(client_id, client_secret)
                raw_orders = await client.get_orders(days=body.days)
                # 발주 미확인(PAYED) 주문 자동 발주확인
                unconfirmed_ids = []
                for ro in raw_orders:
                    po = ro.get("productOrder", ro)
                    order_info = ro.get("order", {})
                    # 클레임 정보: claim / cancel / currentClaim 순으로 확인
                    # 취소요청 시 응답 최상위에 'cancel' 키로 오는 경우 처리
                    claim_info = (
                        ro.get("claim")
                        or ro.get("cancel")
                        or ro.get("currentClaim")
                        or po.get("claim")
                        or {}
                    )
                    orders_data.append(
                        _parse_smartstore_order(
                            po, order_info, account["id"], label, claim_info=claim_info
                        )
                    )
                    if (
                        po.get("placeOrderStatus") == "NOT_YET"
                        and po.get("productOrderStatus") == "PAYED"
                    ):
                        unconfirmed_ids.append(po.get("productOrderId", ""))
                # 발주확인 실행
                if unconfirmed_ids:
                    try:
                        await client.confirm_product_orders(unconfirmed_ids)
                        logger.info(
                            f"[주문동기화] {label}: {len(unconfirmed_ids)}건 발주확인 완료"
                        )
                    except Exception as ce:
                        logger.warning(f"[주문동기화] {label}: 발주확인 실패 — {ce}")

                # last-changed API 권한 제한 보완:
                # DB에 있는 미완결 주문을 직접 재조회하여 배송완료/취소요청 등 최신 상태 반영
                _pending_statuses = {
                    "발주미확인",
                    "발송대기",
                    "결제완료",
                    "배송대기중",
                    "송장전송완료",
                    "배송중",
                }
                _already_fetched = {
                    d["order_number"] for d in orders_data if d.get("order_number")
                }
                from sqlalchemy import select as _sa_select
                from backend.domain.samba.order.model import SambaOrder as _SambaOrder
                from datetime import datetime as _dt, timedelta, timezone as _tz

                _cutoff = _dt.now(_tz.utc) - timedelta(days=max(body.days, 30))
                _stmt = (
                    _sa_select(_SambaOrder.order_number)
                    .where(
                        _SambaOrder.channel_id == account["id"],
                        _SambaOrder.shipping_status.in_(_pending_statuses),
                        _SambaOrder.updated_at >= _cutoff,
                    )
                    .limit(300)
                )
                _res = await session.execute(_stmt)
                _pending_numbers = [
                    r[0]
                    for r in _res.fetchall()
                    if r[0] and r[0] not in _already_fetched
                ]
                if _pending_numbers:
                    logger.info(
                        f"[주문동기화] {label}: 미완결 주문 {len(_pending_numbers)}건 직접 재조회"
                    )
                    try:
                        _extra_raws = await client.get_product_orders_by_ids(
                            _pending_numbers
                        )
                        for ro2 in _extra_raws:
                            po2 = ro2.get("productOrder", ro2)
                            order_info2 = ro2.get("order", {})
                            claim_info2 = (
                                ro2.get("claim")
                                or ro2.get("cancel")
                                or ro2.get("currentClaim")
                                or po2.get("claim")
                                or {}
                            )
                            orders_data.append(
                                _parse_smartstore_order(
                                    po2,
                                    order_info2,
                                    account["id"],
                                    label,
                                    claim_info=claim_info2,
                                )
                            )
                    except Exception as _ex:
                        logger.warning(
                            f"[주문동기화] {label}: 미완결 주문 직접 재조회 실패 — {_ex}"
                        )

            elif market_type == "lotteon":
                from backend.domain.samba.proxy.lotteon import LotteonClient

                api_key = extras.get("apiKey", "") or account["api_key"] or ""
                if not api_key:
                    results.append(
                        {
                            "account": label,
                            "status": "skip",
                            "message": "롯데ON API Key 없음",
                        }
                    )
                    continue
                lotteon_client = LotteonClient(api_key)
                await lotteon_client.test_auth()
                raw_orders = await lotteon_client.get_delivery_orders(days=body.days)
                logger.info(
                    f"[주문동기화] {label}: 롯데ON 주문 {len(raw_orders)}건 조회"
                )
                # 신규주문(odPrgsStepCd=11=출고지시) 자동 연동완료 통보 대상 수집
                # SellerDeliveryOrdersSearch는 11(출고지시)/23(회수지시)만 반환 — "10"은 영원히 안 잡힘(공식 문서 기준)
                # SellerIfCompleteInform(ifCplYN=Y) 호출 시 롯데ON에서 자동으로 11→12(상품준비)로 전이됨
                lotteon_confirmed_count = 0
                unconfirmed_items: list[dict] = []
                for ro in raw_orders:
                    orders_data.append(_parse_lotteon_order(ro, account["id"], label))
                    step_cd = str(ro.get("odPrgsStepCd", "") or "")
                    if step_cd == "11":
                        unconfirmed_items.append(
                            {
                                "odNo": ro.get("odNo", ""),
                                "odSeq": ro.get("odSeq", 1) or 1,
                                "procSeq": ro.get("procSeq", 1) or 1,
                            }
                        )

                # 주문확인(SellerIfCompleteInform, ifCplYN=Y) 일괄 실행 — 호출 후 셀러센터에서 상품준비중 자동 전이
                if unconfirmed_items:
                    try:
                        ok = await lotteon_client.confirm_orders(unconfirmed_items)
                        if ok:
                            lotteon_confirmed_count = len(unconfirmed_items)
                            logger.info(
                                f"[주문동기화] {label}: {len(unconfirmed_items)}건 주문확인 완료 (출고지시→상품준비중 자동 전이)"
                            )
                            # 로컬 표시도 즉시 상품준비중으로 갱신 (다음 sync까지 기다리지 않음)
                            _confirmed_keys = {
                                f"{it['odNo']}_{it['odSeq']}_{it['procSeq']}"
                                for it in unconfirmed_items
                            }
                            for od in orders_data:
                                if (
                                    od.get("source") == "lotteon"
                                    and od.get("order_number") in _confirmed_keys
                                    and od.get("shipping_status")
                                    in ("발주확인대기", "출고지시")
                                ):
                                    od["shipping_status"] = "상품준비"
                                    od["status"] = "preparing"
                        else:
                            logger.warning(
                                f"[주문동기화] {label}: 주문확인 API 응답 실패(rsltCd != 0000)"
                            )
                    except Exception as ce:
                        logger.warning(f"[주문동기화] {label}: 주문확인 실패 — {ce}")

                # ── 정산예상 계산용 raw 필드 매핑 (샵마인 정산공식 채택) ─────────
                # 샵마인 분해표 검증으로 확정된 공식(2026-04-25):
                #   고객결제금액   = slAmt − fvrAmtSum
                #   중개수수료총합 = bseCmsn(기본) + pcsCmsn(제휴) + dvCmsn(배송비) − ajstDcAmt(조정=롯데부담)
                #   정산예정      = 고객결제금액 − 중개수수료총합
                # 기존 sptDcPgmCmsnSum 차감 로직은 셀러부담할인을 이중 차감하는 버그였음.
                # raw 응답 필드명이 미확정인 항목은 후보 키 폴백으로 호환.
                sl_amt_map: dict[str, int] = {}  # 총판매금액 (slAmt)
                fvr_amt_map: dict[str, int] = {}  # 전체 할인합 (셀러+롯데)
                bse_cmsn_map: dict[str, int] = {}  # 기본수수료
                pcs_cmsn_map: dict[str, int] = {}  # PCS/제휴 수수료
                dv_cmsn_map: dict[str, int] = {}  # 배송비 수수료
                ajst_dc_map: dict[str, int] = {}  # 조정(할인) = 롯데부담

                def _pick(d: dict, *keys: str) -> int:
                    for k in keys:
                        v = d.get(k)
                        if v not in (None, "", 0, "0"):
                            try:
                                return int(float(v))
                            except (TypeError, ValueError):
                                continue
                    return 0

                for ro in raw_orders:
                    _od_no = str(ro.get("odNo") or "")
                    if not _od_no:
                        continue
                    _slamt = _pick(ro, "slAmt", "slPrc")
                    _fvr = _pick(ro, "fvrAmtSum", "tdscAmtSum", "totDcAmt")
                    _bse = _pick(ro, "bseCmsn", "bseCmsnAmt")
                    _pcs = _pick(ro, "pcsCmsn", "pcsCmsnAmt", "pgCmsnAmt")
                    _dv = _pick(ro, "dvCmsn", "dvCstCmsnAmt")
                    _ajst = _pick(ro, "ajstDcAmt", "ajstDcSptAmt")
                    if _slamt > sl_amt_map.get(_od_no, 0):
                        sl_amt_map[_od_no] = _slamt
                    if _fvr > fvr_amt_map.get(_od_no, 0):
                        fvr_amt_map[_od_no] = _fvr
                    if _bse > bse_cmsn_map.get(_od_no, 0):
                        bse_cmsn_map[_od_no] = _bse
                    if _pcs > pcs_cmsn_map.get(_od_no, 0):
                        pcs_cmsn_map[_od_no] = _pcs
                    if _dv > dv_cmsn_map.get(_od_no, 0):
                        dv_cmsn_map[_od_no] = _dv
                    if _ajst > ajst_dc_map.get(_od_no, 0):
                        ajst_dc_map[_od_no] = _ajst
                logger.info(
                    f"[주문동기화] {label}: 정산필드 매핑 {len(sl_amt_map)}건 "
                    f"(raw_orders {len(raw_orders)}건)"
                )
                # raw 응답에 수수료 필드가 실제로 존재하는지 1회 디버그 출력
                if raw_orders:
                    _sample = raw_orders[0]
                    _cmsn_keys = [
                        k
                        for k in _sample.keys()
                        if any(t in k.lower() for t in ("cmsn", "fvr", "ajst", "dc"))
                    ]
                    logger.info(
                        f"[주문동기화] {label}: 정산필드 후보 키 = {_cmsn_keys}"
                    )

                # ── 정산금액 매칭 (SettleItmdSales) ─────────────────────────
                # 정산 데이터는 배송완료 → 구매확정 후 수일 지나서 생성되므로
                # 주문 조회 기간(body.days)보다 넓게(최대 30일) 조회해야 매칭률 ↑.
                # 최대값 30은 api_client.get_settlement_items 내부에서 cap.
                try:
                    settle_items = await lotteon_client.get_settlement_items(days=30)
                    # (odNo, odSeq, procSeq) → 정산 데이터 매핑
                    settle_map: dict[tuple[str, str, str], dict] = {}
                    for si in settle_items:
                        key = (
                            str(si.get("odNo", "")),
                            str(si.get("odSeq", "")),
                            str(si.get("procSeq", "")),
                        )
                        settle_map[key] = si
                    # 매출 주문에 매칭 → revenue/fee_rate 갱신
                    matched = 0
                    for i, ro in enumerate(raw_orders):
                        key = (
                            str(ro.get("odNo", "")),
                            str(ro.get("odSeq", "1")),
                            str(ro.get("procSeq", "1")),
                        )
                        si = settle_map.get(key)
                        if not si:
                            continue
                        pymt_amt = float(si.get("pymtAmt", 0) or 0)
                        sl_amt = float(si.get("slAmt", 0) or 0)
                        sl_qty = float(si.get("slQty", 1) or 1)
                        gross = sl_amt * sl_qty
                        # 고객결제금액 = 총판매 - 셀러부담할인 - 상품할인(셀러+이커머스)
                        slr_dc = float(si.get("slrDcAmt", 0) or 0)
                        pd_dc_slr = float(si.get("pdDcSlrAmt", 0) or 0)
                        pd_dc_oco = float(si.get("pdDcOcoAmt", 0) or 0)
                        customer_paid = max(0.0, gross - slr_dc - pd_dc_slr - pd_dc_oco)
                        if pymt_amt > 0 and customer_paid > 0:
                            fee_rate = round((1 - pymt_amt / customer_paid) * 100, 2)
                            orders_data[i]["revenue"] = pymt_amt
                            orders_data[i]["fee_rate"] = fee_rate
                            orders_data[i]["total_payment_amount"] = customer_paid
                            matched += 1
                        elif pymt_amt > 0 and gross > 0:
                            # 할인 필드가 비어 있으면 기존 방식(총판매 기준)으로 폴백
                            fee_rate = round((1 - pymt_amt / gross) * 100, 2)
                            orders_data[i]["revenue"] = pymt_amt
                            orders_data[i]["fee_rate"] = fee_rate
                            matched += 1
                    logger.info(
                        f"[주문동기화] {label}: 정산 매칭 {matched}/{len(raw_orders)}건 "
                        f"(정산 API {len(settle_items)}건)"
                    )
                except Exception as se:
                    logger.warning(f"[주문동기화] {label}: 정산 조회 실패 — {se}")

                # 발주확인은 수동 처리 (원소싱처 재고/가격 확인 후 사용자가 결정)
                # 교환 클레임 조회 → 기존 주문 shipping_status 업데이트
                try:
                    exchange_claims = await lotteon_client.get_exchanges(days=body.days)
                    logger.info(f"[롯데ON] 교환 클레임 조회: {len(exchange_claims)}건")
                    if exchange_claims:
                        exchange_step_map = {
                            "21": "교환요청",
                            "22": "교환회수완료",
                            "23": "교환회수완료",
                            "24": "교환재배송",
                            "25": "교환완료",
                        }
                        exchange_priority = {
                            "교환요청": 1,
                            "교환회수완료": 2,
                            "교환재배송": 3,
                            "교환완료": 4,
                        }
                        for claim in exchange_claims:
                            ex_od_no = claim.get("odNo", "")
                            clm_no = claim.get("clmNo", "")
                            step_cd = str(claim.get("odPrgsStepCd", "") or "")
                            ex_status = exchange_step_map.get(step_cd, "교환요청")
                            logger.info(
                                f"[롯데ON][교환클레임] odNo={ex_od_no} clmNo={clm_no} stepCd={step_cd} → {ex_status}"
                            )
                            found_in_data = False
                            for od in orders_data:
                                # order_number는 합성키(odNo_odSeq_procSeq)이므로 od_no로 비교
                                if od.get("od_no") == ex_od_no:
                                    cur_status = od.get("shipping_status", "")
                                    cur_p = exchange_priority.get(cur_status, 0)
                                    new_p = exchange_priority.get(ex_status, 0)
                                    if cur_p == 0 or new_p >= cur_p:
                                        od["shipping_status"] = ex_status
                                        if step_cd in ("21", "22", "23"):
                                            od["status"] = "return_requested"
                                    found_in_data = True
                                    break
                            if not found_in_data and ex_od_no:
                                from sqlalchemy import text as _sa_text_ex

                                _ex_row = await session.execute(
                                    _sa_text_ex(
                                        "SELECT id FROM samba_order "
                                        "WHERE source = 'lotteon' AND od_no = :od_no LIMIT 1"
                                    ),
                                    {"od_no": ex_od_no},
                                )
                                _ex_id = (_ex_row.fetchone() or [None])[0]
                                existing = (
                                    await svc.repo.get_async(_ex_id) if _ex_id else None
                                )
                                if existing:
                                    cur_p = exchange_priority.get(
                                        existing.shipping_status, 0
                                    )
                                    new_p = exchange_priority.get(ex_status, 0)
                                    if cur_p == 0 or new_p >= cur_p:
                                        update_ex: dict[str, Any] = {
                                            "shipping_status": ex_status
                                        }
                                        if step_cd in ("21", "22", "23"):
                                            update_ex["status"] = "return_requested"
                                        await svc.update_order(existing.id, update_ex)
                                        logger.info(
                                            f"[롯데ON][교환클레임] DB 직접 업데이트: {ex_od_no} → {ex_status}"
                                        )
                except Exception as ex_err:
                    logger.warning(f"[롯데ON] 교환 클레임 조회 실패: {ex_err}")
            elif market_type == "playauto":
                from datetime import UTC, datetime, timedelta

                from backend.domain.samba.proxy.playauto import PlayAutoClient

                api_key = extras.get("apiKey", "") or account["api_key"] or ""
                if not api_key:
                    results.append(
                        {"account": label, "status": "skip", "message": "API Key 없음"}
                    )
                    continue
                # 별칭 매핑 로드 (store_playauto 설정에서)
                alias_map: dict[str, str] = {}
                try:
                    settings_repo = SambaSettingsRepository(session)
                    pa_setting = await settings_repo.find_by_async(key="store_playauto")
                    if pa_setting and isinstance(pa_setting.value, dict):
                        for ak in ("alias1", "alias2", "alias3"):
                            av = pa_setting.value.get(ak, "")
                            if av and "-" in av:
                                code, nick = av.split("-", 1)
                                alias_map[code.strip()] = nick.strip()
                except Exception:
                    pass
                pa_client = PlayAutoClient(api_key)
                try:
                    start_date = (
                        datetime.now(UTC) - timedelta(days=body.days)
                    ).strftime("%Y%m%d")
                    # 전체 상태 한번에 조회 (상태 필터 없이)
                    raw_orders = await pa_client.get_orders(
                        start_date=start_date,
                        count=500,
                    )
                    logger.info(f"[주문동기화] 플레이오토: {len(raw_orders)}건 조회")
                    for ro in raw_orders:
                        # 파생 주문 스킵 (사본-취소마감, ★교환주문 — 원주문에 이미 정보 포함)
                        _pname = ro.get("ProdName", "")
                        if _pname.startswith("[사본-") or "★교환주문" in _pname:
                            continue
                        orders_data.append(
                            _parse_playauto_order(ro, account["id"], label, alias_map)
                        )
                except Exception as e:
                    logger.warning(f"[주문동기화] {label}: 플레이오토 조회 실패 — {e}")
                    results.append(
                        {"account": label, "status": "error", "message": str(e)[:100]}
                    )
                    continue
                finally:
                    await pa_client.close()
            elif market_type == "coupang":
                from backend.domain.samba.proxy.coupang import CoupangClient

                access_key = (
                    extras.get("accessKey", "") or account.get("api_key", "") or ""
                )
                secret_key = (
                    extras.get("secretKey", "") or account.get("api_secret", "") or ""
                )
                vendor_id = extras.get("vendorId", "") or seller_id or ""

                if not all([access_key, secret_key, vendor_id]):
                    results.append(
                        {
                            "account": label,
                            "status": "skip",
                            "message": "쿠팡 인증정보 없음 (accessKey/secretKey/vendorId)",
                        }
                    )
                    continue

                client = CoupangClient(access_key, secret_key, vendor_id)
                try:
                    raw_orders = await client.get_orders(days=body.days)
                    logger.info(f"[주문동기화] 쿠팡({label}): {len(raw_orders)}건 조회")
                    for ro in raw_orders:
                        try:
                            orders_data.append(
                                _parse_coupang_order(ro, account["id"], label)
                            )
                        except Exception as parse_err:
                            logger.warning(f"[주문동기화] 쿠팡 파싱 실패: {parse_err}")
                            continue
                except Exception as e:
                    logger.warning(f"[주문동기화] {label}: 쿠팡 조회 실패 — {e}")
                    results.append(
                        {"account": label, "status": "error", "message": str(e)[:100]}
                    )
                    continue
            elif market_type == "11st":
                # 11번가 주문 조회 (구현 대기)
                results.append(
                    {
                        "account": label,
                        "status": "skip",
                        "message": "11번가 주문 조회 미구현",
                    }
                )
                continue
            elif market_type == "ebay":
                from backend.domain.samba.proxy.ebay import (
                    EbayApiError,
                    EbayClient,
                )

                app_id = (
                    extras.get("clientId") or extras.get("appId") or account["api_key"]
                )
                cert_id = (
                    extras.get("clientSecret")
                    or extras.get("certId")
                    or account["api_secret"]
                )
                refresh_token = extras.get("oauthToken") or extras.get("authToken", "")
                # SambaSettings 폴백
                if not (app_id and cert_id and refresh_token):
                    settings_repo = SambaSettingsRepository(session)
                    row = await settings_repo.find_by_async(key="store_ebay")
                    if row and isinstance(row.value, dict):
                        app_id = (
                            app_id
                            or row.value.get("clientId", "")
                            or row.value.get("appId", "")
                        )
                        cert_id = (
                            cert_id
                            or row.value.get("clientSecret", "")
                            or row.value.get("certId", "")
                        )
                        refresh_token = (
                            refresh_token
                            or row.value.get("oauthToken", "")
                            or row.value.get("authToken", "")
                        )
                if not (app_id and cert_id and refresh_token):
                    results.append(
                        {
                            "account": label,
                            "status": "skip",
                            "message": "eBay 인증정보 없음",
                        }
                    )
                    continue

                ebay_client = EbayClient(
                    app_id=app_id,
                    dev_id="",
                    cert_id=cert_id,
                    refresh_token=refresh_token,
                    sandbox=bool(extras.get("sandbox", False)),
                )
                try:
                    raw_orders = await ebay_client.get_orders(days=body.days)
                except EbayApiError as e:
                    err = str(e)
                    if (
                        "scope" in err.lower()
                        or "invalid_scope" in err.lower()
                        or "insufficient" in err.lower()
                    ):
                        results.append(
                            {
                                "account": label,
                                "status": "error",
                                "message": "sell.fulfillment scope 누락 — eBay 재인증 필요",
                            }
                        )
                    else:
                        results.append(
                            {
                                "account": label,
                                "status": "error",
                                "message": err[:150],
                            }
                        )
                    continue

                logger.info(f"[주문동기화] {label}: eBay 주문 {len(raw_orders)}건 조회")

                # USD → KRW 환율 (exchange_rate_service의 USD effectiveRate 우선)
                ebay_exchange_rate = 1400.0
                try:
                    from backend.domain.samba.exchange_rate_service import (
                        build_exchange_rate_response,
                        get_exchange_rate_settings,
                        get_latest_exchange_rates,
                    )

                    _er_settings = await get_exchange_rate_settings(
                        session, account["tenant_id"] or tenant_id
                    )
                    _er_latest = await get_latest_exchange_rates()
                    _er_resp = build_exchange_rate_response(_er_settings, _er_latest)
                    _usd_info = _er_resp.get("currencies", {}).get("USD", {}) or {}
                    _eff_rate = float(_usd_info.get("effectiveRate") or 0)
                    if _eff_rate > 0:
                        ebay_exchange_rate = _eff_rate
                except Exception as e:
                    logger.warning(
                        f"[주문동기화] {label}: 환율 조회 실패, 폴백 1400 사용 — {e}"
                    )

                for ro in raw_orders:
                    orders_data.append(
                        _parse_ebay_order(ro, account["id"], label, ebay_exchange_rate)
                    )

                # Finance API 실제 정산액 조회 — orderId → (net_usd, fee_usd) 매핑
                # sell.finances scope 필요. 방금 들어온 주문은 거래 미확정 상태라 매핑 없을 수 있음
                try:
                    tx_list = await ebay_client.get_transactions(days=body.days)
                    # Finance API 응답 필드:
                    #   amount                = net (이미 수수료 차감된 값)
                    #   totalFeeBasisAmount   = gross (판매가)
                    #   totalFeeAmount        = 실제 수수료
                    # 같은 orderId에 여러 거래(SALE, SHIPPING_LABEL 등) 있을 수 있음 → 누적
                    tx_map: dict[str, dict[str, float]] = {}
                    for tx in tx_list:
                        oid = tx.get("orderId", "") or ""
                        if not oid:
                            continue
                        net = float((tx.get("amount") or {}).get("value", 0) or 0)
                        gross = float(
                            (tx.get("totalFeeBasisAmount") or {}).get("value", 0) or 0
                        )
                        fee = float(
                            (tx.get("totalFeeAmount") or {}).get("value", 0) or 0
                        )
                        booking = tx.get("bookingEntry", "CREDIT")
                        tx_type = tx.get("transactionType", "")
                        tx_id = tx.get("transactionId", "")
                        tx_status = tx.get("transactionStatus", "")
                        logger.info(
                            "[eBay Finance tx] order=%s type=%s book=%s status=%s "
                            "gross=%.2f fee=%.2f net=%.2f id=%s",
                            oid,
                            tx_type,
                            booking,
                            tx_status,
                            gross,
                            fee,
                            net,
                            tx_id,
                        )
                        # DEBIT = 판매자 잔액 차감 (환불, 배송라벨 등)
                        if booking == "DEBIT":
                            net = -net
                            gross = -gross
                            fee = -fee
                        cur = tx_map.setdefault(
                            oid, {"net": 0.0, "gross": 0.0, "fee": 0.0}
                        )
                        cur["net"] += net
                        cur["gross"] += gross
                        cur["fee"] += fee

                    matched = 0
                    for od in orders_data:
                        oid = od.get("ext_order_number") or ""
                        if oid in tx_map:
                            net_usd = tx_map[oid]["net"]
                            gross_usd = tx_map[oid]["gross"]
                            fee_usd = tx_map[oid]["fee"]
                            od["revenue"] = int(round(net_usd * ebay_exchange_rate))
                            if gross_usd > 0:
                                od["fee_rate"] = round(fee_usd / gross_usd * 100, 2)
                            od["notes"] = (
                                f"gross ${gross_usd:.2f} - fee ${fee_usd:.2f} "
                                f"= net ${net_usd:.2f} @ {ebay_exchange_rate:.2f}원/USD "
                                f"(Finance API)"
                            )
                            matched += 1
                    logger.info(
                        f"[주문동기화] {label}: Finance 실제 정산 매칭 "
                        f"{matched}/{len(orders_data)}건"
                    )
                except Exception as e:
                    logger.warning(
                        f"[주문동기화] {label}: Finance API 조회 실패 "
                        f"(예상 수수료 유지) — {e}"
                    )

                # 반품/취소 수집 (최근 90일 고정)
                try:
                    returns_raw = await ebay_client.get_returns(days=90)
                    cancellations_raw = await ebay_client.get_cancellations(days=90)
                    _apply_ebay_claims_to_orders(
                        orders_data, returns_raw, cancellations_raw
                    )
                    logger.info(
                        f"[주문동기화] {label}: eBay 반품 {len(returns_raw)}건 "
                        f"+ 취소 {len(cancellations_raw)}건 매칭 (90일)"
                    )
                except Exception as e:
                    logger.warning(
                        f"[주문동기화] {label}: eBay 반품/취소 조회 실패 — {e}"
                    )
            # (dead code 제거: 두 번째 롯데ON 블록 → 첫 번째에 병합 완료)
            else:
                results.append(
                    {
                        "account": label,
                        "status": "skip",
                        "message": f"{market_type} 주문 조회 미지원",
                    }
                )
                continue

            # 수집상품 매칭 캐시 구축 (마켓상품번호 → 이미지/소싱처)
            from sqlalchemy import text as _sa_text

            _cp_result = await session.execute(
                _sa_text(
                    "SELECT id, source_site, site_product_id, images, market_product_nos, source_url, category "
                    "FROM samba_collected_product WHERE market_product_nos IS NOT NULL LIMIT 50000"
                )
            )
            _mpn_cache: dict[str, dict] = {}
            for _row in _cp_result.fetchall():
                _cpid, _site, _spid, _imgs, _mpnos, _src_url, _cat = _row
                if _mpnos and isinstance(_mpnos, dict):
                    _thumb = (
                        _imgs[0] if _imgs and isinstance(_imgs, list) and _imgs else ""
                    )
                    # DB에 저장된 source_url 우선 사용 (수집기가 올바르게 저장한 URL)
                    _olink = _src_url or (
                        _sourcing_urls.get(_site, "").format(_spid)
                        if _site in _sourcing_urls and _spid
                        else ""
                    )
                    _entry = {
                        "collected_product_id": _cpid,
                        "source_site": _site,
                        "product_image": _thumb,
                        "original_link": _olink,
                        "category": _cat or "",
                    }
                    for _k, _v in _mpnos.items():
                        if not _v:
                            continue
                        if isinstance(_v, dict):
                            # 중첩 구조: {"originProductNo": "...", "smartstoreChannelProductNo": "..."}
                            for _sub_v in [
                                _v.get("smartstoreChannelProductNo"),
                                _v.get("originProductNo"),
                                _v.get("channelProductNo"),
                            ]:
                                if _sub_v:
                                    _mpn_cache[str(_sub_v)] = _entry
                        else:
                            _mpn_cache[str(_v)] = _entry

            # 미등록 입력 캐시: 동일 product_id+channel_name에 대해 수동 등록된 source_url/product_image 재활용
            _unreg_cache: dict[str, dict[str, str]] = {}
            _unreg_result = await session.execute(
                _sa_text(
                    "SELECT product_id, channel_name, source_url, product_image "
                    "FROM samba_order WHERE source_url IS NOT NULL AND product_id IS NOT NULL"
                )
            )
            for _ur in _unreg_result.fetchall():
                _ukey = f"{_ur[0]}|{_ur[1] or ''}"
                _unreg_cache[_ukey] = {
                    "source_url": _ur[2],
                    "product_image": _ur[3] or "",
                }

            # 중복 확인 후 저장 (기존 주문은 금액/상태 업데이트)
            synced = 0
            for order_data in orders_data:
                # tenant_id 주입 (멀티테넌트 격리 — account 우선, JWT fallback)
                _tid = account["tenant_id"] or tenant_id
                if _tid:
                    order_data["tenant_id"] = _tid
                # 수집상품 매칭 — collected_product_id, product_image, source_site, source_url 보충
                _pid = str(order_data.get("product_id", ""))
                _matched = _mpn_cache.get(_pid)
                if _matched:
                    if not order_data.get("collected_product_id"):
                        order_data["collected_product_id"] = _matched[
                            "collected_product_id"
                        ]
                    if not order_data.get("product_image"):
                        order_data["product_image"] = _matched["product_image"]
                    if not order_data.get("source_site"):
                        order_data["source_site"] = _matched["source_site"]
                    if not order_data.get("source_url") and _matched.get(
                        "original_link"
                    ):
                        order_data["source_url"] = _matched["original_link"]
                # 롯데ON 예상 정산금액 계산 (샵마인 정산공식, 2026-04-25 교체)
                #   고객결제금액   = slAmt − fvrAmtSum
                #   중개수수료총합 = bseCmsn + pcsCmsn + dvCmsn − ajstDcAmt
                #   정산예정      = 고객결제금액 − 중개수수료총합
                # 정산 API(SettleItmdSales) 매칭으로 이미 revenue가 세팅됐으면 확정값이므로 건드리지 않음.
                if order_data.get("source") == "lotteon":
                    _od_no = str(order_data.get("od_no") or "")
                    _slamt = int(sl_amt_map.get(_od_no, 0))
                    _fvr = int(fvr_amt_map.get(_od_no, 0))
                    _bse = int(bse_cmsn_map.get(_od_no, 0))
                    _pcs = int(pcs_cmsn_map.get(_od_no, 0))
                    _dv = int(dv_cmsn_map.get(_od_no, 0))
                    _ajst = int(ajst_dc_map.get(_od_no, 0))

                    if _slamt > 0:
                        _customer_paid = max(0, _slamt - _fvr)
                        order_data["total_payment_amount"] = _customer_paid

                        # revenue가 정산 API로 이미 채워진 경우 fee_rate만 재계산하여 일관성 유지
                        if not order_data.get("revenue"):
                            # 중개수수료: raw 응답에 수수료 필드가 있으면 정확 계산, 없으면 카테고리 폴백
                            if _bse > 0 or _pcs > 0 or _dv > 0:
                                _total_cmsn = max(0, _bse + _pcs + _dv - _ajst)
                            else:
                                from backend.domain.samba.proxy.lotteon.category_fees import (
                                    get_fee_rate_for_category,
                                )

                                _cat_for_fee = (
                                    _matched.get("category", "") if _matched else ""
                                )
                                _fee = get_fee_rate_for_category(_cat_for_fee)
                                _total_cmsn = int(_customer_paid * _fee / 100)

                            _revenue = max(0, _customer_paid - _total_cmsn)
                            order_data["revenue"] = _revenue
                            order_data["fee_rate"] = (
                                round(_total_cmsn / _customer_paid * 100, 2)
                                if _customer_paid > 0
                                else 0
                            )
                    elif not order_data.get("revenue"):
                        # raw 매핑 실패 폴백 — 카테고리 수수료 공식
                        from backend.domain.samba.proxy.lotteon.category_fees import (
                            get_fee_rate_for_category,
                        )

                        _cat_for_fee = _matched.get("category", "") if _matched else ""
                        _fee = get_fee_rate_for_category(_cat_for_fee)
                        _sp = int(order_data.get("sale_price", 0) or 0)
                        order_data["total_payment_amount"] = _sp
                        order_data["fee_rate"] = _fee
                        order_data["revenue"] = max(0, int(_sp * (1 - _fee / 100)))
                # 미등록 입력 자동 적용: 동일 상품의 기존 source_url/product_image 복사
                _ukey = f"{_pid}|{order_data.get('channel_name', '')}"
                _unreg_matched = _unreg_cache.get(_ukey)
                if _unreg_matched:
                    if not order_data.get("source_url"):
                        order_data["source_url"] = _unreg_matched["source_url"]
                    if (
                        not order_data.get("product_image")
                        and _unreg_matched["product_image"]
                    ):
                        order_data["product_image"] = _unreg_matched["product_image"]
                # 상품명에서 소싱처 상품번호 추출 → source_site/source_url 보충
                if not order_data.get("source_url"):
                    import re as _re

                    _pname = order_data.get("product_name", "")
                    _id_match = _re.search(r"\b(\d{6,})\s*$", _pname)
                    if _id_match:
                        _sid = _id_match.group(1)
                        # 1차: DB에서 수집상품 조회
                        _cp_check = await session.execute(
                            _sa_text(
                                "SELECT id, source_site, images FROM samba_collected_product WHERE site_product_id = :sid LIMIT 1"
                            ),
                            {"sid": _sid},
                        )
                        _cp_row = _cp_check.fetchone()
                        if _cp_row:
                            if not order_data.get("collected_product_id"):
                                order_data["collected_product_id"] = _cp_row[0]
                            order_data["source_site"] = _cp_row[1]
                            order_data["source_url"] = _sourcing_urls.get(
                                _cp_row[1], ""
                            ).format(_sid)
                            if (
                                not order_data.get("product_image")
                                and _cp_row[2]
                                and isinstance(_cp_row[2], list)
                            ):
                                order_data["product_image"] = _cp_row[2][0]
                        else:
                            # 2차: DB에 없어도 상품명 패턴으로 소싱처 추론
                            if len(_sid) >= 9:  # 패션플러스 상품번호는 9자리 이상
                                order_data["source_site"] = "FashionPlus"
                                order_data["source_url"] = (
                                    f"https://www.fashionplus.co.kr/goods/detail/{_sid}"
                                )
                            elif len(_sid) >= 7:  # 무신사 상품번호는 7자리
                                order_data["source_site"] = "MUSINSA"
                                order_data["source_url"] = (
                                    f"https://www.musinsa.com/products/{_sid}"
                                )
                # 중복 체크: 롯데ON은 od_no+od_seq+proc_seq 기반, 기타는 order_number 기반
                if order_data.get("source") == "lotteon" and order_data.get("od_no"):
                    _lo_row = await session.execute(
                        _sa_text(
                            "SELECT id FROM samba_order "
                            "WHERE source = 'lotteon' "
                            "AND tenant_id IS NOT DISTINCT FROM :tid "
                            "AND channel_id = :cid "
                            "AND od_no = :od_no "
                            "AND od_seq = :od_seq "
                            "AND proc_seq = :proc_seq "
                            "LIMIT 1"
                        ),
                        {
                            "tid": order_data.get("tenant_id"),
                            "cid": order_data.get("channel_id"),
                            "od_no": order_data["od_no"],
                            "od_seq": order_data.get("od_seq", "1"),
                            "proc_seq": order_data.get("proc_seq", "1"),
                        },
                    )
                    _lo_id = (_lo_row.fetchone() or [None])[0]
                    existing = await svc.repo.get_async(_lo_id) if _lo_id else None
                else:
                    _existing_row = await session.execute(
                        _sa_text(
                            "SELECT id FROM samba_order "
                            "WHERE order_number = :order_number "
                            "AND tenant_id IS NOT DISTINCT FROM :tid "
                            "AND channel_id IS NOT DISTINCT FROM :cid "
                            "ORDER BY created_at DESC "
                            "LIMIT 1"
                        ),
                        {
                            "order_number": order_data["order_number"],
                            "tid": order_data.get("tenant_id"),
                            "cid": order_data.get("channel_id"),
                        },
                    )
                    _existing_id = (_existing_row.fetchone() or [None])[0]
                    existing = (
                        await svc.repo.get_async(_existing_id) if _existing_id else None
                    )
                if (
                    not existing
                    and order_data.get("shipment_id")
                    and order_data.get("product_id")
                ):
                    # 같은 orderId + 상품번호로 이미 있는 주문 검색
                    _dup_candidates = await svc.repo.filter_by_async(
                        shipment_id=order_data["shipment_id"], limit=10
                    )
                    existing = next(
                        (
                            d
                            for d in _dup_candidates
                            if d.product_id == order_data["product_id"]
                            and (d.product_option or "")
                            == (order_data.get("product_option") or "")
                        ),
                        None,
                    )
                    if existing:
                        # order_number 갱신 (발주확인 후 변경된 productOrderId)
                        await svc.repo.update_async(
                            existing.id, order_number=order_data["order_number"]
                        )
                if existing:
                    # 기존 주문: sale_price, 이미지, 상태, 마켓주문상태 업데이트
                    update_fields: dict[str, Any] = {}
                    # tenant_id 보충 (기존 NULL 데이터 대응)
                    if order_data.get("tenant_id") and not existing.tenant_id:
                        update_fields["tenant_id"] = order_data["tenant_id"]
                    if (
                        order_data.get("sale_price")
                        and order_data["sale_price"] != existing.sale_price
                    ):
                        update_fields["sale_price"] = order_data["sale_price"]
                    # 고객결제금액 갱신: 변경됐거나 기존 NULL이면 채움
                    new_total_paid = order_data.get("total_payment_amount")
                    if new_total_paid is not None:
                        existing_total = (
                            existing.total_payment_amount
                            if existing.total_payment_amount is not None
                            else None
                        )
                        if existing_total is None or float(new_total_paid) != float(
                            existing_total
                        ):
                            update_fields["total_payment_amount"] = float(
                                new_total_paid
                            )
                    if order_data.get("product_image") and not existing.product_image:
                        update_fields["product_image"] = order_data["product_image"]
                    if order_data.get("source_site") and not existing.source_site:
                        update_fields["source_site"] = order_data["source_site"]
                    if order_data.get("source_url") and not existing.source_url:
                        update_fields["source_url"] = order_data["source_url"]
                    if order_data.get("customer_note") and order_data[
                        "customer_note"
                    ] != str(existing.customer_note or ""):
                        update_fields["customer_note"] = order_data["customer_note"]
                    if order_data.get("shipment_id") and order_data[
                        "shipment_id"
                    ] != str(existing.shipment_id or ""):
                        update_fields["shipment_id"] = order_data["shipment_id"]
                    # 결제일 갱신: 기존이 NULL이거나 더 이른 값일 때만 채택
                    # (고객 결제시각은 변하지 않음 — 더 늦은 값은 마켓이 sync/처리시각을 결제칸으로 돌려준 케이스로 간주하고 무시)
                    new_paid = order_data.get("paid_at")
                    if new_paid and (
                        existing.paid_at is None or new_paid < existing.paid_at
                    ):
                        update_fields["paid_at"] = new_paid
                    # 주소 보충 (기존 주문에 없으면 채움)
                    if (
                        order_data.get("customer_address")
                        and not existing.customer_address
                    ):
                        update_fields["customer_address"] = order_data[
                            "customer_address"
                        ]
                    # 마켓 상품번호 보충 (기존 주문에 없으면 채움)
                    if order_data.get("product_id") and not existing.product_id:
                        update_fields["product_id"] = order_data["product_id"]
                    # 송장전송완료/배송중 이상 상태는 덮어쓰지 않음
                    # 단, 롯데ON은 발송완료/배송중/배송완료로 진행된 경우 갱신 허용
                    new_ship_status = order_data.get("shipping_status")
                    if new_ship_status:
                        cancel_statuses = {"취소요청", "취소처리중", "취소완료"}
                        exchange_statuses = {
                            "교환요청",
                            "교환회수완료",
                            "교환재배송",
                            "교환완료",
                        }
                        advanced = {"발송완료", "배송중", "배송완료", "구매확정"}
                        if new_ship_status in cancel_statuses:
                            # 취소 상태는 항상 갱신 (송장전송완료 → 취소요청 등 역행 허용)
                            # 단, 이미 반품 진행 중인 주문은 취소로 되돌리지 않음
                            if existing.shipping_status in (
                                "반품요청",
                                "반품완료",
                                "반품거부",
                            ):
                                logger.info(
                                    f"[주문동기화] 반품 상태 보호: {order_data.get('order_number')} "
                                    f"{existing.shipping_status} → {new_ship_status} 차단"
                                )
                            else:
                                update_fields["shipping_status"] = new_ship_status
                        elif new_ship_status in exchange_statuses:
                            # 교환 상태는 항상 갱신 (배송완료 → 교환요청 등 역행 허용)
                            # 단, 이미 반품 상태인 주문은 교환으로 되돌리지 않음
                            if existing.shipping_status in (
                                "반품요청",
                                "반품완료",
                                "반품거부",
                            ):
                                logger.info(
                                    f"[주문동기화] 반품 상태 보호: {order_data.get('order_number')} "
                                    f"{existing.shipping_status} → {new_ship_status} 차단"
                                )
                            else:
                                update_fields["shipping_status"] = new_ship_status
                        elif (
                            existing.shipping_status == "송장전송완료"
                            and new_ship_status in advanced
                        ):
                            update_fields["shipping_status"] = new_ship_status
                        elif (
                            new_ship_status in ("반품요청", "반품완료", "반품거부")
                            and existing.shipping_status in exchange_statuses
                        ):
                            # 반품 상태는 교환 상태를 덮어씀 (교환→반품 재접수 케이스)
                            update_fields["shipping_status"] = new_ship_status
                            logger.info(
                                f"[주문동기화] 교환→반품 상태 전환: {order_data.get('order_number')} "
                                f"{existing.shipping_status} → {new_ship_status}"
                            )
                        elif existing.shipping_status not in (
                            "송장전송완료",
                            "배송중",
                            "배송완료",
                            "교환재배송",
                            "교환요청",
                            "교환회수완료",
                            "교환완료",
                            "교환거부",
                            "반품요청",
                            "반품완료",
                            "반품거부",
                        ):
                            update_fields["shipping_status"] = new_ship_status
                    # 정산금액(revenue) / 수수료율 갱신
                    new_revenue = order_data.get("revenue")
                    new_fee_rate = order_data.get("fee_rate")
                    sp = float(
                        update_fields.get("sale_price", existing.sale_price) or 0
                    )
                    if new_revenue and float(new_revenue) != float(
                        existing.revenue or 0
                    ):
                        rev = float(new_revenue)
                        update_fields["revenue"] = rev
                        update_fields["fee_rate"] = (
                            new_fee_rate
                            if new_fee_rate is not None
                            else (existing.fee_rate or 0)
                        )
                        cost = float(existing.cost or 0)
                        ship_fee = float(existing.shipping_fee or 0)
                        update_fields["profit"] = rev - cost - ship_fee
                        update_fields["profit_rate"] = (
                            f"{((rev - cost - ship_fee) / rev * 100):.2f}"
                            if rev > 0
                            else "0.00"
                        )
                    elif "sale_price" in update_fields:
                        fr = float(
                            new_fee_rate
                            if new_fee_rate is not None
                            else (existing.fee_rate or 0)
                        )
                        rev = sp * (1 - fr / 100)
                        cost = float(existing.cost or 0)
                        ship_fee = float(existing.shipping_fee or 0)
                        update_fields["revenue"] = rev
                        update_fields["profit"] = rev - cost - ship_fee
                        update_fields["profit_rate"] = (
                            f"{((rev - cost - ship_fee) / rev * 100):.2f}"
                            if rev > 0
                            else "0.00"
                        )
                    if update_fields:
                        await svc.update_order(existing.id, update_fields)
                    continue
                await svc.create_order(order_data)
                synced += 1

            total_synced += synced
            if market_type == "smartstore":
                confirmed_count = len(unconfirmed_ids)
            elif market_type == "lotteon":
                confirmed_count = lotteon_confirmed_count
            else:
                confirmed_count = 0

            # ── 클레임(취소/반품/교환) → SambaReturn 자동 생성 ──────────────
            returns_synced = 0
            claim_statuses = {
                "취소요청",
                "취소처리중",
                "취소완료",
                "반품요청",
                "반품완료",
                "반품거부",
                "교환요청",
                "교환회수완료",
                "교환재배송",
                "교환완료",
            }
            claim_orders = [
                od for od in orders_data if od.get("shipping_status") in claim_statuses
            ]
            if claim_orders:
                from backend.domain.samba.returns.service import SambaReturnService
                from backend.domain.samba.returns.repository import (
                    SambaReturnRepository,
                )
                from backend.domain.samba.returns.model import SambaReturn
                from sqlmodel import select as _sel

                return_svc = SambaReturnService(SambaReturnRepository(session))

                claim_type_map = {
                    "취소요청": "cancel",
                    "취소처리중": "cancel",
                    "취소완료": "cancel",
                    "반품요청": "return",
                    "반품완료": "return",
                    "반품거부": "return",
                    "교환요청": "exchange",
                    "교환회수완료": "exchange",
                    "교환재배송": "exchange",
                    "교환완료": "exchange",
                }
                claim_return_status_map = {
                    "취소완료": "completed",
                    "반품완료": "completed",
                    "교환완료": "completed",
                    "반품거부": "rejected",
                }
                claim_completion_detail_map = {
                    "취소완료": "취소",
                    "반품완료": "반품",
                    "교환완료": "교환",
                    "반품거부": "거부",
                }
                for od in claim_orders:
                    order_no = od.get("order_number", "")
                    if not order_no:
                        continue
                    shipping_status = od.get("shipping_status", "")
                    ret_type = claim_type_map.get(shipping_status, "return")
                    return_status = claim_return_status_map.get(shipping_status)
                    completion_detail = claim_completion_detail_map.get(shipping_status)
                    # 중복 체크
                    existing_ret_result = await session.execute(
                        _sel(SambaReturn).where(SambaReturn.order_number == order_no)
                    )
                    existing_ret = existing_ret_result.scalar_one_or_none()
                    if existing_ret:
                        update_fields: dict[str, Any] = {
                            "type": ret_type,
                            "market_order_status": shipping_status,
                        }
                        if return_status:
                            update_fields["status"] = return_status
                        if completion_detail:
                            update_fields["completion_detail"] = completion_detail
                        if return_status in ("completed", "rejected"):
                            from datetime import UTC, datetime as _dt

                            update_fields["completion_date"] = _dt.now(UTC)
                        await return_svc.repo.update_async(
                            existing_ret.id, **update_fields
                        )
                        continue
                    # 연결 주문 조회
                    linked_order = await svc.repo.find_by_async(order_number=order_no)
                    if not linked_order:
                        continue
                    ret = await return_svc.create_return(
                        {
                            "order_id": linked_order.id,
                            "order_number": order_no,
                            "type": ret_type,
                            "market": label,
                            "market_order_status": shipping_status,
                            "product_name": od.get("product_name", ""),
                            "product_image": od.get("product_image", ""),
                            "customer_name": od.get("customer_name", ""),
                            "customer_phone": od.get("customer_phone", ""),
                            "customer_address": od.get("customer_address", ""),
                            "requested_amount": od.get("sale_price", 0),
                        }
                    )
                    if return_status or completion_detail:
                        update_fields: dict[str, Any] = {}
                        if return_status:
                            update_fields["status"] = return_status
                        if completion_detail:
                            update_fields["completion_detail"] = completion_detail
                        if return_status in ("completed", "rejected"):
                            from datetime import UTC, datetime as _dt

                            update_fields["completion_date"] = _dt.now(UTC)
                        await return_svc.repo.update_async(ret.id, **update_fields)
                    returns_synced += 1
                logger.info(
                    f"[주문동기화] {label}: 클레임 {len(claim_orders)}건 중 {returns_synced}건 반품교환 생성"
                )

            cancel_requested = sum(
                1 for od in orders_data if od.get("shipping_status") == "취소요청"
            )
            results.append(
                {
                    "account": label,
                    "status": "success",
                    "fetched": len(orders_data),
                    "synced": synced,
                    "confirmed": confirmed_count,
                    "cancel_requested": cancel_requested,
                    "returns_synced": returns_synced,
                }
            )
            logger.info(
                f"[주문동기화] {label}: {len(orders_data)}건 조회, {synced}건 저장, {confirmed_count}건 발주확인"
            )

            # ── paid_at 백필 — 스마트스토어 NULL paid_at 주문 직접 재조회 ──
            if market_type == "smartstore":
                try:
                    _null_rows = await session.execute(
                        _sa_text(
                            "SELECT order_number FROM samba_order "
                            "WHERE paid_at IS NULL AND source = 'smartstore' "
                            "AND channel_id = :cid LIMIT 100"
                        ),
                        {"cid": account["id"]},
                    )
                    _null_po_ids = [r[0] for r in _null_rows.fetchall()]
                    if _null_po_ids:
                        _details = await client.get_product_orders_by_ids(_null_po_ids)
                        _backfilled = 0
                        for _d in _details:
                            _po = _d.get("productOrder", _d)
                            _oi = _d.get("order", {})
                            _paid = _parse_iso_datetime(
                                _oi.get("paymentDate") or _po.get("paymentDate")
                            )
                            if _paid:
                                _poid = _po.get("productOrderId", "")
                                await session.execute(
                                    _sa_text(
                                        "UPDATE samba_order SET paid_at = :paid "
                                        "WHERE order_number = :on AND paid_at IS NULL"
                                    ),
                                    {"paid": _paid, "on": _poid},
                                )
                                _backfilled += 1
                        if _backfilled:
                            await session.commit()
                            logger.info(
                                f"[주문동기화] {label}: paid_at 백필 {_backfilled}건"
                            )
                except Exception as _bf_err:
                    logger.warning(
                        f"[주문동기화] {label}: paid_at 백필 실패 — {_bf_err}"
                    )

            # ── paid_at 백필 — 플레이오토 NULL paid_at 주문 → 동기화 데이터에서 매칭 ──
            elif market_type == "playauto":
                try:
                    # 현재 동기화에서 paid_at이 유효한 주문의 order_number → paid_at 매핑
                    _pa_paid_map: dict[str, datetime] = {}
                    for od in orders_data:
                        if od.get("paid_at") and od.get("order_number"):
                            _pa_paid_map[od["order_number"]] = od["paid_at"]
                    if _pa_paid_map:
                        _null_rows = await session.execute(
                            _sa_text(
                                "SELECT order_number FROM samba_order "
                                "WHERE paid_at IS NULL AND source = 'playauto' "
                                "AND channel_id = :cid LIMIT 200"
                            ),
                            {"cid": account["id"]},
                        )
                        _null_ons = [r[0] for r in _null_rows.fetchall()]
                        _backfilled = 0
                        for _on in _null_ons:
                            _paid = _pa_paid_map.get(_on)
                            if _paid:
                                await session.execute(
                                    _sa_text(
                                        "UPDATE samba_order SET paid_at = :paid "
                                        "WHERE order_number = :on AND paid_at IS NULL"
                                    ),
                                    {"paid": _paid, "on": _on},
                                )
                                _backfilled += 1
                        if _backfilled:
                            await session.commit()
                            logger.info(
                                f"[주문동기화] {label}: 플레이오토 paid_at 백필 {_backfilled}건"
                            )
                except Exception as _bf_err:
                    logger.warning(
                        f"[주문동기화] {label}: 플레이오토 paid_at 백필 실패 — {_bf_err}"
                    )

            # ── paid_at 백필 — 롯데ON NULL paid_at 주문 → 동기화 데이터에서 매칭 ──
            # order_number = "{od_no}_{od_seq}_{proc_seq}" 합성키 기반 (order.py:3406)
            elif market_type == "lotteon":
                try:
                    _lo_paid_map: dict[str, datetime] = {}
                    for od in orders_data:
                        if od.get("paid_at") and od.get("order_number"):
                            _lo_paid_map[od["order_number"]] = od["paid_at"]
                    if _lo_paid_map:
                        _null_rows = await session.execute(
                            _sa_text(
                                "SELECT order_number FROM samba_order "
                                "WHERE paid_at IS NULL AND source = 'lotteon' "
                                "AND channel_id = :cid LIMIT 200"
                            ),
                            {"cid": account["id"]},
                        )
                        _null_ons = [r[0] for r in _null_rows.fetchall()]
                        _backfilled = 0
                        for _on in _null_ons:
                            _paid = _lo_paid_map.get(_on)
                            if _paid:
                                await session.execute(
                                    _sa_text(
                                        "UPDATE samba_order SET paid_at = :paid "
                                        "WHERE order_number = :on AND paid_at IS NULL"
                                    ),
                                    {"paid": _paid, "on": _on},
                                )
                                _backfilled += 1
                        if _backfilled:
                            await session.commit()
                            logger.info(
                                f"[주문동기화] {label}: 롯데ON paid_at 백필 {_backfilled}건"
                            )
                except Exception as _bf_err:
                    logger.warning(
                        f"[주문동기화] {label}: 롯데ON paid_at 백필 실패 — {_bf_err}"
                    )

        except Exception as e:
            await session.rollback()  # 세션 복구 — 다음 계정 연쇄 실패 방지
            logger.error(f"[주문동기화] {label} 실패: {e}")
            results.append({"account": label, "status": "error", "message": str(e)})

    # DB 기반 원주문 shipping_status 일괄 동기화
    # samba_return 레코드가 있고 진행 중인 주문의 shipping_status를 강제 업데이트
    try:
        from sqlalchemy import text as _sa_text_upd

        await session.execute(
            _sa_text_upd(
                """
            UPDATE samba_order o
            SET shipping_status = CASE
                WHEN r.type = 'exchange' THEN '교환요청'
                WHEN r.type = 'return' THEN '반품요청'
                WHEN r.type = 'cancel' THEN '취소요청'
                ELSE o.shipping_status
            END
            FROM samba_return r
            WHERE r.order_id = o.id
              AND r.status NOT IN ('completed', 'cancelled', 'rejected')
              AND o.shipping_status NOT IN (
                  '교환요청', '교환회수완료', '교환재배송', '교환완료',
                  '반품요청', '반품완료', '반품거부',
                  '취소완료'
              )
        """
            )
        )
        await session.commit()
        logger.info(
            "[주문동기화] 반품/교환/취소 진행 중 원주문 shipping_status 일괄 업데이트 완료"
        )
    except Exception as _upd_err:
        logger.warning(f"[주문동기화] 원주문 일괄 업데이트 실패: {_upd_err}")

    if total_synced > 0:
        from backend.utils.kakao_notify import send_kakao_message

        synced_lines = [
            f"  {r['account']}: {r.get('synced', 0)}건"
            for r in results
            if r.get("synced", 0) > 0
        ]
        msg = f"🛒 주문 {total_synced}건 동기화 완료"
        if synced_lines:
            msg += "\n" + "\n".join(synced_lines)
        asyncio.create_task(send_kakao_message(msg))

    return {"total_synced": total_synced, "results": results}


def _parse_iso_datetime(val: str | None) -> datetime | None:
    """ISO 8601 문자열 → datetime 변환. 실패 시 None."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_smartstore_order(
    po: dict,
    order_info: dict,
    account_id: str,
    account_label: str,
    claim_info: dict | None = None,
) -> dict[str, Any]:
    """스마트스토어 productOrder + order → SambaOrder 데이터 변환."""
    status_map = {
        "PAYED": "pending",
        "DELIVERING": "shipped",
        "DELIVERED": "delivered",
        "PURCHASE_DECIDED": "delivered",
        "EXCHANGED": "delivered",
        "CANCELED": "cancelled",
        "RETURNED": "returned",
        "CANCEL_REQUESTED": "pending",
    }
    naver_status = po.get("productOrderStatus", "")
    place_status = po.get("placeOrderStatus", "")
    sale_price = po.get("totalPaymentAmount", 0) or po.get("unitPrice", 0) or 0
    quantity = po.get("quantity", 1) or 1

    # 클레임 상태 (취소/반품/교환 요청)
    # 우선순위: 호출자가 전달한 claim 서브 객체 → productOrder 최상위 순으로 fallback
    _ci = claim_info or {}
    claim_type = _ci.get("claimType") or po.get("claimType", "") or ""
    claim_status = _ci.get("claimStatus") or po.get("claimStatus", "") or ""

    claim_status_map = {
        "CANCEL_REQUEST": "취소요청",
        "CANCELING": "취소처리중",
        "CANCEL_DONE": "취소완료",
        "CANCEL_REJECT": "취소거부",
        "RETURN_REQUEST": "반품요청",
        "COLLECTING": "수거중",
        "COLLECT_DONE": "수거완료",
        "RETURN_DONE": "반품완료",
        "RETURN_REJECT": "반품거부",
        "EXCHANGE_REQUEST": "교환요청",
        "EXCHANGING": "교환처리중",
        "EXCHANGE_DONE": "교환완료",
        "EXCHANGE_REJECT": "교환거부",
    }

    # 정산금액: API에서 직접 가져오기
    expected_settlement = po.get("expectedSettlementAmount")
    if expected_settlement and sale_price > 0:
        fee_rate = round((1 - expected_settlement / sale_price) * 100, 2)
    else:
        expected_settlement = None
        fee_rate = 0

    # 마켓 주문상태 한글 변환
    market_status_map: dict[str, str] = {
        "PAYED": "결제완료",
        "DELIVERING": "배송중",
        "DELIVERED": "배송완료",
        "PURCHASE_DECIDED": "구매확정",
        "EXCHANGED": "교환완료",
        "CANCELED": "취소완료",
        "RETURNED": "반품완료",
        "CANCEL_REQUESTED": "취소요청",
        "RETURN_REQUESTED": "반품요청",
        "EXCHANGE_REQUESTED": "교환요청",
    }
    # 클레임이 있으면 클레임 상태 우선
    if claim_status and claim_status in claim_status_map:
        market_order_status = claim_status_map[claim_status]
    elif place_status == "NOT_YET" and naver_status == "PAYED":
        market_order_status = "발주미확인"
    elif naver_status == "PAYED":
        market_order_status = "발송대기"
    else:
        market_order_status = market_status_map.get(naver_status, naver_status)

    # 배송지 정보
    shipping = po.get("shippingAddress", {})
    # 주문자 정보 (order 객체에서 추출)
    orderer_name = order_info.get("ordererName", "") or shipping.get("name", "")
    orderer_tel = order_info.get("ordererTel", "") or shipping.get("tel1", "")

    # 마켓 상품번호 (구매페이지 URL 생성용)
    channel_product_no = str(
        po.get("channelProductNo", "") or po.get("productId", "") or ""
    )

    return {
        "order_number": po.get("productOrderId", ""),
        "shipment_id": order_info.get("orderId", ""),
        "channel_id": account_id,
        "channel_name": account_label,
        "product_id": channel_product_no,
        "product_name": po.get("productName", ""),
        "product_option": po.get("productOption", "") or "",
        "product_image": po.get("imageUrl", ""),
        "customer_name": orderer_name,
        "customer_phone": orderer_tel,
        "customer_address": (
            shipping.get("baseAddress", "") + " " + shipping.get("detailedAddress", "")
        ).strip(),
        "customer_note": po.get("shippingMemo", "") or "",
        "quantity": quantity,
        "sale_price": sale_price,
        "cost": 0,
        "fee_rate": fee_rate,
        "revenue": expected_settlement if expected_settlement else sale_price,
        # 내부 status도 클레임 반영
        "status": (
            "cancel_requested"
            if claim_status in ("CANCEL_REQUEST", "CANCELING")
            else (
                "cancelled"
                if claim_status == "CANCEL_DONE"
                else (
                    "return_requested"
                    if claim_status in ("RETURN_REQUEST", "COLLECTING", "COLLECT_DONE")
                    else (
                        "returned"
                        if claim_status == "RETURN_DONE"
                        else status_map.get(naver_status, "pending")
                    )
                )
            )
        ),
        "shipping_status": market_order_status,
        "shipping_company": po.get("deliveryCompany", ""),
        "tracking_number": po.get("trackingNumber", ""),
        "paid_at": _parse_iso_datetime(
            order_info.get("paymentDate") or po.get("paymentDate")
        ),
        "source": "smartstore",
    }


def _parse_coupang_order(
    order: dict,
    account_id: str,
    account_label: str,
) -> dict[str, Any]:
    """쿠팡 ordersheet 1건 → SambaOrder 데이터 변환."""
    status_map = {
        "ACCEPT": "pending",
        "INSTRUCT": "pending",
        "DEPARTURE": "shipped",
        "DELIVERING": "shipped",
        "FINAL_DELIVERY": "delivered",
        "CANCEL": "cancelled",
    }
    market_status_map = {
        "ACCEPT": "결제완료",
        "INSTRUCT": "상품준비중",
        "DEPARTURE": "배송중",
        "DELIVERING": "배송중",
        "FINAL_DELIVERY": "배송완료",
        "CANCEL": "취소완료",
    }

    coupang_status = (order.get("status") or "").upper()
    shipment_box_id = order.get("shipmentBoxId") or 0
    order_id = order.get("orderId") or 0

    # 클레임 (취소/반품 요청) 우선
    cancel_requests = order.get("cancelRequests") or []
    return_requests = order.get("returnRequests") or []
    if cancel_requests:
        market_order_status = "취소요청"
        internal_status = "cancel_requested"
    elif return_requests:
        market_order_status = "반품요청"
        internal_status = "return_requested"
    else:
        market_order_status = market_status_map.get(coupang_status, coupang_status)
        internal_status = status_map.get(coupang_status, "pending")

    order_items = order.get("orderItems") or []
    first_item = order_items[0] if order_items else {}
    product_name = first_item.get("sellerProductName", "") or ""
    # 쿠팡 옵션 없음 placeholder 패턴 (대소문자/공백/구두점 변형 허용)
    _NO_OPTION_PATTERNS = ("옵션없음", "no option")

    option_name = (
        first_item.get("sellerProductItemName", "")
        or first_item.get("firstSellerProductItemName", "")
        or ""
    ).strip()

    # placeholder 텍스트 정규화 (예: "옵션없음. 옵션없음." → "FREE")
    _normalized = option_name.lower().replace(" ", "").replace(".", "")
    if not option_name or any(
        p.replace(" ", "") in _normalized for p in _NO_OPTION_PATTERNS
    ):
        option_name = "FREE"
    sales_price = int(first_item.get("salesPrice", 0) or 0)
    quantity = int(first_item.get("orderQuantity", 1) or 1)
    shipping_price = int(order.get("shippingPrice", 0) or 0)
    sale_price = sales_price + shipping_price

    # 쿠팡 정률 수수료 10.5% + VAT 10% = 실효 11.55%
    fee_rate = 11.55
    revenue = round(sale_price * (1 - fee_rate / 100))

    receiver_addr = (
        order.get("receiverAddr1", "") or order.get("receiverAddress", "") or ""
    )
    receiver_addr_detail = (
        order.get("receiverAddr2", "") or order.get("receiverAddrDetail", "") or ""
    )
    customer_address = (receiver_addr + " " + receiver_addr_detail).strip()

    orderer_name = order.get("ordererName", "") or order.get("receiverName", "") or ""
    orderer_tel = (
        order.get("ordererPhoneNumber", "")
        or order.get("orderPhoneNumber", "")
        or order.get("receiverPhoneNumber", "")
        or ""
    )

    # shipmentBoxId 우선 (배송단위 안정 ID), orderId fallback
    order_number = str(shipment_box_id or order_id or "")

    return {
        "order_number": order_number,
        "shipment_id": str(order_id) if order_id else "",
        "channel_id": account_id,
        "channel_name": account_label,
        "product_id": str(
            first_item.get("productId", "")
            or first_item.get("sellerProductId", "")
            or ""
        ),
        "product_name": product_name,
        "coupang_display_name": first_item.get("vendorItemPackageName", "") or "",
        "product_option": option_name,
        "product_image": "",
        "customer_name": orderer_name,
        "customer_phone": orderer_tel,
        "customer_address": customer_address,
        "quantity": quantity,
        "sale_price": sale_price,
        "cost": 0,
        "fee_rate": fee_rate,
        "revenue": revenue,
        "status": internal_status,
        "shipping_status": market_order_status,
        "shipping_company": order.get("deliveryCompanyName", "") or "",
        "tracking_number": order.get("invoiceNumber", "") or "",
        "paid_at": _parse_iso_datetime(order.get("paidAt") or order.get("orderedAt")),
        "source": "coupang",
    }


def _parse_lotteon_order(item: dict, account_id: str, label: str) -> dict:
    """롯데ON 주문 데이터 → SambaOrder dict 변환."""

    # 주문 진행 단계 코드 → 내부 status/shipping_status 매핑
    step_cd = str(item.get("odPrgsStepCd", "") or "")
    status_map = {
        "10": "pending",  # 발주확인대기
        "11": "preparing",  # 발주확인완료(출고지시) — sync에서 자동 ifCplYN=Y 호출되어 12로 전이
        "12": "preparing",  # 상품준비
        "13": "shipping",  # 발송완료
        "14": "delivered",  # 배송완료
        "20": "pending",  # 발주확인
        "21": "return_requested",  # 교환회수중
        "22": "return_requested",  # 교환회수완료
        "23": "return_requested",  # 교환회수완료확인
        "24": "shipping",  # 교환재배송
        "25": "delivered",  # 교환배송완료
        "30": "shipping",  # 배송중
        "40": "delivered",  # 배송완료
        "50": "confirmed",  # 구매확정
        "90": "cancelled",  # 취소
    }
    shipping_map = {
        "10": "발주확인대기",
        "11": "출고지시",
        "12": "상품준비",
        "13": "발송완료",
        "14": "배송완료",
        "20": "출고지시",
        "21": "교환요청",
        "22": "교환회수완료",
        "23": "교환회수완료",
        "24": "교환재배송",
        "25": "교환완료",
        "30": "배송중",
        "40": "배송완료",
        "50": "구매확정",
        "90": "취소",
    }
    status = status_map.get(step_cd, "pending")
    shipping_status = shipping_map.get(step_cd, "출고지시")

    # 롯데ON 반품 사유코드(200/300번대)인데 교환 stepCd(21~25)로 들어온 경우
    # → 실제로는 반품이므로 반품 상태로 재매핑
    clm_rsn_cd = str(item.get("clmRsnCd", "") or "")
    if clm_rsn_cd.startswith(("2", "3")) and step_cd in ("21", "22", "23", "24", "25"):
        status = "return_requested"
        shipping_status = "반품요청"
        logger.info(
            f"[롯데ON][주문파싱] 반품 사유코드({clm_rsn_cd}) 교환 stepCd({step_cd}) "
            f"→ 반품요청으로 재매핑: odNo={item.get('odNo')}"
        )

    # 결제일시 파싱 — 롯데ON 응답 실측 키는 odCmptDttm (yyyymmddHHmmss, KST)
    # 참고: owhoDttm(발주확인, ISO 포맷)은 결제 이후 시각이라 결제시각 폴백으로 부적합
    from backend.utils import kst_str_to_utc

    order_dttm_str = item.get("odCmptDttm") or ""
    paid_at = kst_str_to_utc(order_dttm_str)
    if not paid_at:
        logger.warning(
            f"[롯데ON][주문파싱] 결제일시 키 없음 odNo={item.get('odNo')} "
            f"odCmptDttm={item.get('odCmptDttm')!r} "
            f"키후보={[k for k in item.keys() if 'tt' in k.lower() or 'dt' in k.lower()]}"
        )

    # 배송지 주소 조합 (dvpStnmZipAddr=도로명기본주소, dvpStnmDtlAddr=상세주소)
    addr1 = item.get("dvpStnmZipAddr") or ""
    addr2 = item.get("dvpStnmDtlAddr") or ""
    full_addr = f"{addr1} {addr2}".strip()

    _od_no = str(item.get("odNo", "") or "")
    _od_seq = str(item.get("odSeq", "1") or "1")
    _proc_seq = str(item.get("procSeq", "1") or "1")
    _sitm_no = str(item.get("sitmNo", "") or "")

    return {
        "channel_id": account_id,
        "channel_name": label,
        "source": "lotteon",
        # 합성 키: 동일 odNo 내 다른 옵션(odSeq)을 구분하기 위해 _odSeq_procSeq 접미사
        "order_number": f"{_od_no}_{_od_seq}_{_proc_seq}" if _od_no else "",
        "od_no": _od_no,
        "od_seq": _od_seq,
        "proc_seq": _proc_seq,
        "sitm_no": _sitm_no,
        "shipment_id": _sitm_no,
        "product_id": str(item.get("spdNo", "") or ""),
        "product_name": item.get("spdNm", "") or "",
        "product_option": item.get("sitmNm", "") or "",
        "quantity": int(item.get("odQty", 1) or 1),
        "sale_price": int(item.get("slAmt", 0) or item.get("slPrc", 0) or 0),
        "cost": 0,
        "status": status,
        "shipping_status": shipping_status,
        "customer_name": item.get("dvpCustNm", "") or item.get("odrNm", "") or "",
        "customer_phone": item.get("dvpMphnNo", "")
        or item.get("dvpTelNo", "")
        or item.get("mphnNo", "")
        or "",
        "customer_address": full_addr,
        "customer_note": item.get("dvMsg", "") or "",
        "paid_at": paid_at,
        # created_at은 명시 X — DB default_factory(now)가 실제 삽입 시각 기록
    }


def _parse_playauto_order(
    ro: dict,
    account_id: str,
    account_label: str,
    alias_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """플레이오토 EMP 주문 → SambaOrder 데이터 변환."""
    status_map = {
        "신규주문": "pending",
        "송장출력": "wait_ship",
        "송장입력": "processing",
        "출고": "shipped",
        "배송중": "shipped",
        "수취확인": "delivered",
        "정산완료": "delivered",
        "주문확인": "pending",
        "취소": "cancelled",
        "취소마감": "cancelled",
        "반품요청": "return_requested",
        "반품마감": "returned",
        "교환요청": "exchange_requested",
        "교환마감": "exchanged",
        "보류": "pending",
    }

    # shipping_status 매핑 (스킬 가이드 기준)
    shipping_status_map = {
        "신규주문": "주문접수",
        "송장출력": "배송대기중",
        "주문확인": "취소중",
        "취소마감": "취소완료",
        "수취확인": "배송완료",
        "정산완료": "배송완료",
    }

    order_state = ro.get("OrderState", "")
    sale_price = int(ro.get("Price", 0) or 0)
    quantity = int(ro.get("Count", 1) or 1)

    site_name = ro.get("SiteName", "")
    site_id = ro.get("SiteId", "")
    supply_price = int(ro.get("SupplyPrice", 0) or 0)

    # 결제일 파싱 — 플레이오토는 KST 기준
    from backend.utils import kst_str_to_utc

    order_date_raw = ro.get("OrderDate", "") or ""
    paid_at = kst_str_to_utc(order_date_raw)

    return {
        "order_number": ro.get("OrderCode", ""),
        "shipment_id": str(ro.get("Number", "")),
        "channel_id": account_id,
        "channel_name": account_label,
        "product_id": ro.get("ProdCode", ""),
        "product_name": ro.get("ProdName", ""),
        "product_option": ro.get("Option", ""),
        "product_image": "",
        "customer_name": ro.get("RecipientName", "") or ro.get("OrderName", ""),
        "customer_phone": ro.get("RecipientHtel", "")
        or ro.get("RecipientTel", "")
        or ro.get("OrderHtel", "")
        or ro.get("OrderTel", ""),
        "customer_address": ro.get("RecipientAddress", ""),
        "quantity": quantity,
        "sale_price": sale_price,
        "cost": int(ro.get("CostPrice", 0) or 0),
        "fee_rate": 0,
        "revenue": supply_price if supply_price else sale_price,
        "status": status_map.get(order_state, "pending"),
        "shipping_status": shipping_status_map.get(order_state, order_state),
        "shipping_company": ro.get("Sender", ""),
        "tracking_number": ro.get("SenderNo", ""),
        "paid_at": paid_at,
        "source": "playauto",
        # 판매처(사업자) 정보 — 별칭 매핑 적용
        "source_site": (
            f"{site_name}({alias_map[site_id]})"
            if alias_map and site_id in alias_map and site_name
            else f"{site_name}({site_id})" if site_name else ""
        ),
    }


def _parse_ebay_datetime(val) -> Optional[datetime]:
    """eBay 날짜 필드는 문자열 또는 {"value": "..."} dict 형태."""
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("value", "")
    return _parse_iso_datetime(val if isinstance(val, str) else None)


def _parse_ebay_order(
    o: dict,
    account_id: str,
    account_label: str,
    exchange_rate: float = 1400.0,
) -> dict[str, Any]:
    """eBay Fulfillment API 주문 dict → SambaOrder 필드 매핑.

    eBay는 USD 결제이므로 ``exchange_rate``(USD→KRW)로 변환해 KRW로 저장한다.
    다른 마켓(스마트스토어/롯데ON)과 통일된 KRW 체계 유지.
    """
    order_id = o.get("orderId", "") or ""
    legacy_id = o.get("legacyOrderId", "") or order_id

    line_items = o.get("lineItems") or []
    first_item: dict[str, Any] = line_items[0] if line_items else {}

    # 배송지
    ship_to: dict[str, Any] = {}
    for inst in o.get("fulfillmentStartInstructions") or []:
        step = inst.get("shippingStep") or {}
        ship_to = step.get("shipTo") or {}
        if ship_to:
            break
    contact = ship_to.get("contactAddress") or {}
    addr_parts = [
        contact.get("addressLine1", ""),
        contact.get("addressLine2", ""),
        contact.get("city", ""),
        contact.get("stateOrProvince", ""),
        contact.get("postalCode", ""),
        contact.get("countryCode", ""),
    ]
    customer_address = ", ".join([p for p in addr_parts if p])

    # 가격 (USD → KRW 변환)
    pricing = o.get("pricingSummary") or {}
    total = pricing.get("total") or {}
    sale_price_usd = float(total.get("value", 0) or 0)
    sale_price_krw = int(round(sale_price_usd * exchange_rate))

    # 수수료 (eBay 마켓플레이스 수수료, USD → KRW 변환)
    marketplace_fee_usd = float(
        (o.get("totalMarketplaceFee") or {}).get("value", 0) or 0
    )
    marketplace_fee_krw = int(round(marketplace_fee_usd * exchange_rate))
    try:
        fee_rate = (
            round(marketplace_fee_usd / sale_price_usd * 100, 2)
            if sale_price_usd > 0
            else 0
        )
    except Exception:
        fee_rate = 0
    revenue = sale_price_krw - marketplace_fee_krw

    # 상태 매핑
    ff_status = o.get("orderFulfillmentStatus", "") or ""
    cancel_state = (o.get("cancelStatus") or {}).get(
        "cancelState", "NONE_REQUESTED"
    ) or "NONE_REQUESTED"
    if cancel_state != "NONE_REQUESTED":
        status = "cancel_requested"
        shipping_status = "취소요청"
    elif ff_status == "FULFILLED":
        status = "pending"
        shipping_status = "배송중"
    elif ff_status == "IN_PROGRESS":
        status = "pending"
        shipping_status = "발송대기"
    else:
        status = "pending"
        shipping_status = "발주확인"

    buyer_username = (o.get("buyer") or {}).get("username", "") or ""

    return {
        "order_number": legacy_id,
        "ext_order_number": order_id,
        "shipment_id": first_item.get("sku", ""),
        "channel_id": account_id,
        "channel_name": account_label,
        "product_id": first_item.get("legacyItemId", "") or first_item.get("sku", ""),
        "product_name": first_item.get("title", ""),
        "product_option": first_item.get("legacyVariationId", "") or "",
        "product_image": "",
        "customer_name": ship_to.get("fullName", "") or buyer_username,
        "customer_phone": (ship_to.get("primaryPhone") or {}).get("phoneNumber", "")
        or "",
        "customer_address": customer_address,
        "quantity": int(first_item.get("quantity", 1) or 1),
        "sale_price": sale_price_krw,
        "cost": 0,
        "fee_rate": fee_rate,
        "revenue": revenue,
        "status": status,
        "shipping_status": shipping_status,
        "shipping_company": "",
        "tracking_number": "",
        "paid_at": _parse_ebay_datetime(o.get("creationDate")),
        "source": "ebay",
        "notes": f"USD {sale_price_usd:.2f} @ {exchange_rate:.2f}원/USD",
    }


def _apply_ebay_claims_to_orders(
    orders_data: list[dict[str, Any]],
    returns_raw: list[dict[str, Any]],
    cancellations_raw: list[dict[str, Any]],
) -> None:
    """eBay 반품/취소 데이터로 orders_data의 shipping_status 덮어쓰기.

    return.state / cancellation.cancelState 를 기준으로 상태 매핑.
    orders_data에 없는 주문이면 추가하지 않음 (sync 범위 내 주문만 반영).
    """
    # 반품
    return_state_map = {
        "OPEN": "반품요청",
        "ESCALATED": "반품요청",
        "CLOSED": "반품완료",
    }
    for r in returns_raw or []:
        order_id = (
            r.get("orderId")
            or (r.get("itemInfo") or {}).get("orderId")
            or (r.get("creationInfo") or {}).get("orderId")
            or ""
        )
        state = (r.get("status") or {}).get("state", "") or ""
        ss = return_state_map.get(state, "반품요청")
        for od in orders_data:
            if od.get("ext_order_number") == order_id or od.get("order_number") == str(
                order_id
            ):
                od["shipping_status"] = ss
                od["status"] = "returned" if ss == "반품완료" else "return_requested"
                break

    # 취소
    cancel_state_map = {
        "IN_PROGRESS": "취소요청",
        "CANCEL_PENDING": "취소요청",
        "CANCEL_CLOSED": "취소완료",
        "CANCEL_CLOSED_FOR_COMMITMENT": "취소요청",
    }
    for c in cancellations_raw or []:
        legacy_order_id = c.get("legacyOrderId", "") or ""
        state = c.get("cancelState", "") or ""
        ss = cancel_state_map.get(state, "취소요청")
        for od in orders_data:
            if od.get("order_number") == legacy_order_id:
                od["shipping_status"] = ss
                od["status"] = "cancelled" if ss == "취소완료" else "cancel_requested"
                break
