"""스토어케어 API — 가구매 스케줄 + 이력."""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.store_care.repository import (
    StoreCareScheduleRepository,
    StoreCarePurchaseRepository,
    StoreCareMarketMetricRepository,
)
from backend.domain.samba.store_care.service import StoreCareService
from backend.domain.samba.tenant.middleware import get_current_tenant_id

router = APIRouter(prefix="/store-care", tags=["samba-store-care"])


def _svc(session: AsyncSession) -> StoreCareService:
    """세션으로부터 서비스 인스턴스 생성."""
    return StoreCareService(
        StoreCareScheduleRepository(session),
        StoreCarePurchaseRepository(session),
        StoreCareMarketMetricRepository(session),
    )


# ── 통계 ──


@router.get("/stats")
async def get_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """오늘 가구매 통계."""
    svc = _svc(session)
    return await svc.today_stats(tenant_id=tenant_id)


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
    tenant_id: str = Depends(get_current_tenant_id),
):
    """활성 스케줄 목록 조회."""
    svc = _svc(session)
    return await svc.list_schedules(tenant_id=tenant_id)


@router.post("/schedules", status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """스케줄 생성."""
    svc = _svc(session)
    data = body.model_dump()
    data["tenant_id"] = tenant_id
    return await svc.create_schedule(data)


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
    tenant_id: str = Depends(get_current_tenant_id),
):
    """최근 구매 이력 조회."""
    svc = _svc(session)
    return await svc.list_purchases(
        limit=limit, market_type=market_type, tenant_id=tenant_id
    )


# ── 마켓 점수·품절률 ──


class MetricsCollectRequest(BaseModel):
    markets: Optional[list] = None  # None이면 STORE_METRICS_URLS 전체 마켓


_OPTION_RANGE_MAX = 100  # 안전장치 — 범위 폭주 방지 (오타로 1~9999 등)


