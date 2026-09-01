"""SambaWave Returns API router."""

import asyncio
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tenant.middleware import get_optional_tenant_id
from backend.dtos.samba.returns import (
    ExchangeActionBody as ExchangeActionBodyDTO,
    ExchangeTrackingPatchBody as ExchangeTrackingPatchBodyDTO,
    ReturnCreate,
    ReturnNoteBody,
    ReturnRejectBody,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/returns", tags=["samba-returns"])

# claim 주문 → 반품 자동백필 throttle — 매 호출마다 5,000건 스캔하던 부하 제거.
# 목록 조회는 read 세션으로 가볍게 끝내고, 백필은 5분에 한 번만 별도 write 세션에서 수행.
_CLAIM_BACKFILL_INTERVAL = 300.0  # 초
_last_claim_backfill_ts = 0.0
# 백필 동시실행 직렬화 락 — 강제 백필(force_backfill)은 스로틀 타임스탬프 선점만으로는
# 동시요청을 못 막으므로(강제 경로는 타임스탬프를 안 보고 실행), 같은 워커에서 새 탭이
# 연달아 열려도 백필이 겹쳐 돌며 중복 행을 INSERT 하지 않도록 한 번에 하나만 실행한다.
# 뒤에 온 요청은 앞 실행이 끝난 뒤 도는데, 백필 내부의 기존행 가드가 중복 생성을 막는다.
_claim_backfill_lock = asyncio.Lock()


def _read_service(session: AsyncSession):
    from backend.domain.samba.returns.repository import SambaReturnRepository
    from backend.domain.samba.returns.service import SambaReturnService

    return SambaReturnService(SambaReturnRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.returns.repository import SambaReturnRepository
    from backend.domain.samba.returns.service import SambaReturnService

    return SambaReturnService(SambaReturnRepository(session))


def _claim_kind_from_order(
    status: str | None, shipping_status: str | None
) -> str | None:
    status_text = (status or "").lower()
    ship_text = shipping_status or ""
    # shipping_status(\ub9c8\ucf13 \uc2e4\uc81c \ud074\ub808\uc784 \uc0c1\ud0dc)\ub97c status(\ub0b4\ubd80 \ud544\ub4dc, stale \uac00\ub2a5)\ubcf4\ub2e4 \uc6b0\uc120\ud55c\ub2e4.
    # status=cancelled \ub85c \uad73\uc740 SSG \ubc18\ud488(\ubc18\ud488\uc778\ub370 cnclQty>0 \u2192 \ucde8\uc18c \uc624\ubd84\ub958 + \uc0c1\ud0dc\uc804\ud658 \uac00\ub4dc\uac00
    # cancelled \ub97c \ubc18\ud488\uc694\uccad\uc73c\ub85c \ub418\ub3cc\ub9ac\uc9c0 \ubabb\ud568)\uc774 shipping=\ubc18\ud488\uc694\uccad\uc774\uba74 return \uc73c\ub85c \uc7a1\ud788\ub3c4\ub85d.
    # \uacfc\uac70\uc5d4 cancel \uc744 \uba3c\uc800 \uac80\uc0ac\ud574 \ubc18\ud488/\uad50\ud658\uc774 \ucde8\uc18c\ub85c \ubd84\ub958\ub418\ub358 \ubc84\uadf8.
    if "\ucde8\uc18c" in ship_text:  # \ucde8\uc18c
        return "cancel"
    if "\uad50\ud658" in ship_text:  # \uad50\ud658
        return "exchange"
    if "\ubc18\ud488" in ship_text:  # \ubc18\ud488
        return "return"
    if status_text in {"cancel_requested", "cancelling", "cancelled"}:
        return "cancel"
    if status_text in {"exchange_requested", "exchanging", "exchanged"}:
        return "exchange"
    if status_text in {"return_requested", "returning", "returned"}:
        return "return"
    return None


def _claim_status_from_order(status: str | None, shipping_status: str | None) -> str:
    status_text = (status or "").lower()
    ship_text = shipping_status or ""
    # shipping_status(\ub9c8\ucf13 \uc2e4\uc81c \uc0c1\ud0dc) \uc6b0\uc120 \u2014 status(\ub0b4\ubd80 \ud544\ub4dc) \uac00 stale(cancelled)\uc5ec\ub3c4
    # shipping \uc774 '\ubc18\ud488\uc694\uccad/\uad50\ud658\uc694\uccad/\ucde8\uc18c\uc694\uccad'(\uc9c4\ud589\uc911)\uc774\uba74 completed \ub85c \uc624\ud310\ud558\uc9c0 \uc54a\ub294\ub2e4.
    if "\uac70\ubd80" in ship_text:  # \uac70\ubd80
        return "rejected"
    if (
        "\uc644\ub8cc" in ship_text or "\ub9c8\uac10" in ship_text
    ):  # \ubc18\ud488\uc644\ub8cc/\ucde8\uc18c\uc644\ub8cc/\uad6c\ub9e4\ud655\uc815 \ub4f1
        return "completed"
    if (
        "\uc694\uccad" in ship_text
    ):  # \ubc18\ud488\uc694\uccad/\uad50\ud658\uc694\uccad/\ucde8\uc18c\uc694\uccad \u2192 \uc9c4\ud589\uc911
        return "requested"
    if status_text in {"cancelled", "returned", "exchanged"}:
        return "completed"
    if status_text in {"cancelling", "returning", "exchanging"}:
        return "approved"
    return "requested"


def _is_cancel_requested(status: str | None, shipping_status: str | None) -> bool:
    # 취소 '요청' 단계만 판별하는 헬퍼 (요청 #5: 반품탭 메모 자동기입 '취소요청').
    # _claim_kind_from_order 의 'cancel' 은 취소진행중(cancelling)·취소완료(cancelled)까지
    # 포함하므로 그대로 쓰면 이미 취소가 끝난 건에도 '취소요청'이 적혀 혼란을 준다.
    # → 주문탭 드롭다운 '취소요청' 저장값(status='cancel_requested',
    #   shipping_status='취소요청' — order.py 상태 매핑)에만 반응하도록 좁힌다.
    status_text = (status or "").lower()
    ship_text = shipping_status or ""
    return status_text == "cancel_requested" or "취소요청" in ship_text


def _completion_detail(claim_type: str, claim_status: str) -> str:
    if claim_status == "rejected":
        return "\uac70\ubd80"
    if claim_status != "completed":
        return "\uc9c4\ud589\uc911"
    return {
        "cancel": "\ucde8\uc18c",
        "return": "\ubc18\ud488",
        "exchange": "\uad50\ud658",
    }.get(claim_type, "\uc9c4\ud589\uc911")


async def _backfill_returns_from_claim_orders(
    session: AsyncSession,
    tenant_id: Optional[str] = None,
    order_ids: Optional[list[str]] = None,
) -> int:
    # order_ids 가 주어지면 해당 주문들로만 스캔을 좁힌다 (주문 상태변경 단건 동기화용
    # — order.py _sync_returns_with_order_status. 일괄변경이 건마다 5,000건 전체
    # 스캔을 돌지 않게 함). None(기본)이면 기존과 100% 동일한 전체 백필.
    from datetime import UTC, datetime as _dt

    from sqlalchemy import or_
    from sqlmodel import col, select

    from backend.domain.samba.order.model import SambaOrder
    from backend.domain.samba.returns.model import SambaReturn
    from backend.domain.samba.returns.repository import SambaReturnRepository
    from backend.domain.samba.returns.service import SambaReturnService

    claim_statuses = {
        "cancel_requested",
        "cancelling",
        "cancelled",
        "return_requested",
        "returning",
        "returned",
        "exchange_requested",
        "exchanging",
        "exchanged",
    }
    claim_words = [
        "\ucde8\uc18c",
        "\ubc18\ud488",
        "\uad50\ud658",
    ]

    stmt = select(SambaOrder).where(
        or_(
            col(SambaOrder.status).in_(claim_statuses),
            *[SambaOrder.shipping_status.ilike(f"%{word}%") for word in claim_words],
        )
    )
    if order_ids is not None:
        # 대상 주문 좁히기 (AND) — claim 판정·tenant 조건·기존행 스킵은 그대로 통과시킨다
        stmt = stmt.where(col(SambaOrder.id).in_(order_ids))
    if tenant_id is not None:
        stmt = stmt.where(
            or_(
                SambaOrder.tenant_id == tenant_id,
                SambaOrder.tenant_id == None,  # noqa: E711
            )
        )
    orders = list((await session.execute(stmt.limit(5000))).scalars().all())
    if not orders:
        return 0

    # 파라미터 order_ids(대상 좁히기)와 섀도잉되지 않게 로컬은 found_ 접두
    found_order_ids = [o.id for o in orders]
    order_numbers = [o.order_number for o in orders if o.order_number]
    existing_stmt = select(SambaReturn.order_id, SambaReturn.order_number).where(
        or_(
            col(SambaReturn.order_id).in_(found_order_ids),
            col(SambaReturn.order_number).in_(order_numbers),
        )
    )
    existing_rows = (await session.execute(existing_stmt)).all()
    existing_order_ids = {row[0] for row in existing_rows if row[0]}
    existing_order_numbers = {row[1] for row in existing_rows if row[1]}

    svc = SambaReturnService(SambaReturnRepository(session))
    created = 0
    now = _dt.now(UTC)
    for order in orders:
        if (
            order.id in existing_order_ids
            or order.order_number in existing_order_numbers
        ):
            continue
        claim_type = _claim_kind_from_order(order.status, order.shipping_status)
        if not claim_type:
            continue
        claim_status = _claim_status_from_order(order.status, order.shipping_status)
        timeline = [
            {
                "date": now.isoformat(),
                "status": claim_status,
                "message": f"{order.shipping_status or order.status} 상태를 주문 수집 정보에서 반영했습니다.",
            }
        ]
        await svc.repo.create_async(
            tenant_id=order.tenant_id,
            order_id=order.id,
            order_number=order.order_number,
            product_image=order.product_image,
            product_name=order.product_name,
            customer_name=order.customer_name,
            customer_phone=order.customer_phone,
            customer_address=order.customer_address,
            business_name=order.channel_name,
            market=order.channel_name,
            order_date=order.paid_at or order.created_at,
            return_link=order.source_url or order.ext_order_number,
            return_source=order.source_site,
            product_location=_extract_city_district(order.customer_address),
            region=_extract_city_district(order.customer_address),
            return_request_date=order.updated_at or now,
            market_order_status=order.shipping_status,
            completion_detail=_completion_detail(claim_type, claim_status),
            type=claim_type,
            description=order.product_name,
            quantity=order.quantity or 1,
            requested_amount=order.sale_price,
            status=claim_status,
            completion_date=now if claim_status in {"completed", "rejected"} else None,
            notes=[],
            timeline=timeline,
            # 취소요청 건은 반품탭 메모에 '취소요청' 자동 기입 (요청 #5, 사장님 결정:
            # 취소요청만 — 취소진행중/취소완료·교환·반품 생성 행에는 기입 안 함).
            # 신규 INSERT 경로에만 적용 — 기존 행은 위 existing_* 가드로 건너뛰므로
            # 사장님이 손으로 쓴 메모를 덮어쓸 일 없음. memo 컬럼은 nullable(기본 None).
            memo="취소요청"
            if _is_cancel_requested(order.status, order.shipping_status)
            else None,
        )
        created += 1

    if created:
        await session.commit()
        logger.info("[returns] backfilled %s claim rows from samba_order", created)
    return created


@router.get("/stats")
async def get_return_stats(
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    await _backfill_returns_from_claim_orders(session, tenant_id=tenant_id)
    svc = _read_service(session)
    return await svc.get_return_stats(tenant_id=tenant_id)


@router.get("/reasons")
async def get_return_reasons():
    from backend.domain.samba.returns.service import SambaReturnService

    return SambaReturnService.get_return_reasons()


@router.post("/auto-approve")
async def auto_approve_returns(
    within_days: int = 7,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """요청 상태인 반품 중 N일 이내 요청건 자동승인."""
    svc = _write_service(session)
    count = await svc.auto_approve_returns(within_days=within_days)
    await session.commit()
    return {"ok": True, "approved_count": count}


@router.get("")
async def list_returns(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    order_id: Optional[str] = None,
    order_number: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    force_backfill: bool = False,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    # claim 주문 자동백필 — 매 호출이 아니라 5분에 한 번만, 별도 write 세션에서 수행.
    # (목록 조회 자체는 가벼운 read 세션으로 처리해 오토튠 write 부하와 분리)
    #
    # 예외(요청 #10): force_backfill=True 이고 order_number 가 함께 온 경우에만 스로틀을
    # 우회해 즉시 백필한다. 주문탭 [반품/교환] → 새 탭 진입 직후, 방금 '취소요청'으로 바꾼
    # 주문이 아직 samba_return 에 없어 첫 로드 목록에서 빠지는 문제 해소용.
    # 백필은 최대 5,000건 주문을 스캔하므로 상시 강제는 운영 부하 위험 →
    # order_number 시드가 있는 저빈도 새 탭 진입 경로에만 허용하고,
    # order_number 없이 force_backfill=true 만 오면 무시하고 기존 스로틀 경로를 탄다.
    global _last_claim_backfill_ts
    now_ts = time.monotonic()
    force = bool(force_backfill and order_number)
    if force or now_ts - _last_claim_backfill_ts >= _CLAIM_BACKFILL_INTERVAL:
        # 강제 실행도 타이머를 갱신한다 — 방금 전체 백필이 돌았으므로 데이터 신선도는
        # 일반 스로틀 백필과 동일하고, 갱신하지 않으면 직후 일반 진입이 같은 5,000건
        # 스캔을 또 돌아 부하만 이중으로 든다. (일반 진입 백필이 '밀리는' 게 아니라
        # 강제 실행이 그 몫까지 이미 수행한 것)
        _last_claim_backfill_ts = now_ts  # 동시요청 중복 실행 방지: 실행 전 선점
        try:
            from backend.db.orm import get_write_session

            # 락으로 직렬화 — 강제 경로는 타임스탬프 선점을 안 보고 실행하므로,
            # 동시 강제 요청이 겹쳐 돌며 중복 행을 만들지 않게 한 번에 하나만 수행.
            async with _claim_backfill_lock:
                async with get_write_session() as wsession:
                    await _backfill_returns_from_claim_orders(
                        wsession, tenant_id=tenant_id
                    )
        except Exception as e:
            logger.warning(f"[returns] claim 자동백필 실패(무시): {e}")

    svc = _read_service(session)
    returns = await svc.list_returns(
        skip=skip,
        limit=limit,
        order_id=order_id,
        order_number=order_number,
        status=status,
        type=type,
        start_date=start_date,
        end_date=end_date,
        tenant_id=tenant_id,
    )

    # 주문의 ext_order_number(타마켓주문링크) 또는 소싱처 주문상세 URL을 return_link로 매칭
    # 주문탭 원주문링크와 100% 동일한 로직
    order_ids = list({r.order_id for r in returns if r.order_id})
    link_map: dict[str, str] = {}
    channel_id_map: dict[str, str] = {}  # order_id → channel_id
    order_date_map: dict[str, Any] = {}  # order_id → paid_at or created_at
    order_addr_map: dict[str, str] = {}  # order_id → customer_address
    if order_ids:
        from backend.domain.samba.order.model import SambaOrder
        from sqlmodel import select, col

        stmt = select(
            SambaOrder.id,
            SambaOrder.ext_order_number,
            SambaOrder.source_site,
            SambaOrder.sourcing_order_number,
            SambaOrder.channel_id,
            SambaOrder.paid_at,
            SambaOrder.created_at,
            SambaOrder.customer_address,
        ).where(col(SambaOrder.id).in_(order_ids))
        rows = (await session.execute(stmt)).all()
        # 소싱처별 주문상세 URL 템플릿 (주문탭 orderUrlMap과 동일)
        _order_detail_urls: dict[str, str] = {
            "MUSINSA": "https://www.musinsa.com/order/order-detail/{}",
            "KREAM": "https://kream.co.kr/my/purchasing/{}",
            "FashionPlus": "https://www.fashionplus.co.kr/mypage/order/detail/{}",
            "ABCmart": "https://abcmart.a-rt.com/mypage/order/read-order-detail?orderNo={}",
            "GrandStage": "https://grandstage.a-rt.com/mypage/order/read-order-detail?orderNo={}",
            "Nike": "https://www.nike.com/kr/orders/{}",
            "SSG": "https://pay.ssg.com/myssg/orderInfoDetail.ssg?orordNo={}&viewType=Ssg",
            "LOTTEON": "https://www.lotteon.com/p/order/claim/giftBoxDetail?odNo={}&type=snd",
            "GSShop": "https://www.gsshop.com/ord/dlvcursta/popup/ordDtl.gs?ordNo={}&ecOrdTypCd=S",
            # 더현대(현대Hi) — 송장조회와 동일 URL (tracking_sync/service.py 의 build_tracking_url 참조)
            "THEHYUNDAI": "https://hi.thehyundai.com/mypage/order/detail?ordNo={}",
        }
        for row in rows:
            # 1순위: 타마켓주문링크 (URL 형태만 — 순수 주문번호는 제외)
            if row.ext_order_number and row.ext_order_number.startswith("http"):
                link_map[row.id] = row.ext_order_number
            # 2순위: 소싱처 구매주문번호 + 소싱처별 URL
            elif row.source_site and row.sourcing_order_number:
                tpl = _order_detail_urls.get(row.source_site, "")
                if tpl:
                    link_map[row.id] = tpl.format(row.sourcing_order_number)
            # channel_id 수집
            if row.channel_id:
                channel_id_map[row.id] = row.channel_id
            # 주문일 수집 (paid_at 우선)
            order_date_map[row.id] = row.paid_at or row.created_at
            # 고객주소 수집 (region 동적 폴백용)
            if row.customer_address:
                order_addr_map[row.id] = row.customer_address

    # business_name 보정용 계정 조회
    account_map: dict[str, str] = {}  # channel_id → business_name
    channel_ids = list(set(channel_id_map.values()))
    if channel_ids:
        from backend.domain.samba.account.model import (
            SambaMarketAccount as AccountModel,
        )
        from sqlmodel import select, col

        acc_stmt = select(
            AccountModel.id,
            AccountModel.account_label,
            AccountModel.business_name,
            AccountModel.market_name,
        ).where(col(AccountModel.id).in_(channel_ids))
        acc_rows = (await session.execute(acc_stmt)).all()
        for acc in acc_rows:
            # 사업자칸 표시명: account_label('가디'/'소경' 등 별칭) 우선 → 없으면 사업자명/마켓명
            account_map[acc.id] = (
                acc.account_label or acc.business_name or acc.market_name or ""
            )

    results = []
    for r in returns:
        data = r.model_dump() if hasattr(r, "model_dump") else r.__dict__.copy()
        # 동적 생성 우선 → DB 값은 폴백
        data["return_link"] = link_map.get(r.order_id) or r.return_link or None
        # 사업자칸: 계정 별칭(account_label '가디'/'소경')으로 항상 우선 표기.
        # 생성 시 channel_name(ID성 값)이 박혀도 계정 매칭되면 별칭으로 덮어씀.
        cid = channel_id_map.get(r.order_id)
        acc_label = account_map.get(cid) if cid else None
        if acc_label:
            data["business_name"] = acc_label
        elif not data.get("business_name"):
            data["business_name"] = None
        # order_date가 없으면 주문의 paid_at으로 동적 보정
        if not data.get("order_date"):
            data["order_date"] = order_date_map.get(r.order_id)
        # region(지역)이 없으면 주문 고객주소에서 즉석 계산해 보정
        # — 생성 시 region을 안 박은 수집경로(스마트스토어/플레이오토 등) 대응
        if not data.get("region"):
            addr = order_addr_map.get(r.order_id) or data.get("customer_address")
            if addr:
                data["region"] = _extract_city_district(addr)
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
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    svc = _read_service(session)
    ret = await svc.get_return(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    # 테넌트 소유권 검증
    if tenant_id is not None and ret.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403, detail="해당 반품/교환에 대한 권한이 없습니다"
        )
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
    return_source: Optional[str] = None
    customer_amount: Optional[str] = None
    company_amount: Optional[str] = None
    return_link_manual: Optional[str] = None
    customer_phone_manual: Optional[str] = None
    sourcing_order_no: Optional[str] = None


@router.patch("/{return_id}")
async def patch_return(
    return_id: str,
    body: ReturnPatchBody,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """확인 체크박스, 정산금액, 환수금액 등 부분 업데이트."""
    svc = _write_service(session)
    ret = await svc.repo.get_async(return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="반품/교환 기록을 찾을 수 없습니다")
    # 테넌트 소유권 검증
    if tenant_id is not None and ret.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403, detail="해당 반품/교환에 대한 권한이 없습니다"
        )
    update_fields: dict[str, Any] = {}
    if body.confirmed is not None:
        update_fields["confirmed"] = body.confirmed
    if body.settlement_amount is not None:
        update_fields["settlement_amount"] = body.settlement_amount
    if body.recovery_amount is not None:
        update_fields["recovery_amount"] = body.recovery_amount
    if body.check_date is not None:
        from backend.utils import kst_iso_to_utc

        update_fields["check_date"] = (
            kst_iso_to_utc(body.check_date) if body.check_date else None
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
    if body.type is not None:
        update_fields["type"] = body.type
    if body.market_order_status is not None:
        update_fields["market_order_status"] = body.market_order_status
    if body.return_source is not None:
        update_fields["return_source"] = body.return_source
    if body.customer_amount is not None:
        update_fields["customer_amount"] = body.customer_amount
    if body.company_amount is not None:
        update_fields["company_amount"] = body.company_amount
    if body.return_link_manual is not None:
        update_fields["return_link_manual"] = body.return_link_manual
    if body.customer_phone_manual is not None:
        update_fields["customer_phone_manual"] = body.customer_phone_manual
    if body.sourcing_order_no is not None:
        update_fields["sourcing_order_no"] = body.sourcing_order_no
    if not update_fields:
        return ret

    updated = await svc.repo.update_async(return_id, **update_fields)

    # 완료내역(반품/취소/교환) 확정 시 연결 주문 status 동기화
    if body.completion_detail is not None:
        await svc._sync_order_status_by_completion(ret.order_id, body.completion_detail)

    return updated


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
    """주소에서 시/군/구 단위를 추출한다.
    - '경기도 수원시 팔달구...' → '수원시 팔달구'
    - '부산광역시 남동구...' → '부산 남동구'
    - '서울특별시 강남구...' → '서울 강남구'
    - '세종특별자치시...' → '세종시'
    - '충남 아산시 ...' → '아산시'
    """
    if not address:
        return None
    parts = address.split()
    if not parts:
        return None
    first = parts[0]
    # 광역시/특별시 → "XX 구이름" (구 단위까지 표기)
    if first.endswith(("광역시", "특별시")):
        city_short = first.replace("광역시", "").replace("특별시", "")
        for p in parts[1:]:
            if p.endswith(("구", "군")):
                return f"{city_short} {p}"
        return f"{city_short}시"
    # 특별자치시(세종) → 세종시
    if first.endswith("특별자치시"):
        return f"{first.replace('특별자치시', '')}시"
    # 도 단위 시작 → 시/군 + 구가 있으면 함께
    city_or_gun: Optional[str] = None
    gu: Optional[str] = None
    for p in parts[1:]:
        if not city_or_gun and p.endswith(("시", "군")):
            city_or_gun = p
            continue
        if city_or_gun and p.endswith("구"):
            gu = p
            break
    if city_or_gun and gu:
        return f"{city_or_gun} {gu}"
    if city_or_gun:
        return city_or_gun
    return first


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

    # 종결 판정: 취소 21=취소완료 / 반품 27=반품완료. 완료일(clmCmptDttm)이 있으면
    # 종결로 본다(실측 2026-07-29: step27 반품은 항상 clmCmptDttm 존재, step23 진행중은
    # 없음). 22=거부. 그 외(반품 23 등)는 진행중.
    if step_cd in ("21", "27") or item.get("clmCmptDttm"):
        status = "completed"
    elif step_cd == "22":
        status = "rejected"
    else:
        status = "requested"

    # 반품 수량: 취소는 cnclQty, 반품은 rtngQty, 없으면 odQty
    qty_raw = item.get("cnclQty") or item.get("rtngQty") or item.get("odQty") or 1
    try:
        qty = int(qty_raw)
    except (ValueError, TypeError):
        qty = 1

    # 잔여수량 — 전체취소(0) 판별용. 주문동기화(order.py)의 부분취소 스킵 가드와 동일 소스.
    try:
        rmdr_qty = int(item.get("rmdrQty", 0) or 0)
    except (TypeError, ValueError):
        rmdr_qty = 0

    return {
        "source": "lotteon",
        "order_number": item.get("odNo", ""),
        "shipment_id": item.get("clmNo", ""),
        "ord_dtl_sn": str(item.get("odSeq", "") or item.get("procSeq", "")),
        "return_type": return_type,
        "reason_code": item.get("clmRsnCd", ""),
        "reason": item.get("clmRsnNm", "") or item.get("clmRsnCd", ""),
        "quantity": qty,
        "rmdr_qty": rmdr_qty,
        "product_name": item.get("spdNm", "") or item.get("sitmNm", ""),
        "product_id": item.get("spdNo", "") or item.get("sitmNo", ""),
        "status": status,
    }


async def _lotteon_find_order_strict(
    order_repo: Any, od_no: str, od_seq: str | None
) -> Any:
    """롯데ON 클레임 매칭 — od_no(+od_seq)로만 조회 (#707).

    shipment_id(=clmNo/배송번호)는 고유하지 않아 한 배송번호를 여러 주문이 공유함
    (find_by_async가 그중 아무 행이나 반환 → 정상 주문에 취소완료가 잘못 붙는 사고).
    order.py의 기존 (od_no, od_seq) 전용 매칭(2026-05-19 사례)과 동일 원칙 적용.
    후보가 여러 개면 잘못 붙이는 것보다 매칭하지 않는 편이 안전하므로 스킵.
    """
    if not od_no:
        return None
    candidates = await order_repo.filter_by_async(
        source="lotteon", od_no=od_no, limit=10
    )
    if od_seq:
        _seq_matched = [c for c in candidates if (c.od_seq or "") == od_seq]
        if _seq_matched:
            candidates = _seq_matched
    if len(candidates) > 1:
        logger.warning(
            f"[롯데ON] 클레임 매칭 후보 {len(candidates)}건(오매칭 위험) — 스킵: "
            f"od_no={od_no} od_seq={od_seq}"
        )
        return None
    return candidates[0] if candidates else None


# 배송 진행 단계 보호 — 주문동기화(order.py `_lo_shipped_guard`)와 동일 집합.
_LO_SHIPPED_GUARD = {
    "송장전송완료",
    "국내배송중",
    "배송완료",
    "구매확정",
    "발송완료",
}
# 취소 라벨 우선순위 — 종결(취소완료)이 요청보다 높다. 하향 전이 차단용.
_LO_CANCEL_PRIORITY = {"취소요청": 1, "취소처리중": 2, "취소완료": 3}


def _lotteon_claim_order_ss(claim: dict[str, Any], current_ss: str) -> Optional[str]:
    """롯데ON 클레임 → 원주문 shipping_status. 변경하면 안 되면 None.

    주문동기화는 odPrgsStepCd 21을 '취소완료'로 매핑하는데(order.py cancel_step_map),
    반품동기화가 상태 무관하게 '취소요청'을 쓰면 두 동기화가 같은 컬럼을 두고 싸운다.
    클레임 조회창이 반품 30일 / 주문 7일이라 8일차 이후엔 되돌리는 쪽만 남아 영구
    고착된다(#642). 롯데온 출고 전 취소는 대부분 신청 즉시 종결(21)이라 사실상 항상
    잘못된 값을 쓰게 된다.
    """
    rt = claim.get("return_type", "")
    if rt != "cancel":
        return "교환요청" if rt == "exchange" else "반품요청"

    status = claim.get("status", "")
    if status == "rejected":
        # 22 철회 = 고객이 취소요청을 회수한 것. 취소가 아니므로 원주문을 건드리지
        # 않는다. '취소요청'을 쓰면 취소도 아닌 주문이 취소요청 좀비로 남는다.
        return None
    if status != "completed":
        return "취소요청"

    # 21 취소완료 — order.py 와 동일한 가드 2종을 적용한 뒤에만 종결 반영
    if int(claim.get("rmdr_qty", 0) or 0) > 0:
        # 부분취소는 전체취소가 아님. 수량 처리는 메인 주문목록 파싱에 위임.
        return None
    if current_ss in _LO_SHIPPED_GUARD:
        # 배송 진행/정산 주문 오취소 차단
        return None
    return "취소완료"


def _lotteon_claim_mos(claim: dict[str, Any]) -> str:
    """롯데ON 클레임 → samba_return.market_order_status. 종결은 종결 라벨로 기록."""
    rt = claim.get("return_type", "")
    if rt == "cancel":
        status = claim.get("status", "")
        if status == "completed":
            return "취소완료"
        if status == "rejected":
            return "취소거부"
        return "취소요청"
    return "교환요청" if rt == "exchange" else "반품요청"


class SyncReturnsRequest(BaseModel):
    days: int = 7
    account_id: Optional[str] = None


@router.post("/sync-from-markets")
async def sync_returns_from_markets(
    body: SyncReturnsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
    run_finalize: bool = True,
):
    """활성 마켓 계정에서 반품/교환/취소 데이터를 가져와 DB에 저장.

    run_finalize:
        True(기본) — 계정 순회 후 전역 후처리(stale auto-close / shipping_status
        일괄 동기화 / 롯데ON 재분류 / claim 백필)까지 실행. 단일 HTTP 호출·단일
        계정 호출은 이 경로.
        False — returns_sync 백그라운드 잡이 계정별로 병렬 호출할 때 사용. 전역
        후처리는 계정 수만큼 반복하면 안 되므로(31× 벌크 UPDATE·5000행 백필 →
        락 경합/데드락) 스킵하고, 잡 핸들러가 모든 계정 완료 후 account_id 미매칭
        sentinel 로 이 함수를 1회 더 호출해 finalize 만 수행한다.
    """
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    from backend.domain.samba.order.repository import SambaOrderRepository

    account_repo = SambaMarketAccountRepository(session)
    order_repo = SambaOrderRepository(session)

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
        all_accounts = await account_repo.filter_by_async(
            is_active=True, order_by="created_at", order_by_desc=True
        )
        if tenant_id is not None:
            active_accounts = [
                a
                for a in all_accounts
                if a.tenant_id == tenant_id or a.tenant_id is None
            ]
        else:
            active_accounts = all_accounts

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

                # 클레임 또는 productOrderStatus 기반 취소/반품/교환 필터
                # 판매자 직접 취소 등 claimType/claimStatus 없이
                # productOrderStatus만 CANCELED/RETURNED/EXCHANGED인 경우도 포함
                _PO_STATUS_FALLBACK: dict[str, tuple[str, str, str, str]] = {
                    # productOrderStatus → (return_type, status, claim_status_raw, display_status)
                    "CANCELED": ("cancel", "completed", "CANCEL_DONE", "취소완료"),
                    "RETURNED": ("return", "completed", "RETURN_DONE", "반품완료"),
                    "EXCHANGED": ("exchange", "completed", "EXCHANGE_DONE", "교환완료"),
                }

                claims_data: list[dict[str, Any]] = []
                for ro in raw_orders:
                    po = ro.get("productOrder", ro)
                    claim_info = (
                        ro.get("claim")
                        if isinstance(ro.get("claim"), dict)
                        else po.get("claim")
                        if isinstance(po.get("claim"), dict)
                        else {}
                    )
                    claim_type = claim_info.get("claimType") or po.get("claimType", "")
                    claim_status = claim_info.get("claimStatus") or po.get(
                        "claimStatus", ""
                    )

                    return_type: str | None = None
                    status: str = ""
                    claim_status_raw: str = ""
                    display_status: str = ""

                    if (
                        claim_type
                        and claim_status
                        and claim_status in _CLAIM_STATUS_MAP
                    ):
                        # 정상 클레임 필드가 있는 경우
                        return_type = _CLAIM_TYPE_MAP.get(claim_type)
                        if not return_type:
                            continue
                        status = _CLAIM_STATUS_MAP[claim_status]
                        claim_status_raw = claim_status
                        display_status = _CLAIM_STATUS_DISPLAY.get(
                            claim_status, claim_status
                        )
                    else:
                        # claimType/claimStatus 없음 → productOrderStatus로 추론
                        po_status = po.get("productOrderStatus", "")
                        fallback = _PO_STATUS_FALLBACK.get(po_status)
                        if not fallback:
                            continue
                        return_type, status, claim_status_raw, display_status = fallback

                    product_order_id = po.get("productOrderId", "")
                    sale_price = (
                        po.get("totalPaymentAmount", 0) or po.get("unitPrice", 0) or 0
                    )
                    quantity = po.get("quantity", 1) or 1

                    # 클레임 사유
                    claim_reason = (
                        claim_info.get("claimReason", "")
                        or claim_info.get("returnReason", "")
                        or po.get("claimReason", "")
                        or po.get("returnReason", "")
                        or ""
                    )

                    claims_data.append(
                        {
                            "product_order_id": product_order_id,
                            "type": return_type,
                            "status": status,
                            "claim_status_raw": claim_status_raw,
                            "display_status": display_status,
                            "reason": claim_reason,
                            "quantity": quantity,
                            "requested_amount": float(sale_price),
                            "product_name": po.get("productName", ""),
                            "product_image": po.get("imageUrl", ""),
                            "product_option": po.get("productOption", "") or "",
                        }
                    )

                # 기존 주문 매칭 및 반품 레코드 생성/업데이트
                synced = 0
                for claim in claims_data:
                    product_order_id = claim["product_order_id"]
                    # 주문 테이블에서 order_number로 매칭
                    existing_order = await order_repo.find_by_async(
                        order_number=product_order_id
                    )
                    if not existing_order:
                        # 주문이 아직 동기화 안 된 경우 — 건너뜀
                        continue

                    order_id = existing_order.id
                    # 이미 동일한 반품 기록이 있는지 확인 (order_id 기준)
                    existing_returns = await svc.repo.filter_by_async(order_id=order_id)

                    if existing_returns:
                        # 같은 타입 우선, 없으면 첫 번째 레코드 사용
                        existing_ret = next(
                            (r for r in existing_returns if r.type == claim["type"]),
                            existing_returns[0],
                        )
                        # 타입이 변경된 경우 (교환→반품 등) 업데이트
                        if existing_ret.type != claim["type"]:
                            await svc.repo.update_async(
                                existing_ret.id, type=claim["type"]
                            )
                        new_status = claim["status"]
                        # 상태 진행도: requested → approved → completed/rejected
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
                                        claim["claim_status_raw"], f"상태: {new_status}"
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
                                update_data["completion_detail"] = {
                                    "cancel": "취소",
                                    "return": "반품",
                                    "exchange": "교환",
                                }.get(claim["type"], existing_ret.completion_detail)
                            elif new_status == "rejected":
                                update_data["completion_detail"] = "거부"
                            await svc.repo.update_async(existing_ret.id, **update_data)
                        # 이미지/전화번호/주소/주문일 보충
                        patch_fields: dict[str, Any] = {}
                        patch_fields["order_date"] = (
                            existing_order.paid_at or existing_order.created_at
                        )
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

                    # 신규 반품 생성
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
                        "order_date": existing_order.paid_at
                        or existing_order.created_at,
                        "status": claim["status"],
                        "completion_detail": (
                            {
                                "cancel": "취소",
                                "return": "반품",
                                "exchange": "교환",
                            }.get(claim["type"], "진행중")
                            if claim["status"] == "completed"
                            else "거부"
                            if claim["status"] == "rejected"
                            else "진행중"
                        ),
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
                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "fetched": len(claims_data),
                        "synced": synced,
                    }
                )
                logger.info(
                    f"[반품동기화] {label}: 클레임 {len(claims_data)}건 조회, {synced}건 신규 저장"
                )

            elif market_type == "lotteon":
                from backend.domain.samba.proxy.lotteon import (
                    LotteonClient,
                )

                api_key = account.api_key or extras.get("apiKey", "")
                if not api_key:
                    results.append(
                        {"account": label, "status": "skip", "message": "API 키 없음"}
                    )
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
                for item in raw_cancels:
                    parsed = _parse_lotteon_return(item, "cancel")
                    parsed["sitmNo"] = item.get("sitmNo", "")
                    claims_data_lo.append(parsed)
                _lo_od_nos = [c["order_number"] for c in claims_data_lo]
                logger.warning(
                    f"[롯데ON] 반품 API 조회된 odNo 목록({len(_lo_od_nos)}건): {_lo_od_nos}"
                )

                synced = 0
                for claim in claims_data_lo:
                    order_number = claim["order_number"]
                    if not order_number:
                        continue
                    # od_no(+od_seq) 전용 매칭 (#707) — shipment_id(clmNo)는 고유하지
                    # 않아 다른 주문에 잘못 붙는 사고 원인이었음. order_number 필드에는
                    # 클레임 API의 odNo(주문번호)가 그대로 들어있어 DB의 order_number
                    # 컬럼(상품주문번호=odNo_odSeq)과는 형식이 달라 직접 비교하지 않음.
                    existing_order = await _lotteon_find_order_strict(
                        order_repo, order_number, claim.get("ord_dtl_sn") or None
                    )
                    if not existing_order:
                        logger.warning(
                            f"[롯데ON] 반품 주문 미매칭: {order_number} sitmNo={claim.get('sitmNo', '')}"
                        )
                        continue

                    order_id = existing_order.id
                    logger.warning(
                        f"[롯데ON] 반품 주문 매칭 성공: {order_number} → DB order_id={order_id}"
                    )
                    existing_returns = await svc.repo.filter_by_async(
                        order_id=order_id, type=claim["return_type"]
                    )
                    if existing_returns:
                        # 기존 레코드에 누락/오류 필드 보충
                        er = existing_returns[0]
                        patch_lo: dict[str, Any] = {}
                        patch_lo["order_date"] = (
                            existing_order.paid_at or existing_order.created_at
                        )
                        correct_type = claim[
                            "return_type"
                        ]  # API에서 확정된 type (return/exchange)
                        if not er.product_image and existing_order.product_image:
                            patch_lo["product_image"] = existing_order.product_image
                        # market_order_status가 type과 불일치하면 강제 수정
                        if (
                            correct_type == "exchange"
                            and er.market_order_status
                            and "반품" in er.market_order_status
                        ):
                            patch_lo["market_order_status"] = "교환요청"
                        elif (
                            correct_type == "return"
                            and er.market_order_status
                            and "교환" in er.market_order_status
                        ):
                            patch_lo["market_order_status"] = "반품요청"
                        elif not er.market_order_status:
                            patch_lo["market_order_status"] = (
                                "교환요청" if correct_type == "exchange" else "반품요청"
                            )
                        # type이 없거나 잘못 저장된 경우 수정
                        if er.type != correct_type:
                            patch_lo["type"] = correct_type
                        patch_lo["market_order_status"] = _lotteon_claim_mos(claim)
                        status_priority = {
                            "requested": 0,
                            "approved": 1,
                            "completed": 2,
                            "rejected": 2,
                            "cancelled": 2,
                        }
                        if status_priority.get(
                            claim["status"], 0
                        ) > status_priority.get(er.status, 0):
                            from datetime import UTC, datetime

                            patch_lo["status"] = claim["status"]
                            if claim["status"] in ("completed", "rejected"):
                                patch_lo["completion_date"] = datetime.now(UTC)
                        if claim["status"] == "completed":
                            patch_lo["completion_detail"] = {
                                "cancel": "취소",
                                "return": "반품",
                                "exchange": "교환",
                            }.get(correct_type, er.completion_detail)
                        elif claim["status"] == "rejected":
                            patch_lo["completion_detail"] = "거부"
                        if patch_lo:
                            await svc.repo.update_async(er.id, **patch_lo)
                            logger.warning(
                                f"[롯데ON] 반품 레코드 패치: {order_number} type={correct_type} patch={list(patch_lo.keys())} er.type={er.type} er.market_order_status={er.market_order_status}"
                            )
                        else:
                            logger.warning(
                                f"[롯데ON] 반품 레코드 패치 불필요: {order_number} er.type={er.type} er.market_order_status={er.market_order_status}"
                            )
                        # 원주문 shipping_status 동기화 (교환/반품 진행 중이면 주문 페이지에서 제외)
                        _cur_ss = existing_order.shipping_status or ""
                        new_order_ss = _lotteon_claim_order_ss(claim, _cur_ss)
                        if new_order_ss and _cur_ss != new_order_ss:
                            # 종결 라벨 하향 전이 차단 — 취소완료 주문을 취소요청/반품요청으로
                            # 되돌리지 않는다(#335 일괄 SQL 가드가 못 막던 per-claim 경로).
                            _cur_p = _LO_CANCEL_PRIORITY.get(_cur_ss, 0)
                            _new_p = _LO_CANCEL_PRIORITY.get(new_order_ss, 0)
                            if _cur_p == 0 or _new_p >= _cur_p:
                                await order_repo.update_async(
                                    existing_order.id, shipping_status=new_order_ss
                                )
                        continue

                    from datetime import UTC, datetime

                    return_data: dict[str, Any] = {
                        "order_id": order_id,
                        "order_number": order_number,
                        "type": claim["return_type"],
                        "reason": claim["reason"] or None,
                        "quantity": claim["quantity"],
                        "product_name": claim["product_name"]
                        or (existing_order.product_name if existing_order else None),
                        "product_image": existing_order.product_image
                        if existing_order
                        else None,
                        "customer_name": existing_order.customer_name
                        if existing_order
                        else None,
                        "customer_phone": existing_order.customer_phone
                        if existing_order
                        else None,
                        "product_location": _extract_city_district(
                            existing_order.customer_address if existing_order else None
                        ),
                        "customer_address": existing_order.customer_address
                        if existing_order
                        else None,
                        "business_name": account.business_name
                        or account.market_name
                        or label,
                        "market": "롯데ON",
                        "market_order_status": "교환요청"
                        if claim["return_type"] == "exchange"
                        else "반품요청",
                        "status": claim["status"],
                        "completion_detail": (
                            {
                                "cancel": "취소",
                                "return": "반품",
                                "exchange": "교환",
                            }.get(claim["return_type"], "진행중")
                            if claim["status"] == "completed"
                            else "거부"
                            if claim["status"] == "rejected"
                            else "진행중"
                        ),
                        "timeline": [
                            {
                                "date": datetime.now(UTC).isoformat(),
                                "status": claim["status"],
                                "message": f"{claim['return_type']} 요청 접수",
                            }
                        ],
                        "notes": [],
                    }
                    return_data["market_order_status"] = _lotteon_claim_mos(claim)
                    await svc.repo.create_async(**return_data)
                    # 원주문 shipping_status 동기화
                    _cur_ss = existing_order.shipping_status or ""
                    new_order_ss = _lotteon_claim_order_ss(claim, _cur_ss)
                    if new_order_ss and _cur_ss != new_order_ss:
                        _cur_p = _LO_CANCEL_PRIORITY.get(_cur_ss, 0)
                        _new_p = _LO_CANCEL_PRIORITY.get(new_order_ss, 0)
                        if _cur_p == 0 or _new_p >= _cur_p:
                            await order_repo.update_async(
                                existing_order.id, shipping_status=new_order_ss
                            )
                    synced += 1

                # 교환 클레임 동기화
                try:
                    raw_exchanges = await client.get_exchanges(days=body.days)
                    for item in raw_exchanges:
                        ex_order_number = item.get("odNo", "")
                        if not ex_order_number:
                            continue
                        # od_no(+od_seq) 전용 매칭 (#707) — 반품/취소 경로와 동일 이유로
                        # shipment_id(sitmNo) fallback 제거.
                        existing_order = await _lotteon_find_order_strict(
                            order_repo,
                            ex_order_number,
                            str(item.get("odSeq", "") or item.get("procSeq", ""))
                            or None,
                        )
                        if not existing_order:
                            logger.warning(
                                f"[롯데ON] 교환 주문 미매칭: {ex_order_number} sitmNo={item.get('sitmNo', '')}"
                            )
                            continue
                        order_id = existing_order.id
                        existing_returns = await svc.repo.filter_by_async(
                            order_id=order_id, type="exchange"
                        )
                        if existing_returns:
                            # 기존 레코드 image 보충 (type은 변경 금지 — 교환취소 후 반품 재신청 케이스 보호)
                            er = existing_returns[0]
                            patch: dict[str, Any] = {}
                            patch["order_date"] = (
                                existing_order.paid_at or existing_order.created_at
                            )
                            if not er.product_image and existing_order.product_image:
                                patch["product_image"] = existing_order.product_image
                            if not er.market_order_status:
                                patch["market_order_status"] = (
                                    "교환요청" if er.type == "exchange" else "반품요청"
                                )
                            if patch:
                                await svc.repo.update_async(er.id, **patch)
                            # shipping_status는 현재 저장된 type 기준으로 동기화 (덮어쓰기 금지)
                            expected_ss = (
                                "교환요청" if er.type == "exchange" else "반품요청"
                            )
                            if existing_order.shipping_status != expected_ss:
                                await order_repo.update_async(
                                    existing_order.id, shipping_status=expected_ss
                                )
                            continue
                        # 이미 취소/반품 레코드가 있으면 교환 레코드 생성 금지
                        # (롯데ON API 버그: 취소 주문이 교환 API에도 포함되는 케이스)
                        existing_cancel_or_return = await svc.repo.filter_by_async(
                            order_id=order_id
                        )
                        if existing_cancel_or_return:
                            logger.warning(
                                f"[롯데ON][교환동기화] 이미 {existing_cancel_or_return[0].type} 레코드 존재 → 교환 생성 스킵: {ex_order_number}"
                            )
                            continue
                        from datetime import UTC, datetime

                        await svc.repo.create_async(
                            order_id=order_id,
                            order_number=ex_order_number,
                            type="exchange",
                            reason=item.get("clmRsnCd", "") or None,
                            quantity=int(item.get("xchgQty") or item.get("odQty") or 1),
                            product_name=item.get("spdNm", "")
                            or existing_order.product_name,
                            product_image=existing_order.product_image,
                            customer_name=existing_order.customer_name,
                            customer_phone=existing_order.customer_phone,
                            product_location=_extract_city_district(
                                existing_order.customer_address
                            ),
                            customer_address=existing_order.customer_address,
                            business_name=account.business_name
                            or account.market_name
                            or label,
                            market="롯데ON",
                            market_order_status="교환요청",
                            status="requested",
                            timeline=[
                                {
                                    "date": datetime.now(UTC).isoformat(),
                                    "status": "requested",
                                    "message": "교환 요청 접수",
                                }
                            ],
                            notes=[],
                        )
                        # 원주문 shipping_status 동기화
                        await order_repo.update_async(
                            existing_order.id, shipping_status="교환요청"
                        )
                        synced += 1
                        logger.info(
                            f"[반품동기화][롯데ON] 교환 클레임 저장: {ex_order_number}"
                        )
                except Exception as ex_err:
                    logger.warning(
                        f"[반품동기화][롯데ON] 교환 클레임 동기화 실패: {ex_err}"
                    )

                total_synced += synced
                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "fetched": len(claims_data_lo),
                        "synced": synced,
                    }
                )
                logger.info(
                    f"[반품동기화][롯데ON] {label}: 반품 {len(raw_returns)}건, 취소 {len(raw_cancels)}건 조회, {synced}건 신규 저장"
                )

            elif market_type == "lotteon":
                # 롯데ON 인증정보 추출
                api_key = (extras.get("apiKey") or account.api_key or "").strip()
                if not api_key:
                    results.append(
                        {"account": label, "status": "skip", "message": "API 키 없음"}
                    )
                    continue

                from backend.domain.samba.proxy.lotteon import (
                    LotteonClient,
                )

                client = LotteonClient(api_key)

                # 반품 + 취소 동시 조회
                raw_returns = await client.get_returns(days=body.days)
                raw_cancels = await client.get_cancel_orders(days=body.days)

                claims_data_lo: list[dict[str, Any]] = []
                for item in raw_returns:
                    claims_data_lo.append(_parse_lotteon_return(item, "return"))
                for item in raw_cancels:
                    claims_data_lo.append(_parse_lotteon_return(item, "cancel"))

                # 스마트스토어와 동일한 upsert 로직 적용
                synced_lo = 0
                for claim in claims_data_lo:
                    order_number = claim.get("order_number", "")
                    if not order_number:
                        continue
                    # 기존 주문 매칭
                    existing_order = await order_repo.find_by_async(
                        order_number=order_number
                    )
                    if not existing_order:
                        logger.warning(f"[롯데ON] 반품 주문 미매칭: {order_number}")
                        continue
                    order_id = existing_order.id
                    # 이미 동일한 반품 기록이 있는지 확인 (order_id 기준)
                    existing_returns_lo = await svc.repo.filter_by_async(
                        order_id=order_id
                    )
                    if existing_returns_lo:
                        # 같은 타입 우선, 없으면 첫 번째 레코드 사용
                        existing_ret = next(
                            (
                                r
                                for r in existing_returns_lo
                                if r.type == claim["return_type"]
                            ),
                            existing_returns_lo[0],
                        )
                        new_status = claim["status"]
                        status_priority = {
                            "requested": 0,
                            "approved": 1,
                            "completed": 2,
                            "rejected": 2,
                            "cancelled": 2,
                        }
                        update_lo: dict[str, Any] = {
                            "order_date": existing_order.paid_at
                            or existing_order.created_at
                        }
                        if status_priority.get(new_status, 0) > status_priority.get(
                            existing_ret.status, 0
                        ):
                            update_lo["status"] = new_status
                        await svc.repo.update_async(existing_ret.id, **update_lo)
                        continue
                    # 신규 반품 생성
                    market_label_map_lo: dict[str, str] = {
                        "smartstore": "스마트스토어",
                        "coupang": "쿠팡",
                        "11st": "11번가",
                        "lotteon": "롯데ON",
                        "ssg": "SSG",
                        "gsshop": "GS샵",
                    }
                    return_data_lo: dict[str, Any] = {
                        "order_id": order_id,
                        "order_number": order_number,
                        "type": claim["return_type"],
                        "reason": claim["reason"] or None,
                        "quantity": claim["quantity"],
                        "product_name": claim["product_name"]
                        or existing_order.product_name,
                        "product_image": existing_order.product_image,
                        "customer_name": existing_order.customer_name,
                        "customer_phone": existing_order.customer_phone,
                        "product_location": _extract_city_district(
                            existing_order.customer_address
                        ),
                        "customer_address": existing_order.customer_address,
                        "business_name": account.business_name
                        or account.market_name
                        or label,
                        "market": market_label_map_lo.get(market_type, market_type),
                        "order_date": existing_order.paid_at
                        or existing_order.created_at,
                        "status": claim["status"],
                        "notes": [],
                    }
                    await svc.repo.create_async(**return_data_lo)
                    synced_lo += 1

                total_synced += synced_lo
                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "returns": len(raw_returns),
                        "cancels": len(raw_cancels),
                        "synced": synced_lo,
                    }
                )
                logger.info(
                    f"[반품동기화][롯데ON] {label}: 반품 {len(raw_returns)}건, 취소 {len(raw_cancels)}건 조회, {synced_lo}건 신규 저장"
                )

            elif market_type == "coupang":
                from datetime import UTC, datetime

                from backend.domain.samba.proxy.coupang import CoupangClient

                access_key = account.api_key or extras.get("accessKey", "")
                secret_key = account.api_secret or extras.get("secretKey", "")
                # extras.vendorId(A0xxxxxxx) 우선, 없을 때만 account.seller_id fallback
                # (account.seller_id는 로그인 ID 'zerocp'가 들어있어 404 유발)
                vendor_id = extras.get("vendorId", "") or account.seller_id or ""
                if not access_key or not secret_key or not vendor_id:
                    results.append(
                        {"account": label, "status": "skip", "message": "API 설정 없음"}
                    )
                    continue

                client = CoupangClient(access_key, secret_key, vendor_id)

                def _coupang_status(raw: Any) -> str:
                    value = str(raw or "").upper()
                    if any(x in value for x in ("COMPLETE", "DONE", "FINISH")):
                        return "completed"
                    if any(x in value for x in ("REJECT", "DENY", "FAIL")):
                        return "rejected"
                    if any(x in value for x in ("APPROVE", "RECEIVE", "COLLECT")):
                        return "approved"
                    return "requested"

                def _coupang_order_candidates(item: dict[str, Any]) -> list[str]:
                    candidates: list[str] = []
                    for key in (
                        "orderId",
                        "orderNo",
                        "orderNumber",
                        "shipmentBoxId",
                        "receiptId",
                    ):
                        value = item.get(key)
                        if value:
                            candidates.append(str(value))
                    for nested_key in ("items", "returnItems", "exchangeItems"):
                        nested = item.get(nested_key)
                        if isinstance(nested, list):
                            for child in nested:
                                if not isinstance(child, dict):
                                    continue
                                for key in ("orderId", "orderNo", "shipmentBoxId"):
                                    value = child.get(key)
                                    if value:
                                        candidates.append(str(value))
                    return list(dict.fromkeys(candidates))

                async def _sync_coupang_items(
                    items: list[dict[str, Any]], return_type: str
                ) -> int:
                    synced_count = 0
                    for item in items:
                        existing_order = None
                        for candidate in _coupang_order_candidates(item):
                            existing_order = await order_repo.find_by_async(
                                order_number=candidate
                            )
                            # 쿠팡 반품 orderId(=배송번호)는 삼바 order_number(상품주문번호)와
                            # 다르고 shipment_id 에 저장된다. order_number 매칭 실패 시
                            # shipment_id 로 재시도 — 안 하면 RETURNS_COMPLETED 갱신이
                            # 스킵돼 반품완료 주문이 진행중으로 고착(덕수궁 관측).
                            if not existing_order:
                                existing_order = await order_repo.find_by_async(
                                    shipment_id=candidate
                                )
                            if existing_order:
                                break
                        if not existing_order:
                            continue

                        status_raw = (
                            item.get("status")
                            or item.get("receiptStatus")
                            or item.get("returnStatus")
                            or item.get("exchangeStatus")
                        )
                        status = _coupang_status(status_raw)
                        # 쿠팡 returnRequests 엔드포인트는 출고중지요청(상품준비중 단계 취소)을
                        # 실제 반품과 같은 응답에 담아 내려준다. 이 건은 receiptType 이
                        # 'RETURN' 이지만 receiptStatus 가 RELEASE_STOP_*(출고중지요청,
                        # 예: RELEASE_STOP_UNCHECKED) 이다 — 실측 확인(손성아/조미혜 2026-07,
                        # cancelReasonCategory1='고객변심'). receiptStatus 를 무시하고 전부
                        # 'return' 으로 저장하면 출고전 취소가 반품으로 둔갑 → 주문상태가
                        # 반품요청으로 덮여 취소가 반품에 갇힌다. 출고중지요청은 취소로 분류.
                        # (결제완료 단계 취소 CANCEL 카테고리의 receiptType='CANCEL' 도 포함.)
                        receipt_type = (item.get("receiptType") or "").upper()
                        receipt_status = (item.get("receiptStatus") or "").upper()
                        is_cancel_claim = (
                            receipt_type == "CANCEL"
                            or receipt_status.startswith("RELEASE_STOP")
                            or receipt_status == "RU"
                        )
                        # 완료단계 모호성 보정: 취소승인(출고중지완료) 후 쿠팡은 그 건을
                        # 반품완료와 동일한 RETURNS_COMPLETED 로 내려줘 receiptStatus 로는
                        # 취소완료/반품완료 구분 불가(실측 손성아/조미혜 2026-07). 이 주문에
                        # 살아있는(거부 아님) 취소 클레임이 이미 있으면 이 완료건을 그 취소의
                        # 완료로 귀속시켜 반품행 재생성을 막는다. 취소 클레임은 RELEASE_STOP
                        # 단계에서 이미 취소행으로 기록되므로(위 분기) 완료건은 그 뒤에 온다.
                        if return_type == "return" and not is_cancel_claim:
                            _prior_cancels = await svc.repo.filter_by_async(
                                order_id=existing_order.id, type="cancel"
                            )
                            if any(
                                (p.status or "").lower() != "rejected"
                                for p in _prior_cancels
                            ):
                                is_cancel_claim = True
                        effective_type = (
                            "cancel"
                            if return_type == "return" and is_cancel_claim
                            else return_type
                        )
                        _done_label = {
                            "exchange": "교환",
                            "cancel": "취소",
                        }.get(effective_type, "반품")
                        # 주문상태 갱신용 '요청' 라벨(신규 진입 시점).
                        _req_label = {
                            "return": "반품요청",
                            "exchange": "교환요청",
                            "cancel": "취소요청",
                        }.get(effective_type, "반품요청")
                        # 반품행 market_order_status — 요청/완료/거부 상태 반영.
                        # 완료건을 요청으로 되돌려 찍지 않는다(취소완료→취소요청 하향 방지).
                        if status == "completed":
                            _status_label = {
                                "exchange": "교환완료",
                                "cancel": "취소완료",
                            }.get(effective_type, "반품완료")
                        elif status == "rejected":
                            _status_label = {
                                "exchange": "교환거부",
                                "cancel": "취소거부",
                            }.get(effective_type, "반품거부")
                        else:
                            _status_label = _req_label
                        existing_returns = await svc.repo.filter_by_async(
                            order_id=existing_order.id, type=effective_type
                        )
                        if existing_returns:
                            patch: dict[str, Any] = {
                                "order_date": existing_order.paid_at
                                or existing_order.created_at,
                                "market_order_status": _status_label,
                            }
                            if status in ("approved", "completed", "rejected"):
                                patch["status"] = status
                            if status == "completed":
                                patch["completion_detail"] = _done_label
                                patch["completion_date"] = datetime.now(UTC)
                            elif status == "rejected":
                                patch["completion_detail"] = "거부"
                                patch["completion_date"] = datetime.now(UTC)
                            await svc.repo.update_async(existing_returns[0].id, **patch)
                            continue

                        first_item = {}
                        for nested_key in ("items", "returnItems", "exchangeItems"):
                            nested = item.get(nested_key)
                            if isinstance(nested, list) and nested:
                                first_item = (
                                    nested[0] if isinstance(nested[0], dict) else {}
                                )
                                break

                        order_number = str(
                            item.get("orderId")
                            or item.get("orderNo")
                            or existing_order.order_number
                        )
                        return_data = {
                            "order_id": existing_order.id,
                            "order_number": order_number,
                            "type": effective_type,
                            "reason": item.get("returnReason")
                            or item.get("reason")
                            or item.get("reasonCode")
                            or None,
                            "description": item.get("reasonDetail")
                            or item.get("returnDetailedReason")
                            or None,
                            "quantity": int(
                                item.get("returnCount")
                                or item.get("exchangeCount")
                                or first_item.get("quantity")
                                or 1
                            ),
                            "requested_amount": float(
                                item.get("returnDeliveryFee")
                                or item.get("returnAmount")
                                or existing_order.sale_price
                                or 0
                            ),
                            "product_image": existing_order.product_image,
                            "product_name": first_item.get("vendorItemName")
                            or item.get("vendorItemName")
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
                            "market": "쿠팡",
                            "market_order_status": _status_label,
                            "return_link": existing_order.source_url or "",
                            "return_source": existing_order.source_site or "",
                            "region": _extract_city_district(
                                existing_order.customer_address
                            ),
                            "return_request_date": datetime.now(UTC),
                            "order_date": existing_order.paid_at
                            or existing_order.created_at,
                            "status": status,
                            "completion_detail": (
                                _done_label
                                if status == "completed"
                                else "거부"
                                if status == "rejected"
                                else "진행중"
                            ),
                            "timeline": [
                                {
                                    "date": datetime.now(UTC).isoformat(),
                                    "status": status,
                                    "message": f"쿠팡 {effective_type} 클레임 동기화",
                                }
                            ],
                            "notes": [],
                        }
                        if status in ("approved", "completed"):
                            return_data["approval_date"] = datetime.now(UTC)
                        if status in ("completed", "rejected"):
                            return_data["completion_date"] = datetime.now(UTC)
                        await svc.repo.create_async(**return_data)
                        # 종결(취소완료/반품완료/교환완료) 주문을 새 '요청' 상태로 하향
                        # 덮어쓰지 않는다 — 롯데ON 경로와 동일 원칙. 특히 이미 취소완료된
                        # 주문이 뒤늦은 출고중지요청 sync 로 취소요청/반품요청으로 되돌아가
                        # 미종결처럼 보이던 문제(손성아) 차단.
                        _cur = (existing_order.status or "").strip().lower()
                        if _cur not in ("cancelled", "returned", "exchanged"):
                            _new_status = {
                                "exchange": "exchange_requested",
                                "cancel": "cancel_requested",
                            }.get(effective_type, "return_requested")
                            await order_repo.update_async(
                                existing_order.id,
                                status=_new_status,
                                shipping_status=_req_label,
                            )
                        synced_count += 1
                    return synced_count

                return_items = await client.get_return_requests(days=body.days)
                exchange_items = await client.get_exchange_requests(days=body.days)
                return_synced = await _sync_coupang_items(return_items, "return")
                exchange_synced = await _sync_coupang_items(exchange_items, "exchange")
                synced = return_synced + exchange_synced
                total_synced += synced
                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "fetched": len(return_items) + len(exchange_items),
                        "synced": synced,
                    }
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

                from backend.utils import now_kst

                end_dt = now_kst()  # KST 기준 (11번가 API는 KST 시각 사용)
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

                    mapped_status = "requested"

                    timeline_msg = "11번가 교환 요청이 접수되었습니다."
                    if existing_returns:
                        # 기존 레코드 — clm_req_seq/ord_prd_seq 보완
                        existing_ret = existing_returns[0]
                        patch: dict[str, Any] = {
                            "order_date": existing_order.paid_at
                            or existing_order.created_at
                        }
                        if clm_req_seq and not existing_ret.clm_req_seq:
                            patch["clm_req_seq"] = clm_req_seq
                        if ord_prd_seq and not existing_ret.ord_prd_seq:
                            patch["ord_prd_seq"] = ord_prd_seq
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
                        "order_date": existing_order.paid_at
                        or existing_order.created_at,
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
                        "order_date": existing_order.paid_at
                        or existing_order.created_at,
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
                        patch: dict[str, Any] = {
                            "order_date": existing_order.paid_at
                            or existing_order.created_at
                        }
                        if clm_req_seq and not existing_ret.clm_req_seq:
                            patch["clm_req_seq"] = clm_req_seq
                        if ord_prd_seq and not existing_ret.ord_prd_seq:
                            patch["ord_prd_seq"] = ord_prd_seq
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
                        "order_date": existing_order.paid_at
                        or existing_order.created_at,
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

            elif market_type == "ebay":
                from backend.domain.samba.proxy.ebay import EbayClient

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
                    raw_returns = await ebay_client.get_returns(days=body.days)
                except Exception as e:
                    results.append(
                        {"account": label, "status": "error", "message": str(e)[:150]}
                    )
                    continue

                synced_ebay = 0
                for ret in raw_returns:
                    return_id = str(ret.get("returnId", ""))
                    order_id_ebay = str(ret.get("orderId", ""))
                    state = ret.get("state") or ret.get("status") or ""
                    reason = (ret.get("creationInfo") or {}).get("reason", "") or ""
                    buyer = str(ret.get("buyerLoginName", ""))
                    item_info = ret.get("creationInfo", {}).get("item", {})
                    item_title = str(item_info.get("itemTitle", ""))
                    refund_amt = (
                        (ret.get("sellerTotalRefund") or {})
                        .get("estimatedRefundAmount", {})
                        .get("value", 0)
                    )
                    creation_date = (
                        (ret.get("creationInfo") or {})
                        .get("creationDate", {})
                        .get("value", "")
                    )

                    # 상태 매핑
                    state_map = {
                        "RETURN_REQUESTED": "반품요청",
                        "RETURN_ACCEPTED": "반품승인",
                        "RETURN_DELIVERED": "반품완료",
                        "CLOSED": "반품완료",
                        "ESCALATED": "반품요청",
                    }
                    market_status = state_map.get(state, state or "반품요청")

                    # 기존 주문 찾기
                    existing_order = await order_repo.find_by_async(
                        order_number=order_id_ebay
                    )
                    order_db_id = existing_order.id if existing_order else ""

                    # 중복 체크
                    existing_ret = await svc.repo.find_by_async(
                        order_number=order_id_ebay, type="return"
                    )
                    if existing_ret:
                        # 상태 업데이트만
                        await svc.repo.update_async(
                            existing_ret.id,
                            market_order_status=market_status,
                            memo=return_id,
                        )
                        continue

                    from datetime import datetime as _dt, timezone as _tz

                    creation_dt = None
                    if creation_date:
                        try:
                            creation_dt = _dt.fromisoformat(
                                creation_date.replace("Z", "+00:00")
                            )
                        except Exception:
                            creation_dt = _dt.now(_tz.utc)

                    return_data = {
                        "order_id": order_db_id,
                        "order_number": order_id_ebay,
                        "type": "return",
                        "status": "requested",
                        "reason": reason,
                        "market": label,
                        "market_order_status": market_status,
                        "memo": return_id,
                        "product_name": item_title
                        or (existing_order.product_name if existing_order else ""),
                        "product_image": existing_order.product_image
                        if existing_order
                        else "",
                        "customer_name": buyer
                        or (existing_order.customer_name if existing_order else ""),
                        "customer_phone": existing_order.customer_phone
                        if existing_order
                        else "",
                        "customer_address": existing_order.customer_address
                        if existing_order
                        else "",
                        "requested_amount": float(refund_amt) if refund_amt else 0,
                        "return_request_date": creation_dt,
                        "return_link": f"https://www.ebay.com/mesh/ord/details?orderid={order_id_ebay}",
                        "tenant_id": account.tenant_id or tenant_id,
                    }
                    await svc.repo.create_async(**return_data)
                    synced_ebay += 1

                    # 원주문 shipping_status 업데이트
                    if existing_order:
                        await order_repo.update_async(
                            existing_order.id,
                            shipping_status=market_status,
                            status="return_requested"
                            if "요청" in market_status
                            else "returned",
                        )

                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "fetched": len(raw_returns),
                        "synced": synced_ebay,
                    }
                )
                total_synced += synced_ebay
                logger.info(
                    f"[반품동기화][eBay] {label}: 반품 {len(raw_returns)}건 조회, {synced_ebay}건 신규"
                )

            elif market_type in ("gmarket", "auction"):
                from backend.domain.samba.proxy.esmplus import (
                    ESMPlusClient,
                    resolve_esm_credentials,
                )
                from datetime import (
                    UTC as _esm_UTC,
                    datetime as _esm_dt,
                    timedelta as _esm_td,
                    timezone as _esm_tz,
                )

                esm_hosting_id, esm_secret_key = await resolve_esm_credentials(
                    session, account
                )
                if not esm_hosting_id or not esm_secret_key:
                    results.append(
                        {
                            "account": label,
                            "status": "skip",
                            "message": "ESM 인증정보 없음",
                        }
                    )
                    continue
                if not seller_id:
                    results.append(
                        {
                            "account": label,
                            "status": "skip",
                            "message": "ESM seller_id 없음",
                        }
                    )
                    continue

                # claim API SiteType: 1=옥션, **3=G마켓** (주문 API의 2=G마켓과 다름!)
                _esm_claim_site_type = 3 if market_type == "gmarket" else 1
                # 7일 max — claim API 한도. to=내일(+1) 여유 위해 -1.
                _esm_days_claim = min(int(body.days or 1), 6)
                # KST 기준 + EndDate=내일 — to=오늘이면 당일 클레임 누락(#369)
                _esm_KST = _esm_tz(_esm_td(hours=9))
                _esm_now_claim = _esm_dt.now(_esm_KST)
                _esm_from_claim = (
                    _esm_now_claim - _esm_td(days=_esm_days_claim)
                ).strftime("%Y-%m-%d")
                _esm_to_claim = (_esm_now_claim + _esm_td(days=1)).strftime("%Y-%m-%d")

                _esm_client = ESMPlusClient(
                    esm_hosting_id, esm_secret_key, seller_id, site=market_type
                )

                # CancelStatus 1~4 → status
                _cancel_status_map = {
                    1: ("requested", "취소요청"),
                    2: ("cancelled", "취소완료"),
                    3: ("completed", "취소완료"),
                    4: ("rejected", "취소거부"),
                }
                # ExchangeStatus 1~5 → status
                _exchange_status_map = {
                    1: ("requested", "교환요청"),
                    2: ("approved", "교환진행"),
                    3: ("approved", "교환진행"),
                    4: ("completed", "교환완료"),
                    5: ("rejected", "교환거부"),
                }
                # ReturnStatus 1~5 → status
                _return_status_map = {
                    1: ("requested", "반품요청"),
                    2: ("approved", "반품진행"),
                    3: ("approved", "반품진행"),
                    4: ("completed", "반품완료"),
                    5: ("rejected", "반품거부"),
                }

                _market_label = "G마켓" if market_type == "gmarket" else "옥션"

                try:
                    _cancel_resp = await _esm_client.search_cancels(
                        {
                            "SiteType": _esm_claim_site_type,
                            "CancelStatus": 0,
                            "Type": 2,
                            "StartDate": _esm_from_claim,
                            "EndDate": _esm_to_claim,
                        }
                    )
                except Exception as _ce:
                    logger.warning(
                        f"[반품동기화][ESM] {label}: cancels 조회 실패 — {_ce}"
                    )
                    _cancel_resp = {}

                try:
                    _exchange_resp = await _esm_client.search_exchanges(
                        {
                            "SiteType": _esm_claim_site_type,
                            "ExchangeStatus": 0,
                            "Type": 2,
                            "StartDate": _esm_from_claim,
                            "EndDate": _esm_to_claim,
                        }
                    )
                except Exception as _xe:
                    logger.warning(
                        f"[반품동기화][ESM] {label}: exchanges 조회 실패 — {_xe}"
                    )
                    _exchange_resp = {}

                try:
                    _return_resp = await _esm_client.search_returns(
                        {
                            "SiteType": _esm_claim_site_type,
                            "ReturnStatus": 0,
                            "Type": 2,
                            "StartDate": _esm_from_claim,
                            "EndDate": _esm_to_claim,
                        }
                    )
                except Exception as _rre:
                    logger.warning(
                        f"[반품동기화][ESM] {label}: returns 조회 실패 — {_rre}"
                    )
                    _return_resp = {}

                _cancel_items = (
                    _cancel_resp.get("Data") if isinstance(_cancel_resp, dict) else []
                ) or []
                _exchange_items = (
                    _exchange_resp.get("Data")
                    if isinstance(_exchange_resp, dict)
                    else []
                ) or []
                _return_items = (
                    _return_resp.get("Data") if isinstance(_return_resp, dict) else []
                ) or []

                _esm_synced = 0
                _esm_total = (
                    len(_cancel_items) + len(_exchange_items) + len(_return_items)
                )

                async def _esm_upsert_claim(
                    order_number: str,
                    return_type: str,
                    market_order_status: str,
                    status: str,
                    reason: str,
                    quantity: int,
                    product_name: str,
                ) -> int:
                    if not order_number:
                        return 0
                    existing_order = await order_repo.find_by_async(
                        order_number=order_number
                    )
                    if not existing_order:
                        logger.warning(
                            f"[반품동기화][ESM] {label}: 주문 미매칭 OrderNo={order_number}"
                        )
                        return 0
                    order_id = existing_order.id
                    existing_returns = await svc.repo.filter_by_async(
                        order_id=order_id, type=return_type
                    )
                    if existing_returns:
                        er = existing_returns[0]
                        patch: dict[str, Any] = {
                            "order_date": existing_order.paid_at
                            or existing_order.created_at,
                        }
                        if not er.product_image and existing_order.product_image:
                            patch["product_image"] = existing_order.product_image
                        if not er.market_order_status:
                            patch["market_order_status"] = market_order_status
                        status_priority = {
                            "requested": 0,
                            "approved": 1,
                            "completed": 2,
                            "rejected": 2,
                            "cancelled": 2,
                        }
                        if status_priority.get(status, 0) > status_priority.get(
                            er.status, 0
                        ):
                            patch["status"] = status
                            if status in ("completed", "rejected", "cancelled"):
                                patch["completion_date"] = _esm_dt.now(_esm_UTC)
                        if patch:
                            await svc.repo.update_async(er.id, **patch)
                    else:
                        await svc.repo.create_async(
                            order_id=order_id,
                            order_number=order_number,
                            type=return_type,
                            reason=reason or None,
                            quantity=quantity,
                            product_name=product_name or existing_order.product_name,
                            product_image=existing_order.product_image,
                            customer_name=existing_order.customer_name,
                            customer_phone=existing_order.customer_phone,
                            product_location=_extract_city_district(
                                existing_order.customer_address
                            ),
                            customer_address=existing_order.customer_address,
                            business_name=account.business_name
                            or account.market_name
                            or label,
                            market=_market_label,
                            market_order_status=market_order_status,
                            status=status,
                            timeline=[
                                {
                                    "date": _esm_dt.now(_esm_UTC).isoformat(),
                                    "status": status,
                                    "message": f"{return_type} 요청 접수",
                                }
                            ],
                            notes=[],
                        )
                    # 원주문 shipping_status 동기화
                    new_ss = market_order_status
                    if return_type == "exchange" and "교환" not in new_ss:
                        new_ss = "교환요청"
                    if return_type == "cancel" and "취소" not in new_ss:
                        new_ss = "취소요청"
                    if return_type == "return" and "반품" not in new_ss:
                        new_ss = "반품요청"
                    if existing_order.shipping_status != new_ss:
                        await order_repo.update_async(
                            existing_order.id, shipping_status=new_ss
                        )
                    return 1

                for _ci in _cancel_items:
                    if not isinstance(_ci, dict):
                        continue
                    _cs = int(_ci.get("CancelStatus") or 1)
                    _st, _mos = _cancel_status_map.get(_cs, ("requested", "취소요청"))
                    _esm_synced += await _esm_upsert_claim(
                        order_number=str(_ci.get("OrderNo") or ""),
                        return_type="cancel",
                        market_order_status=_mos,
                        status=_st,
                        reason=str(_ci.get("CancelReason") or _ci.get("Reason") or ""),
                        quantity=int(_ci.get("CancelQty") or _ci.get("OrderQty") or 1),
                        product_name=str(_ci.get("GoodsName") or ""),
                    )

                for _xi in _exchange_items:
                    if not isinstance(_xi, dict):
                        continue
                    _xs = int(_xi.get("ExchangeStatus") or 1)
                    _st, _mos = _exchange_status_map.get(_xs, ("requested", "교환요청"))
                    _esm_synced += await _esm_upsert_claim(
                        order_number=str(_xi.get("OrderNo") or ""),
                        return_type="exchange",
                        market_order_status=_mos,
                        status=_st,
                        reason=str(
                            _xi.get("ExchangeReason") or _xi.get("Reason") or ""
                        ),
                        quantity=int(
                            _xi.get("ExchangeQty") or _xi.get("OrderQty") or 1
                        ),
                        product_name=str(_xi.get("GoodsName") or ""),
                    )

                for _ri in _return_items:
                    if not isinstance(_ri, dict):
                        continue
                    _rs = int(_ri.get("ReturnStatus") or 1)
                    _st, _mos = _return_status_map.get(_rs, ("requested", "반품요청"))
                    _esm_synced += await _esm_upsert_claim(
                        order_number=str(_ri.get("OrderNo") or ""),
                        return_type="return",
                        market_order_status=_mos,
                        status=_st,
                        reason=str(_ri.get("ReturnReason") or _ri.get("Reason") or ""),
                        quantity=int(_ri.get("ReturnQty") or _ri.get("OrderQty") or 1),
                        product_name=str(_ri.get("GoodsName") or ""),
                    )

                total_synced += _esm_synced
                results.append(
                    {
                        "account": label,
                        "status": "success",
                        "fetched": _esm_total,
                        "synced": _esm_synced,
                    }
                )
                logger.info(
                    f"[반품동기화][ESM] {label}: cancels={len(_cancel_items)}, "
                    f"exchanges={len(_exchange_items)}, returns={len(_return_items)}, "
                    f"synced={_esm_synced}"
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

    # returns_sync 잡의 계정별 병렬 호출은 전역 후처리를 스킵한다(계정 수만큼
    # 반복 실행 = 락 경합/데드락 유발). 잡 핸들러가 모든 계정 완료 후 finalize 만
    # 1회 호출한다. run_finalize=True(기본)인 단일/전체 HTTP 호출은 아래로 진행.
    if not run_finalize:
        return {"total_synced": total_synced, "results": results}

    # 반품 레코드 정합 유지보수 — stale 종결(취소/반품/교환완료) + 중복 정리.
    # order_sync 잡 핸들러도 완료 후 동일 함수를 호출해 3시간 주기 중복 재생성을
    # 흡수한다(단일 소스 = returns/maintenance.py).
    from backend.domain.samba.returns.maintenance import (
        finalize_returns_consistency,
    )

    await finalize_returns_consistency(session)

    # DB 기반 원주문 shipping_status 일괄 동기화
    # samba_return 레코드가 있고 아직 진행 중인 주문의 shipping_status를 강제 업데이트
    try:
        from sqlalchemy import text as _sa_text

        await session.execute(
            _sa_text("""
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
                  '반품요청', '반품완료', '반품거부',
                  -- 취소 라벨 보호: 취소완료 주문에 stale 활성 samba_return 이 남아도
                  -- 반품/교환요청으로 덮지 않음 (issue #335, order.py:8132 와 동일 목록)
                  '취소요청', '취소처리중', '취소완료',
                  -- 송장/배송 진행 라벨도 좀비 return 으로 되돌리지 않음
                  '주문접수', '배송대기중', '송장전송완료', '국내배송중',
                  '배송완료', '구매확정'
              )
        """)
        )
        await session.commit()
        logger.info("[반품동기화] 원주문 shipping_status 일괄 업데이트 완료")
    except Exception as _upd_err:
        logger.warning(f"[반품동기화] 원주문 일괄 업데이트 실패: {_upd_err}")

    # 롯데ON API 버그 수정: clmRsnCd=300번대(반품 사유)가 교환으로 잘못 저장된 레코드 일괄 수정
    try:
        from sqlalchemy import text as _sa_text

        # 진단: 실제 저장된 값 확인
        _diag = await session.execute(
            _sa_text("""
            SELECT r.id, r.type, r.market, r.reason, r.market_order_status, o.order_number
            FROM samba_return r
            LEFT JOIN samba_order o ON o.id = r.order_id
            WHERE r.type = 'exchange'
              AND r.market ILIKE '%롯데%'
            LIMIT 20
        """)
        )
        _diag_rows = _diag.fetchall()
        if _diag_rows:
            logger.warning(
                "[반품동기화][진단] 롯데ON 교환 레코드 샘플: "
                + str(
                    [
                        (str(r[0])[:8], r[1], repr(r[2]), repr(r[3]), r[4], r[5])
                        for r in _diag_rows
                    ]
                )
            )
        else:
            logger.warning(
                "[반품동기화][진단] 롯데ON 교환 레코드 없음 (type=exchange AND market ILIKE '%롯데%')"
            )

        # 1단계: 연결된 원주문 shipping_status를 교환 상태에서 반품요청으로 수정
        # reason이 NULL이거나 2xx/3xx(반품 사유코드)인 경우 처리
        await session.execute(
            _sa_text("""
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
        """)
        )
        # 2단계: samba_return 타입 교환→반품 수정
        result_repair = await session.execute(
            _sa_text("""
            UPDATE samba_return
            SET type = 'return',
                market_order_status = '반품요청'
            WHERE type = 'exchange'
              AND market ILIKE '%롯데%'
              AND (reason ~ '^[23][0-9]+' OR reason IS NULL)
            RETURNING id, order_id, reason
        """)
        )
        repaired_rows = result_repair.fetchall()
        repaired = len(repaired_rows)
        if repaired > 0:
            logger.warning(
                f"[반품동기화] 롯데ON 교환→반품 재분류 수정: {repaired}건 "
                f"IDs={[str(r[0])[:8] for r in repaired_rows]}"
            )
        else:
            logger.warning("[반품동기화] 롯데ON 교환→반품 재분류 수정 대상 없음")
        await session.commit()
    except Exception as _repair_err:
        logger.warning(f"[반품동기화] 롯데ON 반품 재분류 수정 실패: {_repair_err}")

    # 마켓 API 동기화 후 samba_order 기반 백필 실행
    await _backfill_returns_from_claim_orders(session, tenant_id=tenant_id)

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

    update_fields: dict[str, Any] = {}

    if body.exchange_retrieval_status is not None:
        update_fields["exchange_retrieval_status"] = body.exchange_retrieval_status

    if body.exchange_retrieved_at is not None:
        from backend.utils import kst_iso_to_utc

        update_fields["exchange_retrieved_at"] = (
            kst_iso_to_utc(body.exchange_retrieved_at)
            if body.exchange_retrieved_at
            else None
        )

    if body.exchange_reship_company is not None:
        update_fields["exchange_reship_company"] = body.exchange_reship_company

    if body.exchange_reship_tracking is not None:
        update_fields["exchange_reship_tracking"] = body.exchange_reship_tracking

    if body.exchange_delivered_at is not None:
        from backend.utils import kst_iso_to_utc

        update_fields["exchange_delivered_at"] = (
            kst_iso_to_utc(body.exchange_delivered_at)
            if body.exchange_delivered_at
            else None
        )

    if not update_fields:
        return ret

    return await svc.repo.update_async(return_id, **update_fields)
