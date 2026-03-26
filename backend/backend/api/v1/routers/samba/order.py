"""SambaWave Order API router."""

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
    limit: int = Query(50, ge=1, le=200),
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
    from sqlalchemy import select, func, case, and_, extract
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 1:
        last_month_start = this_month_start.replace(year=now.year - 1, month=12)
    else:
        last_month_start = this_month_start.replace(month=now.month - 1)
    week_ago = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)

    # 금월 집계
    this_month_q = select(
        func.count().label('count'),
        func.coalesce(func.sum(SambaOrder.sale_price), 0).label('sales'),
        func.sum(case((SambaOrder.status == 'delivered', 1), else_=0)).label('delivered'),
    ).where(SambaOrder.created_at >= this_month_start)
    tm = (await session.execute(this_month_q)).one()

    # 전월 집계
    last_month_q = select(
        func.count().label('count'),
        func.coalesce(func.sum(SambaOrder.sale_price), 0).label('sales'),
        func.sum(case((SambaOrder.status == 'delivered', 1), else_=0)).label('delivered'),
    ).where(and_(SambaOrder.created_at >= last_month_start, SambaOrder.created_at < this_month_start))
    lm = (await session.execute(last_month_q)).one()

    # 최근 7일 일별 집계
    daily_q = select(
        func.date(SambaOrder.created_at).label('day'),
        func.count().label('count'),
        func.coalesce(func.sum(SambaOrder.sale_price), 0).label('sales'),
        func.sum(case((SambaOrder.status == 'delivered', 1), else_=0)).label('delivered'),
    ).where(SambaOrder.created_at >= week_ago).group_by(func.date(SambaOrder.created_at))
    daily_rows = (await session.execute(daily_q)).all()
    weekly = []
    for i in range(7):
        d = week_ago + timedelta(days=i)
        day_str = d.strftime('%Y-%m-%d')
        row = next((r for r in daily_rows if str(r.day) == day_str), None)
        weekly.append({
            'date': day_str,
            'sales': float(row.sales) if row else 0,
            'count': int(row.count) if row else 0,
            'delivered': int(row.delivered) if row else 0,
        })

    # 최근 활동 5건
    recent_q = select(SambaOrder).order_by(SambaOrder.created_at.desc()).limit(5)
    recent = (await session.execute(recent_q)).scalars().all()

    tm_fulfillment = round(int(tm.delivered or 0) / int(tm.count) * 100) if tm.count else 0
    lm_fulfillment = round(int(lm.delivered or 0) / int(lm.count) * 100) if lm.count else 0
    sales_change = round(((float(tm.sales) - float(lm.sales)) / float(lm.sales)) * 100, 1) if lm.sales else 0

    return {
        'thisMonth': {
            'count': int(tm.count), 'sales': float(tm.sales),
            'delivered': int(tm.delivered or 0), 'fulfillment': tm_fulfillment,
        },
        'lastMonth': {
            'count': int(lm.count), 'sales': float(lm.sales),
            'delivered': int(lm.delivered or 0), 'fulfillment': lm_fulfillment,
        },
        'salesChange': sales_change,
        'weekly': weekly,
        'recentOrders': [o.model_dump() for o in recent],
    }


