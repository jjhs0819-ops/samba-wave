"""SambaWave Order API router."""

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


def _read_service(session: AsyncSession) -> SambaOrderService:
    return SambaOrderService(SambaOrderRepository(session))


def _write_service(session: AsyncSession) -> SambaOrderService:
    return SambaOrderService(SambaOrderRepository(session))


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
        "arrived",
        "ship_failed",
        "shipping",
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
    week_ago = (now - timedelta(days=7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # 날짜 기준: 고객결제일 우선, KST 변환
    order_date_utc = func.coalesce(SambaOrder.paid_at, SambaOrder.created_at)
    order_date = order_date_utc + text("INTERVAL '9 hours'")

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
    ).where(order_date >= this_month_start)
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
    ).where(and_(order_date >= last_month_start, order_date < this_month_start))
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
        .where(order_date >= week_ago)
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
            and_(
                order_date >= year_start,
                extract("year", order_date) == now.year,
            )
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


@router.get("/by-date-range", response_model=list[SambaOrder])
async def list_orders_by_date_range(
    start: str = Query(..., description="시작일 YYYY-MM-DD"),
    end: str = Query(..., description="종료일 YYYY-MM-DD"),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """기간별 주문 조회 — COALESCE(paid_at, created_at) 기준, 제한 없이 전체 반환."""
    from sqlalchemy import func, select as sa_select, or_
    from backend.utils import kst_date_range_to_utc

    start_dt, end_dt = kst_date_range_to_utc(start, end)

    order_date = func.coalesce(SambaOrder.paid_at, SambaOrder.created_at)
    stmt = (
        sa_select(SambaOrder)
        .where(order_date >= start_dt, order_date <= end_dt)
        .order_by(order_date.desc())
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
):
    """상품주문번호로 주문 조회."""
    svc = _read_service(session)
    order = await svc.repo.find_by_async(order_number=order_number)
    if not order:
        return None
    return {"id": order.id, "order_number": order.order_number}


@router.get("/{order_id}", response_model=SambaOrder)
async def get_order(
    order_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
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
                od_no=order.order_number,
                reason_code="135",
                reason_text="고객변심",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"판매자 취소 실패: {e}")

        if not success:
            raise HTTPException(status_code=500, detail=f"판매자 취소 실패: {message}")

        await svc.update_order(
            order_id,
            {"shipping_status": "취소완료", "status": "cancelled"},
        )
        logger.info(f"[판매자취소] 롯데ON {order.order_number} 완료 (고객변심)")
        return {"ok": True, "message": "판매자 취소 완료", "detail": message}

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
                cancel_reason="SOLD_OUT",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"판매자 취소 실패: {e}")

        await svc.update_order(
            order_id,
            {"shipping_status": "취소완료", "status": "cancelled"},
        )
        logger.info(f"[판매자취소] 스마트스토어 {order.order_number} 완료 (SOLD_OUT)")
        return {"ok": True, "message": "판매자 취소 완료"}

    elif account.market_type == "playauto":
        from backend.domain.samba.proxy.playauto import PlayAutoClient

        extras = account.additional_fields or {}
        api_key = extras.get("apiKey", "") or account.api_key or ""
        if not api_key:
            raise HTTPException(status_code=400, detail="플레이오토 API Key 없음")

        # order_number를 정수로 변환 (플레이오토 주문번호는 숫자)
        try:
            order_num = int(order.order_number)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"플레이오토 주문번호 변환 실패: {order.order_number}",
            )

        client = PlayAutoClient(api_key)
        try:
            result = await client.confirm_order([order_num])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"주문확인 실패: {e}")

        await svc.update_order(
            order_id,
            {"shipping_status": "주문확인"},
        )
        logger.info(f"[주문확인] 플레이오토 {order.order_number} 주문확인 완료")
        return {"ok": True, "message": "주문확인 완료", "detail": str(result)}

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
                [{"odNo": order.order_number, "odSeq": 1, "procSeq": 1}]
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
                if str(claim.get("odNo", "")) == str(order.order_number):
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
                        od_no=order.order_number,
                        clm_no=clm_no,
                        items=[
                            {
                                "odSeq": 1,
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
                    od_no=order.order_number,
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
                claim_items = [
                    i for i in raw_returns if i.get("odNo") == order.order_number
                ]
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
                await client.approve_return(order.order_number, clm_no, items_payload)
                new_status = "반품승인"
            elif body.action == "reject":
                await client.reject_return(order.order_number, body.reason or "")
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
                import json
                from sqlmodel import select
                from backend.domain.samba.forbidden.model import SambaSettings

                config_result = await session.execute(
                    select(SambaSettings).where(
                        SambaSettings.key.like("store_lotteon%")
                    )
                )
                lo_settings = config_result.scalars().first()
                if lo_settings:
                    config = (
                        json.loads(lo_settings.value)
                        if isinstance(lo_settings.value, str)
                        else lo_settings.value
                    )
                    client = LotteonClient(config["apiKey"])
                    await client.test_auth()
                    sent = await client.ship_order(
                        od_no=order.order_number,
                        sitm_no=order.shipment_id or order.order_number,
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
                import json
                from sqlmodel import select
                from backend.domain.samba.forbidden.model import SambaSettings
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                config_result = await session.execute(
                    select(SambaSettings).where(
                        SambaSettings.key.like("store_smartstore%")
                    )
                )
                ss_settings = config_result.scalars().first()
                if ss_settings:
                    config = (
                        json.loads(ss_settings.value)
                        if isinstance(ss_settings.value, str)
                        else ss_settings.value
                    )
                    client = SmartStoreClient(
                        config["clientId"], config["clientSecret"]
                    )
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
    import re
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
        active_accounts = [target] if target else []
    else:
        active_accounts = await account_repo.filter_by_async(
            is_active=True, order_by="created_at", order_by_desc=True
        )

    svc = _write_service(session)
    results: list[dict[str, Any]] = []
    total_synced = 0

    for account in active_accounts:
        market_type = account.market_type
        extras = account.additional_fields or {}
        seller_id = account.seller_id or ""
        label = f"{account.market_name}({seller_id})"

        try:
            orders_data: list[dict[str, Any]] = []

            if market_type == "smartstore":
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                client_id = extras.get("clientId", "") or account.api_key or ""
                client_secret = (
                    extras.get("clientSecret", "") or account.api_secret or ""
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
                    orders_data.append(
                        _parse_smartstore_order(po, order_info, account.id, label)
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

            elif market_type == "lotteon":
                from backend.domain.samba.proxy.lotteon import LotteonClient

                api_key = extras.get("apiKey", "") or account.api_key or ""
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
                for ro in raw_orders:
                    orders_data.append(_parse_lotteon_order(ro, account.id, label))

                # ── 정산금액 매칭 (SettleItmdSales) ─────────────────────────
                try:
                    settle_items = await lotteon_client.get_settlement_items(
                        days=body.days
                    )
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
                        if pymt_amt > 0 and gross > 0:
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
                                if od.get("order_number") == ex_od_no:
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
                                existing = await svc.repo.find_by_async(
                                    order_number=ex_od_no
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

                api_key = extras.get("apiKey", "") or account.api_key or ""
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
                        orders_data.append(
                            _parse_playauto_order(ro, account.id, label, alias_map)
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
                # 쿠팡 주문 조회 (구현 대기)
                results.append(
                    {
                        "account": label,
                        "status": "skip",
                        "message": "쿠팡 주문 조회 미구현",
                    }
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
                    "SELECT id, source_site, site_product_id, images, market_product_nos "
                    "FROM samba_collected_product WHERE market_product_nos IS NOT NULL LIMIT 50000"
                )
            )
            _mpn_cache: dict[str, dict] = {}
            _sourcing_urls = {
                "MUSINSA": "https://www.musinsa.com/products/{}",
                "KREAM": "https://kream.co.kr/products/{}",
                "FashionPlus": "https://www.fashionplus.co.kr/goods/detail/{}",
                "ABCmart": "https://www.a-rt.com/product?prdtNo={}",
                "GrandStage": "https://www.a-rt.com/product?prdtNo={}",
                "REXMONDE": "https://www.okmall.com/products/detail/{}",
                "LOTTEON": "https://www.lotteon.com/product/productDetail.lotte?spdNo={}",
                "GSShop": "https://www.gsshop.com/prd/prd.gs?prdid={}",
                "ElandMall": "https://www.elandmall.com/goods/goods.action?goodsNo={}",
                "SSF": "https://www.ssfshop.com/goods/{}",
                "SSG": "https://www.ssg.com/item/itemView.ssg?itemId={}",
                "Nike": "https://www.nike.com/kr/t/{}",
                "Adidas": "https://www.adidas.co.kr/{}.html",
            }
            for _row in _cp_result.fetchall():
                _cpid, _site, _spid, _imgs, _mpnos = _row
                if _mpnos and isinstance(_mpnos, dict):
                    _thumb = (
                        _imgs[0] if _imgs and isinstance(_imgs, list) and _imgs else ""
                    )
                    _olink = (
                        _sourcing_urls.get(_site, "").format(_spid)
                        if _site in _sourcing_urls and _spid
                        else ""
                    )
                    _entry = {
                        "collected_product_id": _cpid,
                        "source_site": _site,
                        "product_image": _thumb,
                        "original_link": _olink,
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
                _tid = account.tenant_id or tenant_id
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
                # order_number 기준 중복 체크 + shipment_id 기반 2차 체크 (발주확인 후 productOrderId 변경 대응)
                existing = await svc.repo.find_by_async(
                    order_number=order_data["order_number"]
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
                    if order_data.get("product_image") and not existing.product_image:
                        update_fields["product_image"] = order_data["product_image"]
                    if order_data.get("source_site") and not existing.source_site:
                        update_fields["source_site"] = order_data["source_site"]
                    if order_data.get("source_url") and not existing.source_url:
                        update_fields["source_url"] = order_data["source_url"]
                    if order_data.get("shipment_id") and not existing.shipment_id:
                        update_fields["shipment_id"] = order_data["shipment_id"]
                    # 결제일 갱신 (마켓 API 값이 정확하므로 항상 갱신)
                    if (
                        order_data.get("paid_at")
                        and order_data["paid_at"] != existing.paid_at
                    ):
                        update_fields["paid_at"] = order_data["paid_at"]
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
                        exchange_statuses = {
                            "교환요청",
                            "교환회수완료",
                            "교환재배송",
                            "교환완료",
                        }
                        advanced = {"발송완료", "배송중", "배송완료", "구매확정"}
                        if new_ship_status in exchange_statuses:
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
            confirmed_count = len(unconfirmed_ids) if market_type == "smartstore" else 0

            # ── 클레임(취소/반품/교환) → SambaReturn 자동 생성 ──────────────
            returns_synced = 0
            claim_statuses = {"취소요청", "반품요청", "교환요청", "취소처리중"}
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
                    "반품요청": "return",
                    "교환요청": "exchange",
                }
                for od in claim_orders:
                    order_no = od.get("order_number", "")
                    if not order_no:
                        continue
                    # 중복 체크
                    existing_ret = await session.execute(
                        _sel(SambaReturn).where(SambaReturn.order_number == order_no)
                    )
                    if existing_ret.scalar_one_or_none():
                        continue
                    # 연결 주문 조회
                    linked_order = await svc.repo.find_by_async(order_number=order_no)
                    if not linked_order:
                        continue
                    ret_type = claim_type_map.get(
                        od.get("shipping_status", ""), "return"
                    )
                    await return_svc.create_return(
                        {
                            "order_id": linked_order.id,
                            "order_number": order_no,
                            "type": ret_type,
                            "status": "requested",
                            "market": label,
                            "market_order_status": od.get("shipping_status", ""),
                            "product_name": od.get("product_name", ""),
                            "product_image": od.get("product_image", ""),
                            "customer_name": od.get("customer_name", ""),
                            "customer_phone": od.get("customer_phone", ""),
                            "customer_address": od.get("customer_address", ""),
                            "requested_amount": od.get("sale_price", 0),
                        }
                    )
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

        except Exception as e:
            await session.rollback()  # 세션 복구 — 다음 계정 연쇄 실패 방지
            logger.error(f"[주문동기화] {label} 실패: {e}")
            results.append({"account": label, "status": "error", "message": str(e)})

    # DB 기반 원주문 shipping_status 일괄 동기화
    # samba_return 레코드가 있고 진행 중인 주문의 shipping_status를 강제 업데이트
    try:
        from sqlalchemy import text as _sa_text_upd

        await session.execute(
            _sa_text_upd("""
            UPDATE samba_order o
            SET shipping_status = CASE
                WHEN r.type = 'exchange' THEN '교환요청'
                WHEN r.type = 'return' THEN '반품요청'
                ELSE o.shipping_status
            END
            FROM samba_return r
            WHERE r.order_id = o.id
              AND r.status NOT IN ('completed', 'cancelled', 'rejected')
              AND o.shipping_status NOT IN (
                  '교환요청', '교환회수완료', '교환재배송', '교환완료',
                  '반품요청', '반품완료', '반품거부'
              )
        """)
        )
        await session.commit()
        logger.info(
            "[주문동기화] 반품/교환 진행 중 원주문 shipping_status 일괄 업데이트 완료"
        )
    except Exception as _upd_err:
        logger.warning(f"[주문동기화] 원주문 일괄 업데이트 실패: {_upd_err}")

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
    po: dict, order_info: dict, account_id: str, account_label: str
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

    # 클레임 상태 (취소/반품/교환 요청 — productOrderStatus와 별도 필드)
    claim_type = po.get("claimType", "")
    claim_status = po.get("claimStatus", "")

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
        "quantity": quantity,
        "sale_price": sale_price,
        "cost": 0,
        "fee_rate": fee_rate,
        "revenue": expected_settlement if expected_settlement else sale_price,
        # 내부 status도 클레임 반영
        "status": (
            "cancel_requested"
            if claim_status in ("CANCEL_REQUEST", "CANCELING")
            else "cancelled"
            if claim_status == "CANCEL_DONE"
            else "return_requested"
            if claim_status in ("RETURN_REQUEST", "COLLECTING", "COLLECT_DONE")
            else "returned"
            if claim_status == "RETURN_DONE"
            else status_map.get(naver_status, "pending")
        ),
        "shipping_status": market_order_status,
        "shipping_company": po.get("deliveryCompany", ""),
        "tracking_number": po.get("trackingNumber", ""),
        "paid_at": _parse_iso_datetime(
            order_info.get("paymentDate") or po.get("paymentDate")
        ),
        "source": "smartstore",
    }


def _parse_lotteon_order(item: dict, account_id: str, label: str) -> dict:
    """롯데ON 주문 데이터 → SambaOrder dict 변환."""
    from datetime import datetime, timezone

    # 주문 진행 단계 코드 → 내부 status/shipping_status 매핑
    step_cd = str(item.get("odPrgsStepCd", "") or "")
    status_map = {
        "10": "pending",  # 발주확인대기
        "11": "pending",  # 발주확인완료(출고지시)
        "12": "pending",  # 상품준비
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

    # 주문 생성일 파싱 (yyyymmddHHmmss) — 롯데ON은 KST 기준
    from backend.utils import kst_str_to_utc

    created_str = item.get("odDttm", "") or ""
    created_at = kst_str_to_utc(created_str)
    if not created_at:
        created_at = datetime.now(timezone.utc)

    # 배송지 주소 조합 (dvpStnmZipAddr=도로명기본주소, dvpStnmDtlAddr=상세주소)
    addr1 = item.get("dvpStnmZipAddr") or ""
    addr2 = item.get("dvpStnmDtlAddr") or ""
    full_addr = f"{addr1} {addr2}".strip()

    return {
        "channel_id": account_id,
        "channel_name": label,
        "source": "lotteon",
        "order_number": str(item.get("odNo", "")),
        "shipment_id": str(item.get("sitmNo", "") or ""),
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
        "notes": item.get("dvMsg", "") or "",
        "paid_at": created_at,
        "created_at": created_at,
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
        "sale_price": sale_price * quantity,
        "cost": int(ro.get("CostPrice", 0) or 0),
        "fee_rate": 0,
        "revenue": supply_price * quantity if supply_price else sale_price * quantity,
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
            else f"{site_name}({site_id})"
            if site_name
            else ""
        ),
    }
