"""SambaWave Order API router."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
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
    limit: int = Query(50, ge=1, le=10000),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.list_orders(skip=skip, limit=limit, status=status)


@router.get("/dashboard-stats")
async def dashboard_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """대시보드 집계 — DB에서 SUM/COUNT 후 결과만 반환 (빠름)."""
    from sqlalchemy import select, func, case, and_, extract, text
    from datetime import datetime, timedelta, timezone as tz

    # 이행매출 대상 상태
    FULFILLMENT_STATUSES = (
        "pending",
        "wait_ship",
        "arrived",
        "shipping",
        "delivered",
        "exchanged",
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


@router.get("/by-date-range", response_model=list[SambaOrder])
async def list_orders_by_date_range(
    start: str = Query(..., description="시작일 YYYY-MM-DD"),
    end: str = Query(..., description="종료일 YYYY-MM-DD"),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """기간별 주문 조회 — COALESCE(paid_at, created_at) 기준, 제한 없이 전체 반환."""
    from sqlalchemy import func, select as sa_select

    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(
        hour=0, minute=0, second=0, tzinfo=UTC
    )
    end_dt = datetime.strptime(end, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=UTC
    )

    order_date = func.coalesce(SambaOrder.paid_at, SambaOrder.created_at)
    stmt = (
        sa_select(SambaOrder)
        .where(order_date >= start_dt, order_date <= end_dt)
        .order_by(order_date.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


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

            if account and account.market_type == "smartstore":
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
                    # 디버그: paid_at 파싱 확인
                    _paid_raw = (
                        order_info.get("paymentDate")
                        or po.get("paymentDate")
                        or order_info.get("orderDate")
                        or po.get("orderDate")
                    )
                    logger.info(
                        f"[paid_at 디버그] ro_keys={list(ro.keys())}, "
                        f"po_keys(date관련)={[k for k in po.keys() if 'date' in k.lower() or 'Date' in k or 'time' in k.lower() or 'pay' in k.lower()]}, "
                        f"order_info_keys={list(order_info.keys())}, "
                        f"paid_raw={_paid_raw!r}"
                    )
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
            elif market_type == "playauto":
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
                        count=5000,
                    )
                    logger.info(f"[주문동기화] 플레이오토: {len(raw_orders)}건 조회")
                    # 디버깅: 첫 주문의 날짜 필드 확인
                    if raw_orders:
                        _s = raw_orders[0]
                        logger.info(
                            f"[플레이오토 날짜] OrderDate={_s.get('OrderDate')!r}, "
                            f"CashDate={_s.get('CashDate')!r}, "
                            f"WriteDate={_s.get('WriteDate')!r}"
                        )
                    for ro in raw_orders:
                        # 파생 주문 스킵 (사본-*, ★교환주문 — 원주문에 이미 정보 포함)
                        _pname = ro.get("ProdName", "")
                        if _pname.startswith("[사본-") or "★교환주문" in _pname:
                            continue
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
                    "SELECT source_site, site_product_id, images, market_product_nos "
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
                "OKmall": "https://www.okmall.com/products/detail/{}",
                "LOTTEON": "https://www.lotteon.com/product/productDetail.lotte?spdNo={}",
                "GSShop": "https://www.gsshop.com/prd/prd.gs?prdid={}",
                "ElandMall": "https://www.elandmall.com/goods/goods.action?goodsNo={}",
                "SSF": "https://www.ssfshop.com/goods/{}",
                "SSG": "https://www.ssg.com/item/itemView.ssg?itemId={}",
                "Nike": "https://www.nike.com/kr/t/{}",
                "Adidas": "https://www.adidas.co.kr/{}.html",
            }
            for _row in _cp_result.fetchall():
                _site, _spid, _imgs, _mpnos = _row
                if _mpnos and isinstance(_mpnos, dict):
                    _thumb = (
                        _imgs[0] if _imgs and isinstance(_imgs, list) and _imgs else ""
                    )
                    _olink = (
                        _sourcing_urls.get(_site, "").format(_spid)
                        if _site in _sourcing_urls and _spid
                        else ""
                    )
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
                                    _mpn_cache[str(_sub_v)] = {
                                        "source_site": _site,
                                        "product_image": _thumb,
                                        "original_link": _olink,
                                    }
                        else:
                            _mpn_cache[str(_v)] = {
                                "source_site": _site,
                                "product_image": _thumb,
                                "original_link": _olink,
                            }

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
            skipped = 0
            for order_data in orders_data:
                try:
                    # 수집상품 매칭 — product_image, source_site, source_url 보충
                    _pid = str(order_data.get("product_id", ""))
                    _matched = _mpn_cache.get(_pid)
                    if _matched:
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
                            order_data["product_image"] = _unreg_matched[
                                "product_image"
                            ]
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
                                    "SELECT source_site, images FROM samba_collected_product WHERE site_product_id = :sid LIMIT 1"
                                ),
                                {"sid": _sid},
                            )
                            _cp_row = _cp_check.fetchone()
                            if _cp_row:
                                order_data["source_site"] = _cp_row[0]
                                order_data["source_url"] = _sourcing_urls.get(
                                    _cp_row[0], ""
                                ).format(_sid)
                                if (
                                    not order_data.get("product_image")
                                    and _cp_row[1]
                                    and isinstance(_cp_row[1], list)
                                ):
                                    order_data["product_image"] = _cp_row[1][0]
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
                    # 디버깅: shipment_id 1005913 추적
                    if order_data.get("shipment_id") == "1005913":
                        logger.info(
                            f"[디버깅 1005913] found={existing is not None}, "
                            f"paid_at_data={order_data.get('paid_at')!r}, "
                            f"paid_at_existing={getattr(existing, 'paid_at', 'N/A')!r}"
                        )
                    if existing:
                        # 기존 주문: sale_price, 이미지, 상태, 마켓주문상태 업데이트
                        update_fields: dict[str, Any] = {}
                        if (
                            order_data.get("sale_price")
                            and order_data["sale_price"] != existing.sale_price
                        ):
                            update_fields["sale_price"] = order_data["sale_price"]
                        if (
                            order_data.get("product_image")
                            and not existing.product_image
                        ):
                            update_fields["product_image"] = order_data["product_image"]
                        if order_data.get("source_site") and not existing.source_site:
                            update_fields["source_site"] = order_data["source_site"]
                        if order_data.get("source_url") and not existing.source_url:
                            update_fields["source_url"] = order_data["source_url"]
                        if order_data.get("shipment_id") and not existing.shipment_id:
                            update_fields["shipment_id"] = order_data["shipment_id"]
                        if order_data.get("paid_at") and not existing.paid_at:
                            update_fields["paid_at"] = order_data["paid_at"]
                            logger.info(
                                f"[paid_at 보충] {existing.order_number} → {order_data['paid_at']}"
                            )
                        # 마켓 상품번호 보충 (기존 주문에 없으면 채움)
                        if order_data.get("product_id") and not existing.product_id:
                            update_fields["product_id"] = order_data["product_id"]
                        if order_data.get("shipping_status"):
                            update_fields["shipping_status"] = order_data[
                                "shipping_status"
                            ]
                        # 플레이오토 주문: 실구매가/배송비는 사용자 입력 전용 — API 값 덮어쓰기 방지 + 기존 값 리셋
                        if order_data.get("source") == "playauto":
                            if existing.cost and existing.cost > 0:
                                update_fields["cost"] = 0
                            if existing.shipping_fee and existing.shipping_fee > 0:
                                update_fields["shipping_fee"] = 0
                        # 내부 status도 갱신 (취소/반품 등 상태 변화 반영)
                        if (
                            order_data.get("status")
                            and order_data["status"] != existing.status
                        ):
                            update_fields["status"] = order_data["status"]
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
                except Exception as _ord_err:
                    await session.rollback()
                    skipped += 1
                    logger.warning(
                        f"[주문동기화] 개별 주문 처리 실패 (order_number={order_data.get('order_number', '?')}): {_ord_err}"
                    )

            # 즉시 커밋 — Cloud Run 타임아웃으로 세션 롤백 방지
            if synced > 0:
                await session.commit()

            total_synced += synced
            confirmed_count = len(unconfirmed_ids) if market_type == "smartstore" else 0
            # 취소/반품/교환 요청 건수 (송장 미입력건만)
            cancel_requested = sum(
                1
                for od in orders_data
                if od.get("shipping_status")
                in ("취소요청", "취소처리중", "반품요청", "교환요청")
                and not od.get("tracking_number")
            )
            results.append(
                {
                    "account": label,
                    "status": "success",
                    "fetched": len(orders_data),
                    "synced": synced,
                    "skipped": skipped,
                    "confirmed": confirmed_count,
                    "cancel_requested": cancel_requested,
                }
            )
            logger.info(
                f"[주문동기화] {label}: {len(orders_data)}건 조회, {synced}건 저장, {skipped}건 스킵, {confirmed_count}건 발주확인"
            )

        except Exception as e:
            logger.error(f"[주문동기화] {label} 실패: {e}")
            results.append({"account": label, "status": "error", "message": str(e)})

    return {"total_synced": total_synced, "results": results}


def _parse_datetime(val: str | datetime | None) -> datetime | None:
    """문자열/datetime → timezone-aware datetime 변환. asyncpg는 str을 거부하므로 필수."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
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
        "source": "smartstore",
        "paid_at": _parse_datetime(
            order_info.get("paymentDate")
            or po.get("paymentDate")
            or order_info.get("orderDate")
            or po.get("orderDate")
        ),
    }