@router.get("/search", response_model=list[SambaOrder])
async def search_orders(
    q: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.search_orders(q)


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
        await svc.update_order(order_id, {
            "shipping_status": "취소완료",
        })
        logger.info(f"[취소승인] {order.order_number} 취소승인 완료")
        return {"ok": True, "message": "취소승인 완료"}
    else:
        raise HTTPException(status_code=400, detail=f"{account.market_type} 취소승인 미지원")


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
    await svc.update_order(order_id, {
        "shipping_company": body.shipping_company,
        "tracking_number": body.tracking_number,
    })

    # 마켓 송장 전송
    market_sent = False
    market_msg = ""

    try:
        if order.channel_id and order.order_number:
            from backend.domain.samba.account.repository import SambaMarketAccountRepository
            account_repo = SambaMarketAccountRepository(session)
            account = await account_repo.get_async(order.channel_id)

            if account and account.market_type == "smartstore":
                import json
                from sqlmodel import select
                from backend.domain.samba.forbidden.model import SambaSettings
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                config_result = await session.execute(
                    select(SambaSettings).where(SambaSettings.key.like("store_smartstore%"))
                )
                ss_settings = config_result.scalars().first()
                if ss_settings:
                    config = json.loads(ss_settings.value) if isinstance(ss_settings.value, str) else ss_settings.value
                    client = SmartStoreClient(config["clientId"], config["clientSecret"])
                    await client.ship_product_order(
                        order.order_number,
                        body.shipping_company,
                        body.tracking_number,
                    )
                    market_sent = True
                    market_msg = "스마트스토어 송장 전송 완료"
                    await svc.update_order(order_id, {"shipping_status": "송장전송완료"})
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
            from backend.domain.samba.forbidden.repository import SambaSettingsRepository
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
                resp = await hc.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                text = resp.text
            m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', text)
            if m:
                return {"image_url": m.group(1).split("?")[0]}
            raise HTTPException(404, "KREAM 상품에서 이미지를 찾을 수 없습니다")

        # ── 범용 fallback (og:image) ──
        else:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as hc:
                resp = await hc.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                text = resp.text
            # og:image 추출
            m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', text)
            if not m:
                # content가 앞에 오는 경우도 처리
                m = re.search(r'<meta[^>]+content="([^"]*)"[^>]+property="og:image"', text)
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
                client_secret = extras.get("clientSecret", "") or account.api_secret or ""
                if not client_id or not client_secret:
                    # fallback: 공유 설정
                    settings_repo = SambaSettingsRepository(session)
                    row = await settings_repo.find_by_async(key="store_smartstore")
                    if row and isinstance(row.value, dict):
                        client_id = client_id or row.value.get("clientId", "")
                        client_secret = client_secret or row.value.get("clientSecret", "")
                if not client_id or not client_secret:
                    results.append({"account": label, "status": "skip", "message": "인증정보 없음"})
                    continue
                client = SmartStoreClient(client_id, client_secret)
                raw_orders = await client.get_orders(days=body.days)
                # 발주 미확인(PAYED) 주문 자동 발주확인
                unconfirmed_ids = []
                for ro in raw_orders:
                    po = ro.get("productOrder", ro)
                    order_info = ro.get("order", {})
                    orders_data.append(_parse_smartstore_order(po, order_info, account.id, label))
                    if po.get("placeOrderStatus") == "NOT_YET" and po.get("productOrderStatus") == "PAYED":
                        unconfirmed_ids.append(po.get("productOrderId", ""))
                # 발주확인 실행
                if unconfirmed_ids:
                    try:
                        await client.confirm_product_orders(unconfirmed_ids)
                        logger.info(f"[주문동기화] {label}: {len(unconfirmed_ids)}건 발주확인 완료")
                    except Exception as ce:
                        logger.warning(f"[주문동기화] {label}: 발주확인 실패 — {ce}")

            elif market_type == "coupang":
                # 쿠팡 주문 조회 (구현 대기)
                results.append({"account": label, "status": "skip", "message": "쿠팡 주문 조회 미구현"})
                continue
            elif market_type == "11st":
                # 11번가 주문 조회 (구현 대기)
                results.append({"account": label, "status": "skip", "message": "11번가 주문 조회 미구현"})
                continue
            else:
                results.append({"account": label, "status": "skip", "message": f"{market_type} 주문 조회 미지원"})
                continue

            # 수집상품 매칭 캐시 구축 (마켓상품번호 → 이미지/소싱처)
            from sqlalchemy import text as _sa_text
            _cp_result = await session.execute(_sa_text(
                "SELECT source_site, site_product_id, images, market_product_nos "
                "FROM samba_collected_product WHERE market_product_nos IS NOT NULL LIMIT 50000"
            ))
            _mpn_cache: dict[str, dict] = {}
            _sourcing_urls = {
                "MUSINSA": "https://www.musinsa.com/app/goods/{}",
                "KREAM": "https://kream.co.kr/products/{}",
                "LOTTEON": "https://www.lotteon.com/product/{}",
                "SSG": "https://www.ssg.com/item/itemView.ssg?itemId={}",
                "ABCmart": "https://abcmart.a-rt.com/product/{}",
                "Nike": "https://www.nike.com/kr/t/{}",
            }
            for _row in _cp_result.fetchall():
                _site, _spid, _imgs, _mpnos = _row
                if _mpnos and isinstance(_mpnos, dict):
                    _thumb = _imgs[0] if _imgs and isinstance(_imgs, list) and _imgs else ""
                    _olink = _sourcing_urls.get(_site, "").format(_spid) if _site in _sourcing_urls and _spid else ""
                    for _k, _v in _mpnos.items():
                        if _v:
                            _mpn_cache[str(_v)] = {"source_site": _site, "product_image": _thumb, "original_link": _olink}

            # 중복 확인 후 저장 (기존 주문은 금액/상태 업데이트)
            synced = 0
            for order_data in orders_data:
                # 수집상품 매칭 — product_image, source_site 보충
                _pid = str(order_data.get("product_id", ""))
                _matched = _mpn_cache.get(_pid)
                if _matched:
                    if not order_data.get("product_image"):
                        order_data["product_image"] = _matched["product_image"]
                    if not order_data.get("source_site"):
                        order_data["source_site"] = _matched["source_site"]
                # order_number 기준 중복 체크
                existing = await svc.repo.find_by_async(order_number=order_data["order_number"])
                if existing:
                    # 기존 주문: sale_price, 이미지, 상태, 마켓주문상태 업데이트
                    update_fields: dict[str, Any] = {}
                    if order_data.get("sale_price") and order_data["sale_price"] != existing.sale_price:
                        update_fields["sale_price"] = order_data["sale_price"]
                    if order_data.get("product_image") and not existing.product_image:
                        update_fields["product_image"] = order_data["product_image"]
                    if order_data.get("source_site") and not existing.source_site:
                        update_fields["source_site"] = order_data["source_site"]
                    if order_data.get("shipment_id") and not existing.shipment_id:
                        update_fields["shipment_id"] = order_data["shipment_id"]
                    # 마켓 상품번호 보충 (기존 주문에 없으면 채움)
                    if order_data.get("product_id") and not existing.product_id:
                        update_fields["product_id"] = order_data["product_id"]
                    if order_data.get("shipping_status"):
                        update_fields["shipping_status"] = order_data["shipping_status"]
                    # 정산금액(revenue) / 수수료율 갱신
                    new_revenue = order_data.get("revenue")
                    new_fee_rate = order_data.get("fee_rate")
                    sp = float(update_fields.get("sale_price", existing.sale_price) or 0)
                    if new_revenue and float(new_revenue) != float(existing.revenue or 0):
                        rev = float(new_revenue)
                        update_fields["revenue"] = rev
                        update_fields["fee_rate"] = new_fee_rate if new_fee_rate is not None else (existing.fee_rate or 0)
                        cost = float(existing.cost or 0)
                        ship_fee = float(existing.shipping_fee or 0)
                        update_fields["profit"] = rev - cost - ship_fee
                        update_fields["profit_rate"] = f"{((rev - cost - ship_fee) / rev * 100):.2f}" if rev > 0 else "0.00"
                    elif "sale_price" in update_fields:
                        fr = float(new_fee_rate if new_fee_rate is not None else (existing.fee_rate or 0))
                        rev = sp * (1 - fr / 100)
                        cost = float(existing.cost or 0)
                        ship_fee = float(existing.shipping_fee or 0)
                        update_fields["revenue"] = rev
                        update_fields["profit"] = rev - cost - ship_fee
                        update_fields["profit_rate"] = f"{((rev - cost - ship_fee) / rev * 100):.2f}" if rev > 0 else "0.00"
                    if update_fields:
                        await svc.update_order(existing.id, update_fields)
                    continue
                await svc.create_order(order_data)
                synced += 1

            total_synced += synced
            confirmed_count = len(unconfirmed_ids) if market_type == "smartstore" else 0
            # 취소/반품/교환 요청 건수 (송장 미입력건만)
            cancel_requested = sum(
                1 for od in orders_data
                if od.get("shipping_status") in ("취소요청", "취소처리중", "반품요청", "교환요청")
                and not od.get("tracking_number")
            )
            results.append({
                "account": label, "status": "success",
                "fetched": len(orders_data), "synced": synced,
                "confirmed": confirmed_count,
                "cancel_requested": cancel_requested,
            })
            logger.info(f"[주문동기화] {label}: {len(orders_data)}건 조회, {synced}건 저장, {confirmed_count}건 발주확인")

        except Exception as e:
            logger.error(f"[주문동기화] {label} 실패: {e}")
            results.append({"account": label, "status": "error", "message": str(e)})

    return {"total_synced": total_synced, "results": results}


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
        po.get("channelProductNo", "")
        or po.get("productId", "")
        or ""
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
        "customer_address": (shipping.get("baseAddress", "") + " " + shipping.get("detailedAddress", "")).strip(),
        "quantity": quantity,
        "sale_price": sale_price,
        "cost": 0,
        "fee_rate": fee_rate,
        "revenue": expected_settlement if expected_settlement else sale_price,
        # 내부 status도 클레임 반영
        "status": (
            "cancel_requested" if claim_status in ("CANCEL_REQUEST", "CANCELING") else
            "cancelled" if claim_status == "CANCEL_DONE" else
            "return_requested" if claim_status in ("RETURN_REQUEST", "COLLECTING", "COLLECT_DONE") else
            "returned" if claim_status == "RETURN_DONE" else
            status_map.get(naver_status, "pending")
        ),
        "shipping_status": market_order_status,
        "shipping_company": po.get("deliveryCompany", ""),
        "tracking_number": po.get("trackingNumber", ""),
        "source": "smartstore",
    }