def _expand_option_range(option_str: Optional[str]) -> list[str]:
    """옵션 문자열을 개별 옵션값 리스트로 확장 (M2 다건/범위).

    - "1~30" / "1-30" → ["1","2",...,"30"] (숫자 범위)
    - "1,3,5"        → ["1","3","5"]       (개별 나열)
    - "1~5,10"       → ["1","2","3","4","5","10"]
    - "270"          → ["270"]             (단일)
    - "" / None      → []                  (옵션 없음 — 단순 담기)

    숫자 범위(양쪽 정수)만 확장 — "S-100" 같이 '-'가 든 리터럴 옵션값은 범위로
    오인하지 않고 단일 처리. 중복 제거 + 최대 _OPTION_RANGE_MAX 개 제한.
    """
    raw = (option_str or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        t = token.strip()
        if not t:
            continue
        m = re.match(r"^(\d+)\s*[~\-]\s*(\d+)$", t)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            for n in range(lo, hi + 1):
                s = str(n)
                if s not in seen:
                    seen.add(s)
                    out.append(s)
        elif t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= _OPTION_RANGE_MAX:
            break
    return out[:_OPTION_RANGE_MAX]


class PurchaseRunRequest(BaseModel):
    """가구매(셀프구매) 장바구니 담기 요청. M2=옵션 범위/다건 담기 지원."""

    market_type: str = "ssg"  # ssg / gsshop / 11st
    product_url: str  # 쇼핑몰 상품 페이지 URL
    option: Optional[str] = None  # 옵션값. 범위/다건 가능: "1~30", "1,3,5", "270"
    quantity: int = 1
    account_id: Optional[str] = (
        None  # 저장 소싱계정 id(자동로그인). 없으면 site 기본계정
    )


@router.get("/metrics")
async def list_market_metrics(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """마켓별 최신 점수·품절률 스냅샷."""
    svc = _svc(session)
    return await svc.list_market_metrics(tenant_id=tenant_id)


@router.post("/metrics/collect")
async def collect_market_metrics(
    request: Request,
    body: Optional[MetricsCollectRequest] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """마켓 점수·품절률 수집 트리거.

    X-Device-Id(버튼 누른 PC)의 확장앱이 로그인된 파트너/셀러 포털을 열어 스크래핑한다.
    결과는 POST /proxy/sourcing/store-metrics-result 로 비동기 수신되어 적재된다.
    """
    from backend.domain.samba.proxy.sourcing_queue import (
        STORE_METRICS_URLS,
        SourcingQueue,
    )

    trigger_device_id = (request.headers.get("X-Device-Id") or "").strip()
    if not trigger_device_id:
        raise HTTPException(400, "X-Device-Id 필요 — 확장앱이 설치된 PC에서 실행하세요")

    requested = [m.lower() for m in ((body.markets if body else None) or [])]
    markets = [
        m
        for m in (requested or list(STORE_METRICS_URLS.keys()))
        if m in STORE_METRICS_URLS
    ]
    if not markets:
        raise HTTPException(
            400, "수집 가능한 마켓이 없습니다 (STORE_METRICS_URLS 등록 마켓만 가능)"
        )

    enqueued: list[dict] = []
    for mt in markets:
        try:
            request_id, _ = await SourcingQueue.add_store_metrics_job(
                mt,
                owner_device_id=trigger_device_id,
                tenant_id=tenant_id,
            )
            enqueued.append({"market_type": mt, "request_id": request_id})
        except Exception as e:  # noqa: BLE001
            enqueued.append({"market_type": mt, "error": str(e)})

    return {"ok": True, "device_id": trigger_device_id, "enqueued": enqueued}


@router.get("/metrics/recommendations")
async def list_metric_recommendations(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """가) 부족분 계산 — 마켓별 목표 대비 '사야 할 구매 갯수'.

    전체 주문수(N)가 수집되면 자동 계산, 없으면 reason에 'N 필요' 표시.
    """
    svc = _svc(session)
    return await svc.list_recommendations(tenant_id=tenant_id)


@router.post("/purchase/run")
async def run_purchase(
    request: Request,
    body: PurchaseRunRequest,
    tenant_id: str = Depends(get_current_tenant_id),
):
    """가구매(셀프구매) 장바구니 담기 트리거 (M1 — 수동 1건).

    X-Device-Id(버튼 누른 PC)의 확장앱이 저장계정으로 자동로그인 후 상품페이지를 열어
    옵션 선택 + 장바구니 담기. 결과는 동기로 반환(확장앱 → /proxy/sourcing/purchase-result).
    결제(폰 QR)·일시품절 원복은 M3. (배치 다건은 추후 fire-and-forget + 폴링으로 전환)
    """
    import asyncio

    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

    trigger_device_id = (request.headers.get("X-Device-Id") or "").strip()
    if not trigger_device_id:
        raise HTTPException(400, "X-Device-Id 필요 — 확장앱이 설치된 PC에서 실행하세요")
    if not body.product_url:
        raise HTTPException(400, "product_url 필요")
    # URL 스킴 보강 — "gsshop.com/..." 처럼 http(s):// 없으면 붙임
    # (없으면 확장앱이 상대경로로 오인 → whale-extension://... ERR_FILE_NOT_FOUND)
    product_url = body.product_url.strip()
    if not product_url.lower().startswith(("http://", "https://")):
        product_url = "https://" + product_url.lstrip("/")

    options = _expand_option_range(body.option)
    request_id, future = await SourcingQueue.add_purchase_job(
        body.market_type or "ssg",
        owner_device_id=trigger_device_id,
        product_url=product_url,
        option=body.option or "",
        options=options,
        quantity=body.quantity or 1,
        sourcing_account_id=body.account_id or "",
        tenant_id=tenant_id,
    )
    # 옵션 다건 대기시간 가변. 11번가는 옵션마다 페이지 리로드(~8s/개)라 넉넉히, 나머지는 누적(~4s/개).
    _per = 8 if (body.market_type or "").lower() == "11st" else 4
    _timeout = min(300, 90 + len(options) * _per)
    try:
        result = await asyncio.wait_for(future, timeout=_timeout)
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "request_id": request_id,
            "error": "시간 초과 — 확장앱이 처리하지 못했습니다 (확장앱 연결/로그인 확인)",
        }
    return {
        "ok": bool(result.get("success")),
        "request_id": request_id,
        "option_count": len(options),
        "result": result,
    }


# ── 저장 상품 (가구매 북마크) — 이름으로 상품 URL 저장/불러오기 ──


class SavedProductCreate(BaseModel):
    name: str  # 표시 이름 (예: 신발끈)
    market_type: str = "ssg"
    product_url: str


@router.get("/purchase/products")
async def list_saved_products(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """저장된 가구매 상품 목록 (마켓별 북마크, 최신순)."""
    from backend.domain.samba.store_care.repository import (
        StoreCareSavedProductRepository,
    )

    repo = StoreCareSavedProductRepository(session)
    rows = await repo.list_by_tenant(tenant_id=tenant_id)
    return [
        {
            "id": r.id,
            "name": r.name,
            "market_type": r.market_type,
            "product_url": r.product_url,
        }
        for r in rows
    ]


@router.post("/purchase/products", status_code=201)
async def create_saved_product(
    body: SavedProductCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """가구매 상품 저장 (이름 + URL + 마켓)."""
    from backend.domain.samba.store_care.repository import (
        StoreCareSavedProductRepository,
    )

    name = (body.name or "").strip()
    url = (body.product_url or "").strip()
    if not name or not url:
        raise HTTPException(400, "이름과 상품 URL이 필요합니다")
    repo = StoreCareSavedProductRepository(session)
    row = await repo.create_async(
        tenant_id=tenant_id,
        name=name[:120],
        market_type=(body.market_type or "ssg").strip().lower(),
        product_url=url,
    )
    return {
        "id": row.id,
        "name": row.name,
        "market_type": row.market_type,
        "product_url": row.product_url,
    }


@router.delete("/purchase/products/{product_id}")
async def delete_saved_product(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """저장된 가구매 상품 삭제 (테넌트 소유 검증)."""
    from backend.domain.samba.store_care.repository import (
        StoreCareSavedProductRepository,
    )

    repo = StoreCareSavedProductRepository(session)
    row = await repo.get_async(product_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, "저장된 상품을 찾을 수 없습니다")
    await repo.delete_async(product_id)
    return {"ok": True}
