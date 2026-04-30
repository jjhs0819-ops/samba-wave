"""SambaWave Shipment API router."""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

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
    log_to_buffer: bool = False  # True: 상품전송삭제 페이지 링 버퍼에 기록


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


class CleanupOrphansRequest(BaseModel):
    # 화면 필터로 좁혀진 product_id 목록 — 비어있으면 tenant 전체 (호환)
    product_ids: Optional[list[str]] = None


@router.post("/smartstore/cleanup-orphans")
async def cleanup_smartstore_orphans(
    body: CleanupOrphansRequest = CleanupOrphansRequest(),
    dry_run: bool = Query(True, description="true면 목록만, false면 실제 삭제"),
    account_id: Optional[str] = Query(None, description="특정 계정만 정리"),
    max_delete: int = Query(50, ge=0, le=500, description="한 번에 삭제할 최대 개수"),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """스마트스토어 고아 상품 정리.

    DB `market_product_nos`에 없는 Naver 등록 상품을 탐지/삭제.
    최초 호출 시 dry_run=true로 목록 확인 후 dry_run=false로 실제 삭제.
    `body.product_ids`가 주어지면 화면 필터 결과만 분석 대상으로 한정한다.
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

    # 2. DB 상품 로드 — 화면 필터 product_ids 우선, 없으면 tenant_id 범위
    from sqlalchemy import or_

    tenant_ids = list({a.tenant_id for a in accounts if a.tenant_id})
    prod_query = select(SambaCollectedProduct)
    if body.product_ids:
        # 화면 필터 결과로 분석 범위 한정
        prod_query = prod_query.where(SambaCollectedProduct.id.in_(body.product_ids))
    elif tenant_ids:
        # 호환: 필터 없으면 tenant 전체 (멀티테넌시 도입 전 NULL 포함)
        prod_query = prod_query.where(
            or_(
                SambaCollectedProduct.tenant_id.in_(tenant_ids),
                SambaCollectedProduct.tenant_id.is_(None),
            )
        )
    prod_result = await session.exec(prod_query)
    all_db_products = prod_result.all()

    # 삼바가 등록한 상품 식별용 style_code 집합
    all_style_codes: set[str] = {
        str(p.style_code) for p in all_db_products if p.style_code
    }

    # 3. 각 계정별 Naver 조회 + 고아 판별
    per_account = []
    total_naver = 0
    total_orphans = 0
    total_stale_db = 0
    total_deleted = 0

    for account in accounts:
        add_info = account.additional_fields or {}
        client_id = add_info.get("clientId") or account.api_key or ""
        client_secret = add_info.get("clientSecret") or account.api_secret or ""
        if not client_id or not client_secret:
            per_account.append({"account_id": account.id, "error": "API 키 없음"})
            continue

        # 이 계정에 매핑된 product_no 수집 + DB product → originProductNo 역매핑
        account_db_nos: set[str] = set()
        # DB 상품 id → 매핑된 originProductNo (stale 판정용)
        db_origin_map: dict[str, dict] = {}
        for p in all_db_products:
            nos = p.market_product_nos or {}
            origin_no_for_p: str = ""
            for k in (account.id, f"{account.id}_origin"):
                v = nos.get(k)
                if isinstance(v, str) and v:
                    account_db_nos.add(v)
                    if not origin_no_for_p:
                        origin_no_for_p = v
                elif isinstance(v, dict):
                    for kk in (
                        "originProductNo",
                        "productNo",
                        "smartstoreChannelProductNo",
                    ):
                        vv = v.get(kk)
                        if vv:
                            account_db_nos.add(str(vv))
                            if not origin_no_for_p and kk == "originProductNo":
                                origin_no_for_p = str(vv)
            if origin_no_for_p:
                db_origin_map[origin_no_for_p] = {
                    "db_id": str(p.id),
                    "style_code": str(p.style_code or ""),
                    "mapped_origin_no": origin_no_for_p,
                    "product_name": (p.name or "")[:80],
                }

        client = SmartStoreClient(client_id, client_secret)

        # 페이징 수집 — 1페이지로 totalPages 파악 후 나머지 페이지 동시 조회
        # (순차 호출 시 8천개 기준 100s+ 소요 → Caddy 120s 타임아웃으로 502 발생)
        naver_products: list[dict] = []

        def _extract_contents(resp: object) -> list[dict]:
            if isinstance(resp, list):
                return resp
            if isinstance(resp, dict):
                v = resp.get("contents") or resp.get("data") or []
                return v if isinstance(v, list) else []
            return []

        r1 = await client._call_api(
            "POST",
            "/v1/products/search",
            body={"page": 1, "size": 100},
        )
        page1_contents = _extract_contents(r1)
        naver_products.extend(page1_contents)

        # 전체 페이지 수 확인 — totalPages 우선, 없으면 totalElements 기반 산출
        total_pages = 0
        if isinstance(r1, dict):
            tp = r1.get("totalPages")
            if isinstance(tp, int) and tp > 0:
                total_pages = tp
            else:
                te = r1.get("totalElements")
                if isinstance(te, int) and te > 0:
                    total_pages = (te + 99) // 100
        if total_pages <= 0:
            # 메타 정보 없으면 페이지가 가득 찼는지로 추정 (단일 페이지로 종료)
            total_pages = 1 if len(page1_contents) < 100 else 200
        total_pages = min(total_pages, 200)  # 20,000개 상한 유지

        # Naver Commerce API /products/search는 RPS 한도가 매우 낮아
        # sem=2도 36/99 페이지 실패 사고. 동시성 1(순차)로 낮추고 호출 사이
        # 강제 0.4s 간격(=최대 2.5 RPS) + 5회 재시도(2/4/8/16/32s 백오프).
        # 99페이지 × ~0.5s = ~50s, 200페이지 상한이어도 ~100s로 Caddy 120s 안전권.
        failed_pages: list[int] = []
        if total_pages > 1:
            sem = asyncio.Semaphore(1)

            async def _fetch_page(pno: int) -> tuple[int, list[dict], bool]:
                """returns (page_no, contents, success)."""
                last_err: Exception | None = None
                for attempt in range(5):
                    try:
                        async with sem:
                            rr = await client._call_api(
                                "POST",
                                "/v1/products/search",
                                body={"page": pno, "size": 100},
                            )
                            # 다음 호출까지 최소 간격 보장 (sem 보유 상태에서 sleep)
                            await asyncio.sleep(0.4)
                        return pno, _extract_contents(rr), True
                    except Exception as e:
                        last_err = e
                        err_msg = str(e)
                        # 429일 때만 길게 백오프, 그 외엔 짧게
                        if "429" in err_msg or "Too Many" in err_msg:
                            await asyncio.sleep(2 * (2**attempt))  # 2/4/8/16/32s
                        else:
                            await asyncio.sleep(0.5 * (2**attempt))  # 0.5/1/2/4/8s
                logger.warning(f"[고아정리] page {pno} 5회 재시도 실패: {last_err}")
                return pno, [], False

            results = await asyncio.gather(
                *[_fetch_page(p) for p in range(2, total_pages + 1)],
                return_exceptions=True,
            )
            for rr in results:
                if isinstance(rr, BaseException):
                    continue
                pno, contents, ok = rr
                if ok:
                    naver_products.extend(contents)
                else:
                    failed_pages.append(pno)

        total_naver += len(naver_products)

        # Naver 상품의 originProductNo / channelProductNo 전체 집합 (stale 역방향 판정용)
        account_naver_nos: set[str] = set()
        for np in naver_products:
            on = str(
                np.get("originProductNo")
                or np.get("originProduct", {}).get("id", "")
                or ""
            )
            if on:
                account_naver_nos.add(on)
            for cp in np.get("channelProducts", []):
                cn = cp.get("channelProductNo")
                if cn:
                    account_naver_nos.add(str(cn))

        orphans = []
        for np in naver_products:
            origin_no = str(np.get("originProductNo") or "")
            if not origin_no:
                continue

            channel_products = np.get("channelProducts", [])
            channel_nos = [
                str(cp.get("channelProductNo", ""))
                for cp in channel_products
                if cp.get("channelProductNo")
            ]
            # originProductNo / channelProductNo 직접 비교
            in_db = (origin_no in account_db_nos) or any(
                cn in account_db_nos for cn in channel_nos
            )
            # 구 등록 상품은 account_db_nos에 origin_no 미포함 → sellerManagementCode(=style_code)로 추가 확인
            if not in_db:
                mgmt_code = str(np.get("sellerManagementCode") or "")
                if mgmt_code and mgmt_code in all_style_codes:
                    in_db = True
            if not in_db:
                name = next(
                    (cp.get("name", "") for cp in channel_products if cp.get("name")),
                    "",
                )
                orphans.append({"origin_no": origin_no, "name": name[:80]})

        total_orphans += len(orphans)

        # DB→Naver 역고아: DB에 매핑은 있지만 Naver 목록에 없는 상품
        stale_db = [
            info
            for origin_no, info in db_origin_map.items()
            if origin_no not in account_naver_nos
        ]
        total_stale_db += len(stale_db)

        deleted_here: list[str] = []
        failed: list[dict] = []
        if not dry_run and orphans:
            # max_delete 한도 적용 + Naver 429 레이트리밋 대응
            # (직전 search 페이징 직후 delete 폭주 시 429 다발 → 33/50 실패 사례)
            remaining = max_delete - total_deleted
            if remaining > 0:
                for o in orphans[:remaining]:
                    last_err: str | None = None
                    for attempt in range(4):  # 최초 1회 + 재시도 3회
                        try:
                            await client.delete_product(o["origin_no"])
                            deleted_here.append(o["origin_no"])
                            last_err = None
                            break
                        except Exception as e:
                            err_msg = str(e)
                            last_err = err_msg
                            if "429" in err_msg and attempt < 3:
                                # 1s, 2s, 4s 지수 백오프 (총 7초까지)
                                await asyncio.sleep(2**attempt)
                                continue
                            break
                    if last_err is not None:
                        failed.append({"origin_no": o["origin_no"], "error": last_err})
                    # 다음 삭제 호출 사이 0.3초 간격 → RPS ≈ 3 (Naver 안전권)
                    await asyncio.sleep(0.3)
                total_deleted += len(deleted_here)

        per_account.append(
            {
                "account_id": account.id,
                "naver_count": len(naver_products),
                "orphan_count": len(orphans),
                "orphans": orphans,
                "stale_db_count": len(stale_db),
                "stale_db": stale_db[:50],
                "deleted": deleted_here,
                "failed": failed,
                "failed_pages": failed_pages,
                "total_pages": total_pages,
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "db_no_count": len(all_db_products),
        "style_code_count": len(all_style_codes),
        "total_stale_db": total_stale_db,
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
        log_to_buffer=body.log_to_buffer,
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
