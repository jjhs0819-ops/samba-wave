"""SambaWave Returns API router."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.dtos.samba.returns import (
    ExchangeActionBody as ExchangeActionBodyDTO,
    ExchangeTrackingPatchBody as ExchangeTrackingPatchBodyDTO,
    ReturnCreate,
    ReturnNoteBody,
    ReturnRejectBody,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/returns", tags=["samba-returns"])


def _read_service(session: AsyncSession):
    from backend.domain.samba.returns.repository import SambaReturnRepository
    from backend.domain.samba.returns.service import SambaReturnService

    return SambaReturnService(SambaReturnRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.returns.repository import SambaReturnRepository
    from backend.domain.samba.returns.service import SambaReturnService

    return SambaReturnService(SambaReturnRepository(session))


@router.get("/stats")
async def get_return_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    return await svc.get_return_stats()


@router.get("/reasons")
async def get_return_reasons():
    from backend.domain.samba.returns.service import SambaReturnService

    return SambaReturnService.get_return_reasons()


@router.get("")
async def list_returns(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    order_id: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    returns = await svc.list_returns(
        skip=skip, limit=limit, order_id=order_id, status=status, type=type
    )

    # 주문의 ext_order_number(타마켓주문링크) 또는 소싱처 주문상세 URL을 return_link로 매칭
    # 주문탭 원주문링크와 100% 동일한 로직
    from backend.domain.samba.order.repository import SambaOrderRepository

    order_repo = SambaOrderRepository(session)
    order_ids = list({r.order_id for r in returns if r.order_id})
    link_map: dict[str, str] = {}
    if order_ids:
        from backend.domain.samba.order.model import SambaOrder
        from sqlmodel import select, col

        stmt = select(
            SambaOrder.id,
            SambaOrder.ext_order_number,
            SambaOrder.source_site,
            SambaOrder.sourcing_order_number,
        ).where(col(SambaOrder.id).in_(order_ids))
        rows = (await session.execute(stmt)).all()
        # 소싱처별 주문상세 URL 템플릿 (주문탭 orderUrlMap과 동일)
        _order_detail_urls: dict[str, str] = {
            "MUSINSA": "https://www.musinsa.com/order/order-detail/{}",
            "KREAM": "https://kream.co.kr/my/purchasing/{}",
            "FashionPlus": "https://www.fashionplus.co.kr/mypage/order/detail/{}",
            "ABCmart": "https://www.a-rt.com/mypage/order-detail/{}",
            "Nike": "https://www.nike.com/kr/orders/{}",
        }
        for row in rows:
            # 1순위: 타마켓주문링크
            if row.ext_order_number:
                link_map[row.id] = row.ext_order_number
            # 2순위: 소싱처 구매주문번호 + 소싱처별 URL
            elif row.source_site and row.sourcing_order_number:
                tpl = _order_detail_urls.get(row.source_site, "")
                if tpl:
                    link_map[row.id] = tpl.format(row.sourcing_order_number)

    results = []
    for r in returns:
        data = r.model_dump() if hasattr(r, "model_dump") else r.__dict__.copy()
        # 동적 생성 우선 → DB 값은 사용하지 않음 (하드코딩 방지)
        data["return_link"] = link_map.get(r.order_id) or None
        results.append(data)
    return results


@router.post("", status_code=201)
async def create_return(
    body: ReturnCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    return await svc.create_return(body.model_dump(exclude_unset=True))


@router.get("/{return_id}")
async def get_return(
    return_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    ret = await svc.get_return(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    return ret


@router.put("/{return_id}/approve")
async def approve_return(
    return_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    ret = await svc.approve_return(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    return ret


@router.put("/{return_id}/reject")
async def reject_return(
    return_id: str,
    body: ReturnRejectBody,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    ret = await svc.reject_return(return_id, reason=body.reason)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    return ret


@router.put("/{return_id}/complete")
async def complete_return(
    return_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    ret = await svc.complete_return(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    return ret


@router.put("/{return_id}/cancel")
async def cancel_return(
    return_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    ret = await svc.cancel_return(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    return ret


@router.post("/{return_id}/note")
async def add_note(
    return_id: str,
    body: ReturnNoteBody,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    ret = await svc.add_note(return_id, body.note)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    return ret


# ══════════════════════════════════════════════
# 확인 토글 + 금액 업데이트
# ══════════════════════════════════════════════


class ReturnPatchBody(BaseModel):
    confirmed: Optional[bool] = None
    settlement_amount: Optional[float] = None
    recovery_amount: Optional[float] = None
    check_date: Optional[str] = None
    memo: Optional[str] = None
    product_location: Optional[str] = None
    completion_detail: Optional[str] = None
    status: Optional[str] = None
    customer_order_no: Optional[str] = None
    original_order_no: Optional[str] = None


@router.patch("/{return_id}")
async def patch_return(
    return_id: str,
    body: ReturnPatchBody,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """확인 체크박스, 정산금액, 환수금액 등 부분 업데이트."""
    svc = _write_service(session)
    ret = await svc.repo.get_async(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    update_fields: dict[str, Any] = {}
    if body.confirmed is not None:
        update_fields["confirmed"] = body.confirmed
    if body.settlement_amount is not None:
        update_fields["settlement_amount"] = body.settlement_amount
    if body.recovery_amount is not None:
        update_fields["recovery_amount"] = body.recovery_amount
    if body.check_date is not None:
        from datetime import datetime, timezone

        update_fields["check_date"] = (
            datetime.fromisoformat(body.check_date).replace(tzinfo=timezone.utc)
            if body.check_date
            else None
        )
    if body.memo is not None:
        update_fields["memo"] = body.memo
    if body.product_location is not None:
        update_fields["product_location"] = body.product_location
    if body.completion_detail is not None:
        update_fields["completion_detail"] = body.completion_detail
    if body.status is not None:
        update_fields["status"] = body.status
    if body.customer_order_no is not None:
        update_fields["customer_order_no"] = body.customer_order_no
    if body.original_order_no is not None:
        update_fields["original_order_no"] = body.original_order_no
    if not update_fields:
        return ret
    return await svc.repo.update_async(return_id, **update_fields)


# ══════════════════════════════════════════════
# 마켓 반품/교환/취소 동기화
# ══════════════════════════════════════════════

# 스마트스토어 claimType → SambaReturn.type 매핑
_CLAIM_TYPE_MAP: dict[str, str] = {
    "CANCEL": "cancel",
    "RETURN": "return",
    "EXCHANGE": "exchange",
}

# 스마트스토어 claimStatus → SambaReturn.status 매핑
_CLAIM_STATUS_MAP: dict[str, str] = {
    "CANCEL_REQUEST": "requested",
    "CANCELING": "approved",
    "CANCEL_DONE": "completed",
    "CANCEL_REJECT": "rejected",
    "RETURN_REQUEST": "requested",
    "COLLECTING": "approved",
    "COLLECT_DONE": "approved",
    "RETURN_DONE": "completed",
    "RETURN_REJECT": "rejected",
    "EXCHANGE_REQUEST": "requested",
    "EXCHANGING": "approved",
    "EXCHANGE_DONE": "completed",
    "EXCHANGE_REJECT": "rejected",
}

# claimStatus → 한글 CS 표시명
_CLAIM_STATUS_DISPLAY: dict[str, str] = {
    "CANCEL_REQUEST": "취소요청",
    "CANCELING": "취소중",
    "CANCEL_DONE": "취소완료",
    "CANCEL_REJECT": "취소거부",
    "RETURN_REQUEST": "반품요청",
    "COLLECTING": "수거중",
    "COLLECT_DONE": "수거완료",
    "RETURN_DONE": "반품완료",
    "RETURN_REJECT": "반품거부",
    "EXCHANGE_REQUEST": "교환요청",
    "EXCHANGING": "교환중",
    "EXCHANGE_DONE": "교환완료",
    "EXCHANGE_REJECT": "교환거부",
}

# claimStatus → 한글 타임라인 메시지
_CLAIM_STATUS_LABEL: dict[str, str] = {
    "CANCEL_REQUEST": "취소 요청이 접수되었습니다.",
    "CANCELING": "취소가 처리 중입니다.",
    "CANCEL_DONE": "취소가 완료되었습니다.",
    "CANCEL_REJECT": "취소 요청이 거부되었습니다.",
    "RETURN_REQUEST": "반품 요청이 접수되었습니다.",
    "COLLECTING": "반품 수거가 진행 중입니다.",
    "COLLECT_DONE": "반품 수거가 완료되었습니다.",
    "RETURN_DONE": "반품이 완료되었습니다.",
    "RETURN_REJECT": "반품 요청이 거부되었습니다.",
    "EXCHANGE_REQUEST": "교환 요청이 접수되었습니다.",
    "EXCHANGING": "교환이 처리 중입니다.",
    "EXCHANGE_DONE": "교환이 완료되었습니다.",
    "EXCHANGE_REJECT": "교환 요청이 거부되었습니다.",
}


def _extract_city_district(address: Optional[str]) -> Optional[str]:
    """주소에서 시/군 단위를 추출한다.
    - '경기도 수원시 팔달구...' → '수원시'
    - '부산광역시 남동구...' → '부산시'
    - '서울특별시 강남구...' → '서울시'
    - '세종특별자치시...' → '세종시'
    """
    if not address:
        return None
    parts = address.split()
    # 광역시/특별시/특별자치시 → "XX시" 형태로 변환
    first = parts[0] if parts else ""
    if first.endswith(("광역시", "특별시", "특별자치시")):
        city_name = (
            first.replace("광역시", "").replace("특별자치시", "").replace("특별시", "")
        )
        return f"{city_name}시"
    # 도 다음의 시/군 반환
    for p in parts[1:]:
        if p.endswith(("시", "군")):
            return p
    return parts[0] if parts else None


class SyncReturnsRequest(BaseModel):
    days: int = 7
    account_id: Optional[str] = None


@router.post("/sync-from-markets")
async def sync_returns_from_markets(
    body: SyncReturnsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """활성 마켓 계정에서 반품/교환/취소 데이터를 가져와 DB에 저장."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    from backend.domain.samba.order.repository import SambaOrderRepository

    account_repo = SambaMarketAccountRepository(session)
    order_repo = SambaOrderRepository(session)

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

    # 마켓 타입 → 한글 마켓명
    market_label_map: dict[str, str] = {
        "smartstore": "스마트스토어",
        "coupang": "쿠팡",
        "11st": "11번가",
        "lotteon": "롯데ON",
        "ssg": "SSG",
        "gsshop": "GS샵",
    }

    # 주문 status → 반품 type 매핑
    _ORDER_STATUS_TO_RETURN_TYPE: dict[str, str] = {
        "cancelled": "cancel",
        "cancel_requested": "cancel",
        "returned": "return",
        "return_requested": "return",
    }

    # ── 1단계: DB 기반 — samba_order에서 취소/반품 주문 직접 조회 ──
    from sqlalchemy import text as sa_text

    account_ids = [acc.id for acc in active_accounts]
    if account_ids:
        # 취소/반품 상태 주문 중 아직 samba_return이 없는 것
        placeholders = ", ".join(f":aid_{i}" for i in range(len(account_ids)))
        bind_params = {f"aid_{i}": aid for i, aid in enumerate(account_ids)}
        bind_params["days"] = body.days

        claim_orders_query = sa_text(f"""
            SELECT o.* FROM samba_order o
            LEFT JOIN samba_return r ON r.order_id = o.id
            WHERE o.channel_id IN ({placeholders})
              AND o.status IN ('cancelled','cancel_requested','returned','return_requested')
              AND o.created_at >= now() - make_interval(days => :days)
              AND r.id IS NULL
            ORDER BY o.created_at DESC
        """)
        result = await session.execute(claim_orders_query, bind_params)
        claim_orders = result.mappings().all()

        db_synced = 0
        for row in claim_orders:
            order_status = row["status"]
            return_type = _ORDER_STATUS_TO_RETURN_TYPE.get(order_status)
            if not return_type:
                continue

            # 해당 주문의 계정 찾기
            acct = next((a for a in active_accounts if a.id == row["channel_id"]), None)
            if not acct:
                continue

            from datetime import UTC, datetime

            is_completed = order_status in ("cancelled", "returned")
            ret_status = "completed" if is_completed else "requested"
            shipping = row.get("shipping_status", "") or ""

            timeline_entries = [
                {
                    "date": datetime.now(UTC).isoformat(),
                    "status": ret_status,
                    "message": f"{shipping or order_status} (주문 데이터 기반 동기화)",
                }
            ]

            return_data: dict[str, Any] = {
                "order_id": row["id"],
                "order_number": row["order_number"],
                "type": return_type,
                "reason": None,
                "description": row.get("product_name") or None,
                "quantity": row.get("quantity", 1) or 1,
                "requested_amount": float(row.get("sale_price", 0) or 0),
                "product_image": row.get("product_image"),
                "product_name": row.get("product_name"),
                "customer_name": row.get("customer_name"),
                "customer_phone": row.get("customer_phone"),
                "product_location": _extract_city_district(row.get("customer_address")),
                "customer_address": row.get("customer_address"),
                "business_name": acct.business_name or acct.market_name or "",
                "market": market_label_map.get(acct.market_type, acct.market_type),
                "market_order_status": shipping,
                "return_link": row.get("source_url") or "",
                "return_source": row.get("source_site") or "",
                "region": _extract_city_district(row.get("customer_address")),
                "return_request_date": datetime.now(UTC),
                "order_date": row.get("created_at"),
                "status": ret_status,
                "timeline": timeline_entries,
                "notes": [],
            }
            if is_completed:
                return_data["approval_date"] = datetime.now(UTC)
                return_data["completion_date"] = datetime.now(UTC)

            await svc.repo.create_async(**return_data)
            db_synced += 1

        if db_synced > 0:
            total_synced += db_synced
            logger.info(f"[반품동기화] DB 기반: {db_synced}건 신규 저장")

    # ── 2단계: API 기반 — 마켓별 실시간 클레임 조회 (추가 보완) ──
    for account in active_accounts:
        market_type = account.market_type
        extras = account.additional_fields or {}
        seller_id = account.seller_id or ""
        label = f"{account.market_name}({seller_id})"

        try:
            if market_type == "smartstore":
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                client_id = extras.get("clientId", "") or account.api_key or ""
                client_secret = (
                    extras.get("clientSecret", "") or account.api_secret or ""
                )
                if not client_id or not client_secret:
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

                # 클레임이 있는 주문만 필터
                claims_data: list[dict[str, Any]] = []
                for ro in raw_orders:
                    po = ro.get("productOrder", ro)
                    claim_type = po.get("claimType", "")
                    claim_status = po.get("claimStatus", "")
                    if not claim_type or not claim_status:
                        continue
                    if claim_status not in _CLAIM_STATUS_MAP:
                        continue

                    return_type = _CLAIM_TYPE_MAP.get(claim_type)
                    if not return_type:
                        continue

                    product_order_id = po.get("productOrderId", "")
                    sale_price = (
                        po.get("totalPaymentAmount", 0) or po.get("unitPrice", 0) or 0
                    )
                    quantity = po.get("quantity", 1) or 1
                    claim_reason = (
                        po.get("claimReason", "") or po.get("returnReason", "") or ""
                    )

                    claims_data.append(
                        {
                            "product_order_id": product_order_id,
                            "type": return_type,
                            "status": _CLAIM_STATUS_MAP[claim_status],
                            "claim_status_raw": claim_status,
                            "display_status": _CLAIM_STATUS_DISPLAY.get(
                                claim_status, claim_status
                            ),
                            "reason": claim_reason,
                            "quantity": quantity,
                            "requested_amount": float(sale_price),
                            "product_name": po.get("productName", ""),
                            "product_image": po.get("imageUrl", ""),
                            "product_option": po.get("productOption", "") or "",
                        }
                    )

                # API 클레임 → 반품 레코드 생성/업데이트
                synced = 0
                for claim in claims_data:
                    product_order_id = claim["product_order_id"]
                    existing_order = await order_repo.find_by_async(
                        order_number=product_order_id
                    )
                    if not existing_order:
                        continue

                    order_id = existing_order.id
                    existing_returns = await svc.repo.filter_by_async(order_id=order_id)

                    if existing_returns:
                        # 기존 레코드 업데이트
                        existing_ret = next(
                            (r for r in existing_returns if r.type == claim["type"]),
                            existing_returns[0],
                        )
                        if existing_ret.type != claim["type"]:
                            await svc.repo.update_async(
                                existing_ret.id, type=claim["type"]
                            )
                        new_status = claim["status"]
                        status_priority = {
                            "requested": 0,
                            "approved": 1,
                            "completed": 2,
                            "rejected": 2,
                            "cancelled": 2,
                        }
                        if status_priority.get(new_status, 0) > status_priority.get(
                            existing_ret.status, 0
                        ):
                            from datetime import UTC, datetime

                            timeline = list(existing_ret.timeline or [])
                            timeline.append(
                                {
                                    "date": datetime.now(UTC).isoformat(),
                                    "status": new_status,
                                    "message": _CLAIM_STATUS_LABEL.get(
                                        claim["claim_status_raw"],
                                        f"상태: {new_status}",
                                    ),
                                }
                            )
                            update_data: dict[str, Any] = {
                                "status": new_status,
                                "timeline": timeline,
                                "market_order_status": claim["display_status"],
                            }
                            if new_status == "approved":
                                update_data["approval_date"] = datetime.now(UTC)
                            elif new_status == "completed":
                                update_data["completion_date"] = datetime.now(UTC)
                            await svc.repo.update_async(existing_ret.id, **update_data)
                        # 이미지/전화번호/주소 보충
                        patch_fields: dict[str, Any] = {}
                        if claim["product_image"] and not existing_ret.product_image:
                            patch_fields["product_image"] = claim["product_image"]
                        if (
                            existing_order.customer_phone
                            and not existing_ret.customer_phone
                        ):
                            patch_fields["customer_phone"] = (
                                existing_order.customer_phone
                            )
                        if existing_order.customer_address:
                            new_loc = _extract_city_district(
                                existing_order.customer_address
                            )
                            if new_loc and new_loc != existing_ret.product_location:
                                patch_fields["product_location"] = new_loc
                            if not existing_ret.customer_address:
                                patch_fields["customer_address"] = (
                                    existing_order.customer_address
                                )
                        if patch_fields:
                            await svc.repo.update_async(existing_ret.id, **patch_fields)
                        continue

                    # 신규 반품 생성 (API 데이터 기반 — DB보다 상세)
                    from datetime import UTC, datetime

                    claim_status_raw = claim["claim_status_raw"]
                    timeline_entries = [
                        {
                            "date": datetime.now(UTC).isoformat(),
                            "status": claim["status"],
                            "message": _CLAIM_STATUS_LABEL.get(
                                claim_status_raw,
                                f"{claim['type']} 요청이 접수되었습니다.",
                            ),
                        }
                    ]

                    return_data = {
                        "order_id": order_id,
                        "order_number": product_order_id,
                        "type": claim["type"],
                        "reason": claim["reason"] or None,
                        "description": f"{claim['product_name']} {claim['product_option']}".strip()
                        or None,
                        "quantity": claim["quantity"],
                        "requested_amount": claim["requested_amount"],
                        "product_image": claim["product_image"]
                        or existing_order.product_image,
                        "product_name": claim["product_name"]
                        or existing_order.product_name,
                        "customer_name": existing_order.customer_name,
                        "customer_phone": existing_order.customer_phone,
                        "product_location": _extract_city_district(
                            existing_order.customer_address
                        ),
                        "customer_address": existing_order.customer_address,
                        "business_name": account.business_name
                        or account.market_name
                        or label,
                        "market": market_label_map.get(market_type, market_type),
                        "market_order_status": claim["display_status"],
                        "return_link": existing_order.source_url or "",
                        "return_source": existing_order.source_site or "",
                        "region": _extract_city_district(
                            existing_order.customer_address
                        ),
                        "return_request_date": datetime.now(UTC),
                        "order_date": existing_order.created_at,
                        "status": claim["status"],
                        "timeline": timeline_entries,
                        "notes": [],
                    }
                    if claim["status"] in ("approved", "completed"):
                        return_data["approval_date"] = datetime.now(UTC)
                    if claim["status"] == "completed":
                        return_data["completion_date"] = datetime.now(UTC)

                    await svc.repo.create_async(**return_data)
                    synced += 1

                api_fetched = len(claims_data)
                total_synced += synced
                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "fetched": api_fetched,
                        "synced": synced,
                    }
                )
                logger.info(
                    f"[반품동기화] {label}: API {api_fetched}건, 신규 {synced}건"
                )

            elif market_type == "11st":
                # 11번가 교환/취소 요청 동기화
                api_key = account.api_key or extras.get("apiKey", "")
                if not api_key:
                    results.append(
                        {"account": label, "status": "skip", "message": "API 키 없음"}
                    )
                    continue

                from backend.domain.samba.proxy.elevenst_exchange import (
                    ElevenstExchangeClient,
                    ElevenstApiError,
                )

                elevenst_client = ElevenstExchangeClient(api_key)

                from datetime import UTC, datetime, timedelta

                end_dt = datetime.now()  # 로컬 KST 기준 (11번가 API는 KST 시각 사용)
                start_dt = end_dt - timedelta(days=body.days)
                fmt = "%Y%m%d%H%M"

                try:
                    exchange_items = await elevenst_client.get_exchange_requests(
                        start_dt.strftime(fmt), end_dt.strftime(fmt)
                    )
                except ElevenstApiError as e:
                    logger.warning(f"[반품동기화] {label} 11번가 교환 조회 실패: {e}")
                    exchange_items = []

                synced = 0
                for item in exchange_items:
                    ord_no = item.get("ordNo", "")
                    ord_prd_seq = item.get("ordPrdSeq", "")
                    clm_req_seq = item.get("clmReqSeq", "")
                    # 11번가는 ordPrdNo(상품주문번호)를 order_number로 사용
                    order_number = item.get("ordPrdNo", "") or ord_no

                    if not order_number:
                        continue

                    existing_order = await order_repo.find_by_async(
                        order_number=order_number
                    )
                    if not existing_order:
                        # ordNo로도 재시도
                        if ord_no and ord_no != order_number:
                            existing_order = await order_repo.find_by_async(
                                order_number=ord_no
                            )
                    if not existing_order:
                        continue

                    order_id = existing_order.id
                    existing_returns = await svc.repo.filter_by_async(
                        order_id=order_id, type="exchange"
                    )

                    status_raw = item.get("ordPrdStatCd", "") or item.get(
                        "clmStatCd", ""
                    )
                    mapped_status = "requested"

                    timeline_msg = "11번가 교환 요청이 접수되었습니다."
                    if existing_returns:
                        # 기존 레코드 — clm_req_seq/ord_prd_seq 보완
                        existing_ret = existing_returns[0]
                        patch: dict[str, Any] = {}
                        if clm_req_seq and not existing_ret.clm_req_seq:
                            patch["clm_req_seq"] = clm_req_seq
                        if ord_prd_seq and not existing_ret.ord_prd_seq:
                            patch["ord_prd_seq"] = ord_prd_seq
                        if patch:
                            await svc.repo.update_async(existing_ret.id, **patch)
                        continue

                    # 신규 교환 레코드 생성
                    timeline_entries = [
                        {
                            "date": datetime.now(UTC).isoformat(),
                            "status": mapped_status,
                            "message": timeline_msg,
                        }
                    ]

                    return_data: dict[str, Any] = {
                        "order_id": order_id,
                        "order_number": order_number,
                        "type": "exchange",
                        "reason": item.get("clmRsn") or None,
                        "description": item.get("prdNm") or existing_order.product_name,
                        "quantity": int(item.get("qty", 1) or 1),
                        "requested_amount": float(item.get("sellAmt", 0) or 0),
                        "product_image": existing_order.product_image,
                        "product_name": item.get("prdNm")
                        or existing_order.product_name,
                        "customer_name": item.get("buyMbrNm")
                        or existing_order.customer_name,
                        "customer_phone": item.get("rcvTelNo")
                        or existing_order.customer_phone,
                        "product_location": _extract_city_district(
                            item.get("rcvAddr") or existing_order.customer_address
                        ),
                        "customer_address": item.get("rcvAddr")
                        or existing_order.customer_address,
                        "business_name": account.business_name
                        or account.market_name
                        or label,
                        "market": "11번가",
                        "market_order_status": "교환요청",
                        "return_link": existing_order.source_url or "",
                        "return_source": existing_order.source_site or "",
                        "region": _extract_city_district(
                            item.get("rcvAddr") or existing_order.customer_address
                        ),
                        "return_request_date": datetime.now(UTC),
                        "order_date": existing_order.created_at,
                        "status": mapped_status,
                        "timeline": timeline_entries,
                        "notes": [],
                        # 11번가 교환 클레임 식별자
                        "clm_req_seq": clm_req_seq or None,
                        "ord_prd_seq": ord_prd_seq or None,
                    }

                    await svc.repo.create_async(**return_data)
                    synced += 1

                exchange_synced = synced

                # 11번가 취소 요청 동기화
                from backend.domain.samba.proxy.elevenst import ElevenstClient

                elevenst_order_client = ElevenstClient(api_key)
                try:
                    cancel_items = await elevenst_order_client.get_cancel_requests(
                        start_dt.strftime(fmt), end_dt.strftime(fmt)
                    )
                except Exception as ce:
                    logger.warning(f"[반품동기화] {label} 11번가 취소 조회 실패: {ce}")
                    cancel_items = []

                cancel_synced = 0
                for item in cancel_items:
                    ord_no = item.get("ordNo", "")
                    ord_prd_seq = item.get("ordPrdSeq", "")
                    ord_prd_cn_seq = item.get("ordPrdCnSeq", "")
                    order_number = item.get("ordPrdNo", "") or ord_no

                    if not order_number:
                        continue

                    existing_order = await order_repo.find_by_async(
                        order_number=order_number
                    )
                    if not existing_order and ord_no and ord_no != order_number:
                        existing_order = await order_repo.find_by_async(
                            order_number=ord_no
                        )
                    if not existing_order:
                        continue

                    # 이미 취소 레코드가 있으면 스킵
                    existing_cancels = await svc.repo.filter_by_async(
                        order_id=existing_order.id, type="cancel"
                    )
                    if existing_cancels:
                        continue

                    from datetime import UTC, datetime as _dt

                    timeline_entries = [
                        {
                            "date": _dt.now(UTC).isoformat(),
                            "status": "requested",
                            "message": "11번가 취소 요청이 접수되었습니다.",
                        }
                    ]
                    return_data = {
                        "order_id": existing_order.id,
                        "order_number": order_number,
                        "type": "cancel",
                        "reason": item.get("cnRsnCd") or None,
                        "description": item.get("prdNm") or existing_order.product_name,
                        "quantity": int(item.get("qty", 1) or 1),
                        "requested_amount": float(item.get("sellAmt", 0) or 0),
                        "product_image": existing_order.product_image,
                        "product_name": item.get("prdNm")
                        or existing_order.product_name,
                        "customer_name": existing_order.customer_name,
                        "customer_phone": existing_order.customer_phone,
                        "customer_address": existing_order.customer_address,
                        "product_location": _extract_city_district(
                            existing_order.customer_address
                        ),
                        "business_name": account.business_name
                        or account.market_name
                        or label,
                        "market": "11번가",
                        "market_order_status": "취소요청",
                        "return_link": existing_order.source_url or "",
                        "return_source": existing_order.source_site or "",
                        "region": _extract_city_district(
                            existing_order.customer_address
                        ),
                        "return_request_date": _dt.now(UTC),
                        "order_date": existing_order.created_at,
                        "status": "requested",
                        "timeline": timeline_entries,
                        "notes": [],
                        "clm_req_seq": ord_prd_cn_seq or None,
                        "ord_prd_seq": ord_prd_seq or None,
                    }
                    await svc.repo.create_async(**return_data)
                    # 주문 상태도 취소요청으로 업데이트
                    await order_repo.update_async(
                        existing_order.id,
                        status="cancel_requested",
                        shipping_status="취소요청",
                    )
                    cancel_synced += 1

                # 11번가 반품 요청 동기화
                try:
                    return_items = await elevenst_order_client.get_return_requests(
                        start_dt.strftime(fmt), end_dt.strftime(fmt)
                    )
                except Exception as re:
                    logger.warning(f"[반품동기화] {label} 11번가 반품 조회 실패: {re}")
                    return_items = []

                return_synced = 0
                for item in return_items:
                    ord_no = item.get("ordNo", "")
                    ord_prd_seq = item.get("ordPrdSeq", "")
                    clm_req_seq = item.get("clmReqSeq", "")
                    order_number = item.get("ordPrdNo", "") or ord_no

                    if not order_number:
                        continue

                    existing_order = await order_repo.find_by_async(
                        order_number=order_number
                    )
                    if not existing_order and ord_no and ord_no != order_number:
                        existing_order = await order_repo.find_by_async(
                            order_number=ord_no
                        )
                    if not existing_order:
                        continue

                    # 이미 반품 레코드가 있으면 clm_req_seq/ord_prd_seq 보완 후 스킵
                    existing_returns = await svc.repo.filter_by_async(
                        order_id=existing_order.id, type="return"
                    )
                    if existing_returns:
                        existing_ret = existing_returns[0]
                        patch: dict[str, Any] = {}
                        if clm_req_seq and not existing_ret.clm_req_seq:
                            patch["clm_req_seq"] = clm_req_seq
                        if ord_prd_seq and not existing_ret.ord_prd_seq:
                            patch["ord_prd_seq"] = ord_prd_seq
                        if patch:
                            await svc.repo.update_async(existing_ret.id, **patch)
                        continue

                    from datetime import UTC, datetime as _dt

                    timeline_entries = [
                        {
                            "date": _dt.now(UTC).isoformat(),
                            "status": "requested",
                            "message": "11번가 반품 요청이 접수되었습니다.",
                        }
                    ]
                    return_data = {
                        "order_id": existing_order.id,
                        "order_number": order_number,
                        "type": "return",
                        "reason": item.get("returnRsnCd")
                        or item.get("clmRsnCd")
                        or None,
                        "description": item.get("prdNm") or existing_order.product_name,
                        "quantity": int(item.get("qty", 1) or 1),
                        "requested_amount": float(item.get("sellAmt", 0) or 0),
                        "product_image": existing_order.product_image,
                        "product_name": item.get("prdNm")
                        or existing_order.product_name,
                        "customer_name": existing_order.customer_name,
                        "customer_phone": existing_order.customer_phone,
                        "customer_address": existing_order.customer_address,
                        "product_location": _extract_city_district(
                            existing_order.customer_address
                        ),
                        "business_name": account.business_name
                        or account.market_name
                        or label,
                        "market": "11번가",
                        "market_order_status": "반품요청",
                        "return_link": existing_order.source_url or "",
                        "return_source": existing_order.source_site or "",
                        "region": _extract_city_district(
                            existing_order.customer_address
                        ),
                        "return_request_date": _dt.now(UTC),
                        "order_date": existing_order.created_at,
                        "status": "requested",
                        "timeline": timeline_entries,
                        "notes": [],
                        "clm_req_seq": clm_req_seq or None,
                        "ord_prd_seq": ord_prd_seq or None,
                    }
                    await svc.repo.create_async(**return_data)
                    # 주문 상태 반품요청으로 업데이트
                    await order_repo.update_async(
                        existing_order.id,
                        status="return_requested",
                        shipping_status="반품요청",
                    )
                    return_synced += 1

                logger.info(
                    f"[반품동기화] {label}: 11번가 교환 {len(exchange_items)}건({exchange_synced}건 신규), 취소 {len(cancel_items)}건({cancel_synced}건 신규), 반품 {len(return_items)}건({return_synced}건 신규)"
                )
                synced = exchange_synced + cancel_synced + return_synced
                total_synced += synced
                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "fetched": len(exchange_items)
                        + len(cancel_items)
                        + len(return_items),
                        "synced": synced,
                    }
                )

            else:
                results.append(
                    {
                        "account": label,
                        "status": "skip",
                        "message": f"{market_type} 반품 조회 미지원",
                    }
                )
                continue

        except Exception as e:
            logger.error(f"[반품동기화] {label} 실패: {e}")
            results.append({"account": label, "status": "error", "message": str(e)})

    # db_synced가 있으면 결과에 포함
    if account_ids and db_synced > 0:
        results.insert(
            0,
            {
                "account": "DB 주문 기반",
                "status": "success",
                "fetched": len(claim_orders),
                "synced": db_synced,
            },
        )

    return {"total_synced": total_synced, "results": results}


