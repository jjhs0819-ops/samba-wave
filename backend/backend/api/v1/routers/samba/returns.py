"""SambaWave Returns API router."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.dtos.samba.returns import ReturnCreate, ReturnNoteBody, ReturnRejectBody

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
    limit: int = Query(50, ge=1, le=1000),
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
            SambaOrder.id, SambaOrder.ext_order_number,
            SambaOrder.source_site, SambaOrder.sourcing_order_number,
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
        data = r.model_dump() if hasattr(r, 'model_dump') else r.__dict__.copy()
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
    type: Optional[str] = None
    market_order_status: Optional[str] = None


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
        update_fields["check_date"] = datetime.fromisoformat(body.check_date).replace(tzinfo=timezone.utc) if body.check_date else None
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
    if body.type is not None:
        update_fields["type"] = body.type
    if body.market_order_status is not None:
        update_fields["market_order_status"] = body.market_order_status
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
        city_name = first.replace("광역시", "").replace("특별자치시", "").replace("특별시", "")
        return f"{city_name}시"
    # 도 다음의 시/군 반환
    for p in parts[1:]:
        if p.endswith(("시", "군")):
            return p
    return parts[0] if parts else None


def _parse_lotteon_return(
  item: dict[str, Any],
  return_type: str,  # "return" | "cancel"
) -> dict[str, Any]:
  """롯데ON 반품/취소 데이터 → SambaReturn dict 변환.

  item: getCancellationRequestAndComplateList API의 itemList 단일 항목
        (odNo, clmNo가 상위 claim에서 주입된 상태)
  """
  step_cd = str(item.get("odPrgsStepCd", "") or "")
  # return_type은 호출 API(get_returns=return, get_exchanges=exchange)에서 결정
  # step_cd로 재분류하지 않음 — clmTpCd=RETN이면 반품, 교환 API면 교환

  if step_cd == "21":
    status = "done"
  elif step_cd == "22":
    status = "rejected"
  else:
    status = "requested"

  qty_raw = item.get("cnclQty") or item.get("odQty") or 1
  try:
    qty = int(qty_raw)
  except (ValueError, TypeError):
    qty = 1

  return {
    "source": "lotteon",
    "order_number": item.get("odNo", ""),
    "shipment_id": item.get("clmNo", ""),
    "ord_dtl_sn": str(item.get("odSeq", "") or item.get("procSeq", "")),
    "return_type": return_type,
    "reason_code": item.get("clmRsnCd", ""),
    "reason": item.get("clmRsnNm", "") or item.get("clmRsnCd", ""),
    "quantity": qty,
    "product_name": item.get("spdNm", "") or item.get("sitmNm", ""),
    "product_id": item.get("spdNo", "") or item.get("sitmNo", ""),
    "status": status,
  }


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

    for account in active_accounts:
        market_type = account.market_type
        extras = account.additional_fields or {}
        seller_id = account.seller_id or ""
        label = f"{account.market_name}({seller_id})"

        try:
            if market_type == "smartstore":
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                client_id = extras.get("clientId", "") or account.api_key or ""
                client_secret = extras.get("clientSecret", "") or account.api_secret or ""
                if not client_id or not client_secret:
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

                # 클레임이 있는 주문만 필터
                claims_data: list[dict[str, Any]] = []
                for ro in raw_orders:
                    po = ro.get("productOrder", ro)
                    order_info = ro.get("order", {})
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
                    sale_price = po.get("totalPaymentAmount", 0) or po.get("unitPrice", 0) or 0
                    quantity = po.get("quantity", 1) or 1

                    # 클레임 사유
                    claim_reason = po.get("claimReason", "") or po.get("returnReason", "") or ""

                    claims_data.append({
                        "product_order_id": product_order_id,
                        "type": return_type,
                        "status": _CLAIM_STATUS_MAP[claim_status],
                        "claim_status_raw": claim_status,
                        "display_status": _CLAIM_STATUS_DISPLAY.get(claim_status, claim_status),
                        "reason": claim_reason,
                        "quantity": quantity,
                        "requested_amount": float(sale_price),
                        "product_name": po.get("productName", ""),
                        "product_image": po.get("imageUrl", ""),
                        "product_option": po.get("productOption", "") or "",
                    })

                # 기존 주문 매칭 및 반품 레코드 생성/업데이트
                synced = 0
                for claim in claims_data:
                    product_order_id = claim["product_order_id"]
                    # 주문 테이블에서 order_number로 매칭
                    existing_order = await order_repo.find_by_async(order_number=product_order_id)
                    if not existing_order:
                        # 주문이 아직 동기화 안 된 경우 — 건너뜀
                        continue

                    order_id = existing_order.id
                    # 이미 동일한 반품 기록이 있는지 확인 (order_id 기준)
                    existing_returns = await svc.repo.filter_by_async(
                        order_id=order_id
                    )

                    if existing_returns:
                        # 같은 타입 우선, 없으면 첫 번째 레코드 사용
                        existing_ret = next(
                            (r for r in existing_returns if r.type == claim["type"]),
                            existing_returns[0]
                        )
                        # 타입이 변경된 경우 (교환→반품 등) 업데이트
                        if existing_ret.type != claim["type"]:
                            await svc.repo.update_async(existing_ret.id, type=claim["type"])
                        new_status = claim["status"]
                        # 상태 진행도: requested → approved → completed/rejected
                        status_priority = {"requested": 0, "approved": 1, "completed": 2, "rejected": 2, "cancelled": 2}
                        if status_priority.get(new_status, 0) > status_priority.get(existing_ret.status, 0):
                            from datetime import UTC, datetime
                            timeline = list(existing_ret.timeline or [])
                            timeline.append({
                                "date": datetime.now(UTC).isoformat(),
                                "status": new_status,
                                "message": _CLAIM_STATUS_LABEL.get(claim["claim_status_raw"], f"상태: {new_status}"),
                            })
                            update_data: dict[str, Any] = {"status": new_status, "timeline": timeline, "market_order_status": claim["display_status"]}
                            if new_status == "approved":
                                update_data["approval_date"] = datetime.now(UTC)
                            elif new_status == "completed":
                                update_data["completion_date"] = datetime.now(UTC)
                            await svc.repo.update_async(existing_ret.id, **update_data)
                        # 이미지/전화번호/주소 보충
                        patch_fields: dict[str, Any] = {}
                        if claim["product_image"] and not existing_ret.product_image:
                            patch_fields["product_image"] = claim["product_image"]
                        if existing_order.customer_phone and not existing_ret.customer_phone:
                            patch_fields["customer_phone"] = existing_order.customer_phone
                        if existing_order.customer_address:
                            new_loc = _extract_city_district(existing_order.customer_address)
                            if new_loc and new_loc != existing_ret.product_location:
                                patch_fields["product_location"] = new_loc
                            if not existing_ret.customer_address:
                                patch_fields["customer_address"] = existing_order.customer_address
                        if patch_fields:
                            await svc.repo.update_async(existing_ret.id, **patch_fields)
                        continue

                    # 신규 반품 생성
                    from datetime import UTC, datetime
                    claim_status_raw = claim["claim_status_raw"]
                    timeline_entries = [{
                        "date": datetime.now(UTC).isoformat(),
                        "status": claim["status"],
                        "message": _CLAIM_STATUS_LABEL.get(claim_status_raw, f"{claim['type']} 요청이 접수되었습니다."),
                    }]

                    # 마켓 타입 → 한글 마켓명
                    market_label_map: dict[str, str] = {
                        "smartstore": "스마트스토어",
                        "coupang": "쿠팡",
                        "11st": "11번가",
                        "lotteon": "롯데ON",
                        "ssg": "SSG",
                        "gsshop": "GS샵",
                    }

                    return_data: dict[str, Any] = {
                        "order_id": order_id,
                        "order_number": product_order_id,
                        "type": claim["type"],
                        "reason": claim["reason"] or None,
                        "description": f"{claim['product_name']} {claim['product_option']}".strip() or None,
                        "quantity": claim["quantity"],
                        "requested_amount": claim["requested_amount"],
                        "product_image": claim["product_image"] or existing_order.product_image,
                        "product_name": claim["product_name"] or existing_order.product_name,
                        "customer_name": existing_order.customer_name,
                        "customer_phone": existing_order.customer_phone,
                        "product_location": _extract_city_district(existing_order.customer_address),
                        "customer_address": existing_order.customer_address,
                        "business_name": account.business_name or account.market_name or label,
                        "market": market_label_map.get(market_type, market_type),
                        "market_order_status": claim["display_status"],
                        "return_link": existing_order.source_url or "",
                        "return_source": existing_order.source_site or "",
                        "region": _extract_city_district(existing_order.customer_address),
                        "return_request_date": datetime.now(UTC),
                        "order_date": existing_order.created_at,
                        "status": claim["status"],
                        "timeline": timeline_entries,
                        "notes": [],
                    }
                    # 이미 진행된 상태이면 날짜도 설정
                    if claim["status"] in ("approved", "completed"):
                        return_data["approval_date"] = datetime.now(UTC)
                    if claim["status"] == "completed":
                        return_data["completion_date"] = datetime.now(UTC)

                    await svc.repo.create_async(**return_data)
                    synced += 1

                total_synced += synced
                results.append({
                    "account": label,
                    "status": "success",
                    "fetched": len(claims_data),
                    "synced": synced,
                })
                logger.info(f"[반품동기화] {label}: 클레임 {len(claims_data)}건 조회, {synced}건 신규 저장")

            elif market_type == "lotteon":
                from backend.domain.samba.proxy.lotteon import LotteonApiError, LotteonClient

                api_key = account.api_key or extras.get("apiKey", "")
                if not api_key:
                    results.append({"account": label, "status": "skip", "message": "API 키 없음"})
                    continue

                client = LotteonClient(api_key=api_key)
                await client.test_auth()

                raw_cancels = await client.get_cancel_orders(days=body.days)
                raw_returns = await client.get_returns(days=body.days)

                # 반품 건만 반품교환 화면에 저장 (취소 건은 주문 내역에서 처리)
                claims_data_lo: list[dict[str, Any]] = []
                for item in raw_returns:
                    parsed = _parse_lotteon_return(item, "return")
                    parsed["sitmNo"] = item.get("sitmNo", "")
                    claims_data_lo.append(parsed)
                _lo_od_nos = [c['order_number'] for c in claims_data_lo]
                logger.warning(f"[롯데ON] 반품 API 조회된 odNo 목록({len(_lo_od_nos)}건): {_lo_od_nos}")

                synced = 0
                for claim in claims_data_lo:
                    order_number = claim["order_number"]
                    if not order_number:
                        continue
                    existing_order = await order_repo.find_by_async(order_number=order_number)
                    if not existing_order:
                        # sitmNo(상품주문번호)는 DB의 shipment_id 필드에 저장됨
                        sitmNo = claim.get("sitmNo", "")
                        if sitmNo:
                            existing_order = await order_repo.find_by_async(shipment_id=sitmNo)
                    if not existing_order:
                        logger.warning(f"[롯데ON] 반품 주문 미매칭: {order_number} sitmNo={claim.get('sitmNo','')}")
                        continue

                    order_id = existing_order.id
                    logger.warning(f"[롯데ON] 반품 주문 매칭 성공: {order_number} → DB order_id={order_id}")
                    existing_returns = await svc.repo.filter_by_async(order_id=order_id)
                    if existing_returns:
                        # 기존 레코드에 누락/오류 필드 보충
                        er = existing_returns[0]
                        patch_lo: dict[str, Any] = {}
                        correct_type = claim["return_type"]  # API에서 확정된 type (return/exchange)
                        if not er.product_image and existing_order.product_image:
                            patch_lo["product_image"] = existing_order.product_image
                        # market_order_status가 type과 불일치하면 강제 수정
                        if correct_type == "exchange" and er.market_order_status and "반품" in er.market_order_status:
                            patch_lo["market_order_status"] = "교환요청"
                        elif correct_type == "return" and er.market_order_status and "교환" in er.market_order_status:
                            patch_lo["market_order_status"] = "반품요청"
                        elif not er.market_order_status:
                            patch_lo["market_order_status"] = "교환요청" if correct_type == "exchange" else "반품요청"
                        # type이 없거나 잘못 저장된 경우 수정
                        if er.type != correct_type:
                            patch_lo["type"] = correct_type
                        if patch_lo:
                            await svc.repo.update_async(er.id, **patch_lo)
                            logger.warning(f"[롯데ON] 반품 레코드 패치: {order_number} type={correct_type} patch={list(patch_lo.keys())} er.type={er.type} er.market_order_status={er.market_order_status}")
                        else:
                            logger.warning(f"[롯데ON] 반품 레코드 패치 불필요: {order_number} er.type={er.type} er.market_order_status={er.market_order_status}")
                        # 원주문 shipping_status 동기화 (교환/반품 진행 중이면 주문 페이지에서 제외)
                        new_order_ss = "교환요청" if correct_type == "exchange" else "반품요청"
                        if existing_order.shipping_status != new_order_ss:
                            await order_repo.update_async(existing_order.id, shipping_status=new_order_ss)
                        continue

                    from datetime import UTC, datetime
                    return_data: dict[str, Any] = {
                        "order_id": order_id,
                        "order_number": order_number,
                        "type": claim["return_type"],
                        "reason": claim["reason"] or None,
                        "quantity": claim["quantity"],
                        "product_name": claim["product_name"] or (existing_order.product_name if existing_order else None),
                        "product_image": existing_order.product_image if existing_order else None,
                        "customer_name": existing_order.customer_name if existing_order else None,
                        "customer_phone": existing_order.customer_phone if existing_order else None,
                        "product_location": _extract_city_district(existing_order.customer_address if existing_order else None),
                        "customer_address": existing_order.customer_address if existing_order else None,
                        "business_name": account.business_name or account.market_name or label,
                        "market": "롯데ON",
                        "market_order_status": "교환요청" if claim["return_type"] == "exchange" else "반품요청",
                        "status": claim["status"],
                        "timeline": [{
                            "date": datetime.now(UTC).isoformat(),
                            "status": claim["status"],
                            "message": f"{claim['return_type']} 요청 접수",
                        }],
                        "notes": [],
                    }
                    await svc.repo.create_async(**return_data)
                    # 원주문 shipping_status 동기화
                    new_order_ss = "교환요청" if claim["return_type"] == "exchange" else "반품요청"
                    await order_repo.update_async(existing_order.id, shipping_status=new_order_ss)
                    synced += 1

                # 교환 클레임 동기화
                try:
                    raw_exchanges = await client.get_exchanges(days=body.days)
                    for item in raw_exchanges:
                        ex_order_number = item.get("odNo", "")
                        if not ex_order_number:
                            continue
                        existing_order = await order_repo.find_by_async(order_number=ex_order_number)
                        if not existing_order:
                            # sitmNo(상품주문번호)는 DB의 shipment_id 필드에 저장됨
                            ex_sitmNo = item.get("sitmNo", "")
                            if ex_sitmNo:
                                existing_order = await order_repo.find_by_async(shipment_id=ex_sitmNo)
                        if not existing_order:
                            logger.warning(f"[롯데ON] 교환 주문 미매칭: {ex_order_number} sitmNo={item.get('sitmNo','')}")
                            continue
                        order_id = existing_order.id
                        existing_returns = await svc.repo.filter_by_async(order_id=order_id)
                        if existing_returns:
                            # 기존 레코드 image 보충 (type은 변경 금지 — 교환취소 후 반품 재신청 케이스 보호)
                            er = existing_returns[0]
                            patch: dict[str, Any] = {}
                            if not er.product_image and existing_order.product_image:
                                patch["product_image"] = existing_order.product_image
                            if not er.market_order_status:
                                patch["market_order_status"] = "교환요청" if er.type == "exchange" else "반품요청"
                            if patch:
                                await svc.repo.update_async(er.id, **patch)
                            # shipping_status는 현재 저장된 type 기준으로 동기화 (덮어쓰기 금지)
                            expected_ss = "교환요청" if er.type == "exchange" else "반품요청"
                            if existing_order.shipping_status != expected_ss:
                                await order_repo.update_async(existing_order.id, shipping_status=expected_ss)
                            continue
                        from datetime import UTC, datetime
                        await svc.repo.create_async(
                            order_id=order_id,
                            order_number=ex_order_number,
                            type="exchange",
                            reason=item.get("clmRsnCd", "") or None,
                            quantity=int(item.get("xchgQty") or item.get("odQty") or 1),
                            product_name=item.get("spdNm", "") or existing_order.product_name,
                            product_image=existing_order.product_image,
                            customer_name=existing_order.customer_name,
                            customer_phone=existing_order.customer_phone,
                            product_location=_extract_city_district(existing_order.customer_address),
                            customer_address=existing_order.customer_address,
                            business_name=account.business_name or account.market_name or label,
                            market="롯데ON",
                            market_order_status="교환요청",
                            status="requested",
                            timeline=[{
                                "date": datetime.now(UTC).isoformat(),
                                "status": "requested",
                                "message": "교환 요청 접수",
                            }],
                            notes=[],
                        )
                        # 원주문 shipping_status 동기화
                        await order_repo.update_async(existing_order.id, shipping_status="교환요청")
                        synced += 1
                        logger.info(f"[반품동기화][롯데ON] 교환 클레임 저장: {ex_order_number}")
                except Exception as ex_err:
                    logger.warning(f"[반품동기화][롯데ON] 교환 클레임 동기화 실패: {ex_err}")

                total_synced += synced
                results.append({
                    "account": label,
                    "status": "success",
                    "fetched": len(claims_data_lo),
                    "synced": synced,
                })
                logger.info(f"[반품동기화][롯데ON] {label}: 반품 {len(raw_returns)}건, 취소 {len(raw_cancels)}건 조회, {synced}건 신규 저장")

            else:
                results.append({"account": label, "status": "skip", "message": f"{market_type} 반품 조회 미지원"})
                continue

        except Exception as e:
            logger.error(f"[반품동기화] {label} 실패: {e}")
            results.append({"account": label, "status": "error", "message": str(e)})

    # DB 기반 원주문 shipping_status 일괄 동기화
    # samba_return 레코드가 있고 아직 진행 중인 주문의 shipping_status를 강제 업데이트
    try:
        from sqlalchemy import text as _sa_text
        await session.execute(_sa_text("""
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
        """))
        logger.info("[반품동기화] 원주문 shipping_status 일괄 업데이트 완료")
    except Exception as _upd_err:
        logger.warning(f"[반품동기화] 원주문 일괄 업데이트 실패: {_upd_err}")

    # 롯데ON API 버그 수정: clmRsnCd=300번대(반품 사유)가 교환으로 잘못 저장된 레코드 일괄 수정
    try:
        from sqlalchemy import text as _sa_text
        # 진단: 실제 저장된 값 확인
        _diag = await session.execute(_sa_text("""
            SELECT r.id, r.type, r.market, r.reason, r.market_order_status, o.order_number
            FROM samba_return r
            LEFT JOIN samba_order o ON o.id = r.order_id
            WHERE r.type = 'exchange'
              AND r.market ILIKE '%롯데%'
            LIMIT 20
        """))
        _diag_rows = _diag.fetchall()
        if _diag_rows:
            logger.warning(
                f"[반품동기화][진단] 롯데ON 교환 레코드 샘플: "
                + str([(str(r[0])[:8], r[1], repr(r[2]), repr(r[3]), r[4], r[5]) for r in _diag_rows])
            )
        else:
            logger.warning("[반품동기화][진단] 롯데ON 교환 레코드 없음 (type=exchange AND market ILIKE '%롯데%')")

        # 1단계: 연결된 원주문 shipping_status를 교환 상태에서 반품요청으로 수정
        # reason이 NULL이거나 2xx/3xx(반품 사유코드)인 경우 처리
        await session.execute(_sa_text("""
            UPDATE samba_order o
            SET shipping_status = '반품요청'
            FROM samba_return r
            WHERE r.order_id = o.id
              AND r.type = 'exchange'
              AND r.market ILIKE '%롯데%'
              AND (r.reason ~ '^[23][0-9]+' OR r.reason IS NULL)
              AND o.shipping_status IN (
                  '교환요청', '교환회수완료', '교환재배송', '교환완료'
              )
        """))
        # 2단계: samba_return 타입 교환→반품 수정
        result_repair = await session.execute(_sa_text("""
            UPDATE samba_return
            SET type = 'return',
                market_order_status = '반품요청'
            WHERE type = 'exchange'
              AND market ILIKE '%롯데%'
              AND (reason ~ '^[23][0-9]+' OR reason IS NULL)
            RETURNING id, order_id, reason
        """))
        repaired_rows = result_repair.fetchall()
        repaired = len(repaired_rows)
        if repaired > 0:
            logger.warning(
                f"[반품동기화] 롯데ON 교환→반품 재분류 수정: {repaired}건 "
                f"IDs={[str(r[0])[:8] for r in repaired_rows]}"
            )
        else:
            logger.warning("[반품동기화] 롯데ON 교환→반품 재분류 수정 대상 없음")
    except Exception as _repair_err:
        logger.warning(f"[반품동기화] 롯데ON 반품 재분류 수정 실패: {_repair_err}")

    return {"total_synced": total_synced, "results": results}
