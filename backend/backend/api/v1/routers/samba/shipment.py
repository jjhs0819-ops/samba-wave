"""SambaWave Shipment API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tenant.middleware import get_optional_tenant_id, require_admin

router = APIRouter(prefix="/shipments", tags=["samba-shipments"])


class ShipmentStartRequest(BaseModel):
    product_ids: list[str]
    update_items: list[str]  # ['price', 'stock', 'image', 'description']
    target_account_ids: list[str]
    skip_unchanged: bool = False  # 가격 변동 없으면 스킵


class MarketDeleteRequest(BaseModel):
    product_ids: list[str]
    target_account_ids: list[str]
    current_idx: int | None = None  # 전체 삭제 중 현재 인덱스 (로그 표시용)
    total_count: int | None = None  # 전체 삭제 대상 수 (로그 표시용)


class MarketDeleteByAccountRequest(BaseModel):
    account_id: str
    dry_run: bool = False


def _get_service(session: AsyncSession):
    from backend.domain.samba.shipment.repository import SambaShipmentRepository
    from backend.domain.samba.shipment.service import SambaShipmentService

    return SambaShipmentService(SambaShipmentRepository(session), session)


class CancelRequest(BaseModel):
    job_id: Optional[str] = None


@router.post("/cancel")
async def cancel_transmit(body: CancelRequest = CancelRequest()):
    """진행 중인 전송 강제 중단. job_id가 주어지면 해당 잡만 취소."""
    from backend.domain.samba.shipment.service import request_cancel_transmit

    request_cancel_transmit(body.job_id)
    target = f"잡 {body.job_id}" if body.job_id else "전체"
    return {"ok": True, "message": f"전송 중단 요청 완료 ({target})"}


@router.post("/emergency-stop")
async def emergency_stop(
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """작업중지 — 전송 백그라운드 작업 즉시 중단 + pending/running Job 전부 취소 (오토튠 제외)."""
    from backend.domain.samba.emergency import trigger_emergency_stop
    from backend.domain.samba.shipment.service import request_cancel_transmit
    from sqlalchemy import text

    # 1. 비상정지 플래그 ON
    trigger_emergency_stop()
    # 2. 전송 취소 플래그
    request_cancel_transmit()
    # 3. pending/running Job 전부 취소
    r = await session.execute(
        text(
            "UPDATE samba_jobs SET status = 'cancelled', completed_at = now() WHERE status IN ('pending', 'running')"
        )
    )
    cancelled_count = r.rowcount
    await session.commit()

    # 플래그 해제하지 않음 — 워커가 감지 후 직접 해제
    return {
        "ok": True,
        "cancelled_jobs": cancelled_count,
        "message": "비상정지 완료",
    }


@router.post("/emergency-clear")
async def emergency_clear(admin: str = Depends(require_admin)):
    """비상정지 해제 — 전송/오토튠 재개 가능."""
    from backend.domain.samba.emergency import clear_emergency_stop
    from backend.domain.samba.shipment.service import clear_cancel_transmit

    clear_emergency_stop()
    clear_cancel_transmit()
    return {"ok": True, "message": "비상정지 해제"}


@router.post("/smartstore/cleanup-orphans")
async def cleanup_smartstore_orphans(
    dry_run: bool = Query(True, description="true면 목록만, false면 실제 삭제"),
    account_id: Optional[str] = Query(None, description="특정 계정만 정리"),
    max_delete: int = Query(50, ge=0, le=500, description="한 번에 삭제할 최대 개수"),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """스마트스토어 고아 상품 정리.

    DB `market_product_nos`에 없는 Naver 등록 상품을 탐지/삭제.
    최초 호출 시 dry_run=true로 목록 확인 후 dry_run=false로 실제 삭제.
    """
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.smartstore import SmartStoreClient

    # 1. 스마트스토어 계정 조회
    q = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "smartstore",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    if account_id:
        q = q.where(SambaMarketAccount.id == account_id)
    result = await session.exec(q)
    accounts = result.all()
    if not accounts:
        raise HTTPException(status_code=404, detail="활성 스마트스토어 계정 없음")

    # 2. DB에 기록된 모든 origin/channel product no 수집
    prod_result = await session.exec(
        select(SambaCollectedProduct).where(
            SambaCollectedProduct.market_product_nos.isnot(None)
        )
    )
    all_products = prod_result.all()
    db_nos: set[str] = set()
    for p in all_products:
        for k, v in (p.market_product_nos or {}).items():
            if isinstance(v, str) and v:
                db_nos.add(v)
            elif isinstance(v, dict):
                for kk in (
                    "originProductNo",
                    "productNo",
                    "smartstoreChannelProductNo",
                ):
                    vv = v.get(kk)
                    if vv:
                        db_nos.add(str(vv))

    # 3. 각 계정별 Naver 조회 + 고아 판별
    per_account = []
    total_naver = 0
    total_orphans = 0
    total_deleted = 0

    for account in accounts:
        add_info = account.additional_fields or {}
        client_id = add_info.get("clientId") or account.api_key or ""
        client_secret = add_info.get("clientSecret") or account.api_secret or ""
        if not client_id or not client_secret:
            per_account.append({"account_id": account.id, "error": "API 키 없음"})
            continue

        client = SmartStoreClient(client_id, client_secret)

        # 페이징 수집
        naver_products: list[dict] = []
        page = 1
        while True:
            r = await client._call_api(
                "POST",
                "/v1/products/search",
                body={"page": page, "size": 100},
            )
            contents = r.get("contents") or r.get("data") or []
            if isinstance(r, list):
                contents = r
            if not contents:
                break
            naver_products.extend(contents)
            if len(contents) < 100:
                break
            page += 1
            if page > 200:  # 20,000개 상한 — 무한루프 방지
                break

        total_naver += len(naver_products)

        orphans = []
        for np in naver_products:
            origin_no = str(
                np.get("originProductNo")
                or np.get("originProduct", {}).get("id", "")
                or ""
            )
            channel_nos = [
                str(cp.get("channelProductNo", ""))
                for cp in np.get("channelProducts", [])
                if cp.get("channelProductNo")
            ]
            in_db = (origin_no and origin_no in db_nos) or any(
                cn in db_nos for cn in channel_nos
            )
            if not in_db and origin_no:
                name = (
                    np.get("originProduct", {}).get("name") or np.get("name", "") or ""
                )
                orphans.append({"origin_no": origin_no, "name": name[:80]})

        total_orphans += len(orphans)

        deleted_here: list[str] = []
        failed: list[dict] = []
        if not dry_run and orphans:
            # max_delete 한도 적용
            remaining = max_delete - total_deleted
            if remaining <= 0:
                pass
            else:
                for o in orphans[:remaining]:
                    try:
                        await client.delete_product(o["origin_no"])
                        deleted_here.append(o["origin_no"])
                    except Exception as e:
                        failed.append({"origin_no": o["origin_no"], "error": str(e)})
                total_deleted += len(deleted_here)

        per_account.append(
            {
                "account_id": account.id,
                "naver_count": len(naver_products),
                "orphan_count": len(orphans),
                "orphans": orphans,
                "deleted": deleted_here,
                "failed": failed,
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "db_no_count": len(db_nos),
        "total_naver": total_naver,
        "total_orphans": total_orphans,
        "total_deleted": total_deleted,
        "max_delete": max_delete,
        "accounts": per_account,
    }


@router.get("")
async def list_shipments(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    from sqlmodel import select

    from backend.domain.samba.shipment.model import SambaShipment

    # tenant_id가 있으면 해당 테넌트 전송 이력만 조회
    if tenant_id is not None:
        stmt = (
            select(SambaShipment)
            .order_by(SambaShipment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                SambaShipment.tenant_id == tenant_id,
                SambaShipment.tenant_id == None,  # noqa: E711
            )
        )
        if status:
            stmt = stmt.where(SambaShipment.status == status)
        result = await session.execute(stmt)
        return result.scalars().all()
    svc = _get_service(session)
    return await svc.list_shipments(skip=skip, limit=limit, status=status)


@router.get("/product/{product_id}")
async def list_by_product(
    product_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _get_service(session).list_by_product(product_id)


@router.get("/{shipment_id}")
async def get_shipment(
    shipment_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    s = await svc.get_shipment(shipment_id)
    if not s:
        raise HTTPException(404, "전송 기록을 찾을 수 없습니다")
    return s


@router.post("/start", status_code=201)
async def start_shipment(
    body: ShipmentStartRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    result = await svc.start_update(
        body.product_ids,
        body.update_items,
        body.target_account_ids,
        skip_unchanged=body.skip_unchanged,
    )
    return result


@router.post("/market-delete")
async def market_delete(
    body: MarketDeleteRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """선택된 상품을 대상 마켓에서 판매중지/삭제."""
    svc = _get_service(session)
    return await svc.delete_from_markets(
        body.product_ids,
        body.target_account_ids,
        current_idx=body.current_idx,
        total_count=body.total_count,
    )


@router.post("/market-delete-by-account")
async def market_delete_by_account(
    body: MarketDeleteByAccountRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """특정 마켓 계정에 등록된 모든 상품을 마켓에서 삭제."""
    svc = _get_service(session)
    try:
        return await svc.delete_all_by_account(body.account_id, dry_run=body.dry_run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{shipment_id}/retry")
async def retry_shipment(
    shipment_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    result = await svc.retransmit(shipment_id)
    if not result:
        raise HTTPException(404, "전송 기록을 찾을 수 없습니다")
    return result


# ==================== 그룹상품 ====================


class GroupPreviewRequest(BaseModel):
    product_ids: list[str] = []
    search_filter_ids: list[str] = []
    account_id: str


class GroupPreviewProduct(BaseModel):
    id: str
    name: str
    color: Optional[str]
    sale_price: Optional[float]
    thumbnail: Optional[str]
    existing_product_no: Optional[str]


class GroupPreviewGroup(BaseModel):
    group_key: str
    group_name: str
    products: list[GroupPreviewProduct]


class GroupPreviewResponse(BaseModel):
    groups: list[GroupPreviewGroup]
    singles: list[GroupPreviewProduct]
    delete_count: int
    group_count: int
    single_count: int


@router.post("/group-preview")
async def group_preview(
    body: GroupPreviewRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """전송 대상 상품에서 그룹핑 가능한 상품을 감지하여 미리보기 반환."""
    from collections import defaultdict

    from backend.domain.samba.collector.grouping import group_products_by_key
    from backend.domain.samba.collector.repository import (
        SambaCollectedProductRepository,
    )

    repo = SambaCollectedProductRepository(session)
    products = []

    # search_filter_ids가 제공되면 해당 필터의 상품을 모두 조회
    product_ids = list(body.product_ids)
    if body.search_filter_ids:
        for sf_id in body.search_filter_ids:
            filter_products = await repo.filter_by_async(
                search_filter_id=sf_id, limit=10000
            )
            product_ids.extend([p.id for p in filter_products])

    for pid in product_ids:
        p = await repo.get_async(pid)
        if p:
            products.append(p.model_dump())

    # search_filter_id별로 분리 후 그룹핑 (다른 검색그룹끼리는 묶지 않음)
    by_filter: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        sf_id = p.get("search_filter_id") or "_none"
        by_filter[sf_id].append(p)

    all_groups: dict[str, list[dict]] = {}
    all_singles: list[dict] = []
    for sf_id, sf_products in by_filter.items():
        r = group_products_by_key(sf_products)
        all_groups.update(r["groups"])
        all_singles.extend(r["singles"])

    # 그룹별 미리보기 구성
    groups = []
    delete_count = 0
    for key, items in all_groups.items():
        first_name = items[0].get("name", "")
        group_name = (
            first_name.split(" - ", 1)[0].strip() if " - " in first_name else first_name
        )

        group_products = []
        for item in items:
            market_nos = item.get("market_product_nos") or {}
            existing_no = market_nos.get(body.account_id)
            if existing_no:
                if isinstance(existing_no, dict):
                    existing_no = str(existing_no.get("originProductNo", ""))
                else:
                    existing_no = str(existing_no)
                delete_count += 1
            else:
                existing_no = None
            item_images = item.get("images") or []
            group_products.append(
                GroupPreviewProduct(
                    id=item["id"],
                    name=item.get("name", ""),
                    color=item.get("color"),
                    sale_price=item.get("sale_price"),
                    thumbnail=item_images[0] if item_images else None,
                    existing_product_no=existing_no,
                )
            )
        groups.append(
            GroupPreviewGroup(
                group_key=key,
                group_name=group_name,
                products=group_products,
            )
        )

    singles = []
    for item in all_singles:
        item_images = item.get("images") or []
        market_nos = item.get("market_product_nos") or {}
        existing = market_nos.get(body.account_id)
        if existing and isinstance(existing, dict):
            existing = str(existing.get("originProductNo", ""))
        elif existing:
            existing = str(existing)
        else:
            existing = None
        singles.append(
            GroupPreviewProduct(
                id=item["id"],
                name=item.get("name", ""),
                color=item.get("color"),
                sale_price=item.get("sale_price"),
                thumbnail=item_images[0] if item_images else None,
                existing_product_no=existing,
            )
        )

    return GroupPreviewResponse(
        groups=groups,
        singles=singles,
        delete_count=delete_count,
        group_count=len(groups),
        single_count=len(singles),
    )


class GroupSendItem(BaseModel):
    group_key: str
    product_ids: list[str]


class GroupSendRequest(BaseModel):
    groups: list[GroupSendItem]
    singles: list[str]
    account_id: str


@router.post("/group-send")
async def group_send(
    body: GroupSendRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """그룹상품 + 단일상품 전송."""
    svc = _get_service(session)
    results = []

    # 1. 그룹상품 전송
    for group in body.groups:
        try:
            result = await svc.transmit_group(
                product_ids=group.product_ids,
                account_id=body.account_id,
            )
            results.append(
                {"group_key": group.group_key, "status": "success", **result}
            )
        except Exception as e:
            results.append(
                {"group_key": group.group_key, "status": "error", "error": str(e)}
            )

    # 2. 단일상품 전송 (기존 방식)
    single_results = {}
    if body.singles:
        single_results = await svc.start_update(
            product_ids=body.singles,
            update_items=["price", "stock", "image", "description"],
            target_account_ids=[body.account_id],
        )

    return {
        "group_results": results,
        "single_results": single_results,
    }