# ══════════════════════════════════════════════
# 11번가 교환 처리 (승인 / 거부)
# ══════════════════════════════════════════════


@router.post("/{return_id}/exchange-action")
async def elevenst_exchange_action(
    return_id: str,
    body: ExchangeActionBodyDTO,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """11번가 교환 승인(재배송) 또는 거부 처리.

    - action="approve" → GET /rest/claimservice/exchangereqconf/{clmReqSeq}/{ordNo}/{ordPrdSeq}
    - action="reject"  → GET /rest/claimservice/exchangereqrej/{clmReqSeq}/{ordNo}/{ordPrdSeq}

    clm_req_seq, ord_no, ord_prd_seq는 samba_return 레코드에 저장된 값을 우선 사용.
    요청 바디에서 override 가능.
    """
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.order.repository import SambaOrderRepository
    from backend.domain.samba.proxy.elevenst_exchange import (
        ElevenstApiError,
        ElevenstExchangeClient,
    )

    svc = _write_service(session)
    ret = await svc.repo.get_async(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="교환 기록을 찾을 수 없습니다")
    if ret.type != "exchange":
        raise HTTPException(status_code=400, detail="교환 유형이 아닙니다")

    # 클레임 식별자: 요청 바디 우선, 없으면 DB 저장값 사용
    clm_req_seq = body.clm_req_seq or ret.clm_req_seq or ""
    ord_prd_seq = body.ord_prd_seq or ret.ord_prd_seq or ""
    ord_no = body.ord_no or ret.order_number or ""

    if not clm_req_seq or not ord_no or not ord_prd_seq:
        raise HTTPException(
            status_code=400,
            detail="교환 처리에 필요한 클레임 식별자(clm_req_seq, ord_no, ord_prd_seq)가 없습니다",
        )

    # 주문 → 마켓 계정 조회
    order_repo = SambaOrderRepository(session)
    order = await order_repo.get_async(ret.order_id)
    if not order or not order.channel_id:
        raise HTTPException(status_code=400, detail="주문/마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account or account.market_type != "11st":
        raise HTTPException(status_code=400, detail="11번가 계정이 아닙니다")

    api_key = account.api_key or ""
    if not api_key:
        raise HTTPException(status_code=400, detail="11번가 API 키가 없습니다")

    client = ElevenstExchangeClient(api_key)

    action_labels = {"approve": "교환승인(재배송)", "reject": "교환거부"}
    label = action_labels.get(body.action, body.action)

    try:
        if body.action == "approve":
            await client.confirm_exchange(clm_req_seq, ord_no, ord_prd_seq)
            new_status = "approved"
            new_market_status = "교환승인"
        elif body.action == "reject":
            await client.reject_exchange(
                clm_req_seq, ord_no, ord_prd_seq, body.reason or "판매자 교환 거부"
            )
            new_status = "rejected"
            new_market_status = "교환거부"
        else:
            raise HTTPException(
                status_code=400, detail=f"알 수 없는 액션: {body.action}"
            )
    except HTTPException:
        raise
    except ElevenstApiError as e:
        raise HTTPException(status_code=502, detail=f"{label} API 오류: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{label} 실패: {e}")

    # DB 상태 업데이트
    from datetime import UTC, datetime

    timeline = list(ret.timeline or [])
    timeline.append(
        {
            "date": datetime.now(UTC).isoformat(),
            "status": new_status,
            "message": f"{label} 처리 완료",
        }
    )
    update_fields: dict[str, Any] = {
        "status": new_status,
        "market_order_status": new_market_status,
        "timeline": timeline,
    }
    if new_status == "approved":
        update_fields["approval_date"] = datetime.now(UTC)
    elif new_status == "rejected":
        update_fields["completion_date"] = datetime.now(UTC)

    await svc.repo.update_async(return_id, **update_fields)

    # 연결 주문 상태도 업데이트
    from backend.domain.samba.order.service import SambaOrderService

    order_svc = SambaOrderService(order_repo)
    order_status_map = {"approved": "교환승인", "rejected": "교환거부"}
    await order_svc.update_order(
        ret.order_id, {"shipping_status": order_status_map[new_status]}
    )

    logger.info(
        f"[11번가 교환처리] return_id={return_id} clmReqSeq={clm_req_seq} {label} 완료"
    )
    return {"ok": True, "message": f"{label} 완료"}


@router.patch("/{return_id}/exchange-tracking")
async def patch_exchange_tracking(
    return_id: str,
    body: ExchangeTrackingPatchBodyDTO,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """교환 추적 정보 수기 업데이트.

    11번가 API가 제공하지 않는 정보(회수 상태, 소싱처 출고 정보, 도착일)를 수기로 입력.
    """
    svc = _write_service(session)
    ret = await svc.repo.get_async(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="교환 기록을 찾을 수 없습니다")

    from datetime import datetime, timezone

    update_fields: dict[str, Any] = {}

    if body.exchange_retrieval_status is not None:
        update_fields["exchange_retrieval_status"] = body.exchange_retrieval_status

    if body.exchange_retrieved_at is not None:
        update_fields["exchange_retrieved_at"] = (
            datetime.fromisoformat(body.exchange_retrieved_at).replace(
                tzinfo=timezone.utc
            )
            if body.exchange_retrieved_at
            else None
        )

    if body.exchange_reship_company is not None:
        update_fields["exchange_reship_company"] = body.exchange_reship_company

    if body.exchange_reship_tracking is not None:
        update_fields["exchange_reship_tracking"] = body.exchange_reship_tracking

    if body.exchange_delivered_at is not None:
        update_fields["exchange_delivered_at"] = (
            datetime.fromisoformat(body.exchange_delivered_at).replace(
                tzinfo=timezone.utc
            )
            if body.exchange_delivered_at
            else None
        )

    if not update_fields:
        return ret

    return await svc.repo.update_async(return_id, **update_fields)