def _parse_playauto_order(
    ro: dict,
    account_id: str,
    account_label: str,
    alias_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """플레이오토 EMP 주문 → SambaOrder 데이터 변환."""
    status_map = {
        "신규주문": "new_order",
        "송장출력": "invoice_printed",
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

    order_state = ro.get("OrderState", "")
    sale_price = int(ro.get("Price", 0) or 0)
    quantity = int(ro.get("Count", 1) or 1)

    site_name = ro.get("SiteName", "")
    site_id = ro.get("SiteId", "")
    supply_price = int(ro.get("SupplyPrice", 0) or 0)

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
        "cost": 0,
        "fee_rate": 0,
        "revenue": supply_price * quantity if supply_price else sale_price * quantity,
        "status": status_map.get(order_state, "pending"),
        "shipping_status": {
            "신규주문": "주문접수",
            "송장출력": "배송대기중",
            "주문확인": "취소중",
            "수취확인": "배송완료",
        }.get(order_state, order_state),
        "shipping_company": ro.get("Sender", ""),
        "tracking_number": ro.get("SenderNo", ""),
        "source": "playauto",
        "paid_at": _parse_datetime(
            ro.get("OrderDate") or ro.get("InsertDate") or ro.get("RegDate")
        ),
        # 판매처(사업자) 정보 — 별칭 매핑 적용
        "source_site": (
            f"{site_name}({alias_map[site_id]})"
            if alias_map and site_id in alias_map and site_name
            else f"{site_name}({site_id})"
            if site_name
            else ""
        ),
    }
