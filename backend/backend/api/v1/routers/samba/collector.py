"""SambaWave Collector API router - 필터 CRUD + 수집 상품 CRUD."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.cache import cache
from backend.domain.user.auth_service import get_user_id
from backend.domain.samba.tenant.middleware import get_optional_tenant_id

from backend.api.v1.routers.samba.collector_common import (
    _HEAVY_FIELDS,
    _get_services,
    _invalidate_blacklist_cache,
)

router = APIRouter(prefix="/collector", tags=["samba-collector"])


def _all_options_sold_out(cp):
    """options JSON 배열의 모든 옵션이 stock <= 0인 조건 (sale_status 무관)."""
    from sqlalchemy import and_, text, cast, String

    return and_(
        cp.options.isnot(None),
        cast(cp.options, String) != "null",
        cast(cp.options, String) != "[]",
        text(
            "NOT EXISTS ("
            "  SELECT 1 FROM json_array_elements(options) AS elem"
            "  WHERE COALESCE((elem->>'stock')::int, 0) > 0"
            ")"
        ),
    )


# ── Inline DTOs (will be replaced by dtos/samba/collector.py when ready) ──


class SearchFilterCreate(BaseModel):
    source_site: str
    name: str
    keyword: Optional[str] = None
    category_filter: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    exclude_sold_out: bool = True
    requested_count: int = 100
    parent_id: Optional[str] = None
    is_folder: bool = False


class SearchFilterUpdate(BaseModel):
    name: Optional[str] = None
    keyword: Optional[str] = None
    category_filter: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    exclude_sold_out: Optional[bool] = None
    is_active: Optional[bool] = None
    requested_count: Optional[int] = None
    applied_policy_id: Optional[str] = None
    target_mappings: Optional[dict] = None


class CollectedProductCreate(BaseModel):
    source_site: str
    site_product_id: Optional[str] = None
    search_filter_id: Optional[str] = None
    name: str
    brand: Optional[str] = None
    original_price: float = 0
    sale_price: float = 0
    cost: Optional[float] = None
    images: Optional[list] = None
    options: Optional[list] = None
    category: Optional[str] = None
    category1: Optional[str] = None
    category2: Optional[str] = None
    category3: Optional[str] = None
    category4: Optional[str] = None
    status: str = "collected"


class CollectedProductUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    manufacturer: Optional[str] = None
    style_code: Optional[str] = None
    origin: Optional[str] = None
    sex: Optional[str] = None
    season: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    care_instructions: Optional[str] = None
    quality_guarantee: Optional[str] = None
    sale_price: Optional[float] = None
    cost: Optional[float] = None
    status: Optional[str] = None
    applied_policy_id: Optional[str] = None
    market_prices: Optional[dict] = None
    market_enabled: Optional[dict] = None
    is_sold_out: Optional[bool] = None
    sale_status: Optional[str] = None
    lock_delete: Optional[bool] = None
    lock_stock: Optional[bool] = None
    images: Optional[list] = None
    detail_images: Optional[list] = None
    tags: Optional[list] = None
    options: Optional[list] = None


class BulkCreateRequest(BaseModel):
    items: list[CollectedProductCreate]


class BulkProductIdsRequest(BaseModel):
    ids: list[str]


class BlockProductRequest(BaseModel):
    product_ids: list[str]


class FolderCreateRequest(BaseModel):
    source_site: str
    name: str
    parent_id: Optional[str] = None


class MoveFilterRequest(BaseModel):
    parent_id: Optional[str] = None


class BulkImageRemoveRequest(BaseModel):
    image_url: str
    field: str = "images"  # 하위호환
    fields: Optional[list[str]] = None  # ['images', 'detail_images'] 선택 가능


class BulkTagUpdateRequest(BaseModel):
    ids: list[str]
    tags: list[str] | None = None
    seo_keywords: list[str] | None = None


# ── Duplicate Detection ──


@router.get("/products/duplicates")
async def get_duplicate_products(
    request: Request,
    source_site: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    """마켓 등록 상품과 동일 원상품명인 중복 상품 그룹 반환."""
    svc = _get_services(session)
    groups = await svc.get_duplicate_products(
        tenant_id=tenant_id, source_site=source_site
    )
    return {"groups": groups, "total": len(groups)}


# ── Status / Health ──


@router.get("/proxy-status")
async def proxy_status():
    """프록시 서버 연결 상태 확인 — 백엔드 통합으로 항상 정상."""
    return {"status": "ok", "message": "프록시 서버 정상 작동 중 (백엔드 통합)"}


@router.get("/musinsa-auth-status")
async def musinsa_auth_status(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """무신사 인증 상태 확인."""
    from backend.domain.samba.forbidden.model import SambaSettings
    from sqlmodel import select

    try:
        result = await session.execute(
            select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
        )
        row = result.scalar_one_or_none()
        if row and row.value:
            return {"status": "ok", "message": "무신사 인증 완료"}
    except Exception as e:
        # DB 조회 실패 등 심각한 에러가 삼켜지지 않도록 로깅
        logger.error(f"[musinsa-auth-status] 인증 상태 조회 실패: {e}", exc_info=True)
    return {"status": "error", "message": "무신사 인증 필요"}


# ── Search Filters ──


@router.get("/filters")
async def list_filters(session: AsyncSession = Depends(get_write_session_dependency)):
    svc = _get_services(session)
    all_filters = await svc.list_filters(limit=10000)
    # 폴더 제외, 리프 그룹만 반환 (기존 호환성)
    filters = [f for f in all_filters if not f.is_folder]

    # 각 필터별 카운트를 단일 쿼리로 일괄 조회
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import func, case, and_, literal

    filter_ids = [f.id for f in filters]
    if not filter_ids:
        return []

    # 한 번의 GROUP BY 쿼리로 모든 카운트 산출
    from sqlalchemy import cast, String

    count_stmt = (
        select(
            _CP.search_filter_id,
            func.count().label("collected_count"),
            func.count(
                case(
                    (
                        and_(
                            _CP.registered_accounts != None,
                            cast(_CP.registered_accounts, String) != "null",
                            cast(_CP.registered_accounts, String) != "[]",
                            _CP.market_product_nos != None,
                            cast(_CP.market_product_nos, String) != "null",
                            cast(_CP.market_product_nos, String) != "{}",
                        ),
                        literal(1),
                    )
                )
            ).label("market_registered_count"),
            func.count(case((and_(_CP.applied_policy_id != None), literal(1)))).label(
                "policy_applied_count"
            ),
            func.count(
                case((and_(cast(_CP.tags, String).like("%__ai_tagged__%")), literal(1)))
            ).label("ai_tagged_count"),
            func.count(
                case((and_(cast(_CP.tags, String).like("%__ai_image__%")), literal(1)))
            ).label("ai_image_count"),
            func.count(
                case(
                    (
                        and_(
                            _CP.tags != None,
                            func.length(cast(_CP.tags, String))
                            > 20,  # 시스템태그만 있으면 짧음, 실제 태그 있으면 > 20
                            ~cast(_CP.tags, String).like("%[]%"),
                        ),
                        literal(1),
                    )
                )
            ).label("tag_applied_count"),
        )
        .where(_CP.search_filter_id.in_(filter_ids))
        .group_by(_CP.search_filter_id)
    )
    count_result = await session.execute(count_stmt)
    count_map = {}
    for row in count_result.all():
        count_map[row[0]] = {
            "collected_count": row[1],
            "market_registered_count": row[2],
            "policy_applied_count": row[3],
            "ai_tagged_count": row[4],
            "ai_image_count": row[5],
            "tag_applied_count": row[6],
        }

    result = []
    for f in filters:
        data = {c.key: getattr(f, c.key) for c in f.__table__.columns}
        counts = count_map.get(f.id, {})
        data["collected_count"] = counts.get("collected_count", 0)
        data["market_registered_count"] = counts.get("market_registered_count", 0)
        data["policy_applied_count"] = counts.get("policy_applied_count", 0)
        data["ai_tagged_count"] = counts.get("ai_tagged_count", 0)
        data["ai_image_count"] = counts.get("ai_image_count", 0)
        data["tag_applied_count"] = counts.get("tag_applied_count", 0)
        result.append(data)
    return result


@router.post("/filters", status_code=201)
async def create_filter(
    body: SearchFilterCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
    user_id: str = Depends(get_user_id),
):
    svc = _get_services(session)
    data = body.model_dump(exclude_unset=True)
    data["created_by"] = user_id
    return await svc.create_filter(data)


@router.put("/filters/{filter_id}")
async def update_filter(
    filter_id: str,
    body: SearchFilterUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    data = body.model_dump(exclude_unset=True)
    result = await svc.update_filter(filter_id, data)
    if not result:
        raise HTTPException(404, "필터를 찾을 수 없습니다")

    # 정책 적용 시 해당 그룹 상품에 백그라운드 전파 (즉시 응답)
    if "applied_policy_id" in data and data["applied_policy_id"]:
        policy_id = data["applied_policy_id"]

        async def _propagate():
            try:
                from backend.db.orm import get_write_session

                async with get_write_session() as bg_session:
                    from backend.domain.samba.policy.repository import (
                        SambaPolicyRepository,
                    )

                    policy_repo = SambaPolicyRepository(bg_session)
                    policy = await policy_repo.get_async(policy_id)
                    policy_data = None
                    if policy and policy.pricing:
                        pr = policy.pricing if isinstance(policy.pricing, dict) else {}
                        policy_data = {
                            "margin_rate": pr.get("marginRate", 15),
                            "shipping_cost": pr.get("shippingCost", 0),
                            "extra_charge": pr.get("extraCharge", 0),
                            "source_site_margins": pr.get("sourceSiteMargins", {}),
                        }
                    bg_svc = _get_services(bg_session)
                    count = await bg_svc.apply_policy_to_filter_products(
                        filter_id, policy_id, policy_data
                    )
                    await bg_session.commit()
                    logger.info(f"정책 전파 완료: 필터 {filter_id} → {count}개 상품")
            except Exception as e:
                logger.error(f"정책 전파 실패: 필터 {filter_id} → {e}")

        asyncio.create_task(_propagate())

    return result


@router.delete("/filters/{filter_id}")
async def delete_filter(
    filter_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    from sqlalchemy import delete as sa_delete
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP

    svc = _get_services(session)
    sf = await svc.filter_repo.get_async(filter_id)
    if not sf:
        raise HTTPException(404, "필터를 찾을 수 없습니다")

    # 마켓등록 상품 체크
    products = await svc.product_repo.list_by_filter(filter_id, limit=100000)
    registered = [
        p for p in products if p.registered_accounts and len(p.registered_accounts) > 0
    ]
    if registered:
        raise HTTPException(
            400, f"마켓등록 상품이 {len(registered)}건 있어서 삭제할 수 없습니다"
        )

    # 상품 벌크 삭제 → 그룹 삭제
    deleted_count = len(products)
    if products:
        await session.execute(sa_delete(_CP).where(_CP.search_filter_id == filter_id))
        logger.info(f"그룹 삭제: {filter_id} → 상품 {deleted_count}건 연동 삭제")

    await svc.delete_filter(filter_id)
    return {"ok": True, "deleted_products": deleted_count}


@router.delete("/products/orphans")
async def delete_orphan_products(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """그룹이 삭제되었지만 상품이 남은 고아 상품을 정리."""
    from sqlalchemy import select, delete as sa_delete, and_
    from backend.domain.samba.collector.model import (
        SambaCollectedProduct as _CP,
        SambaSearchFilter as _SF,
    )

    # search_filter_id가 있지만 해당 필터가 존재하지 않는 상품 조회
    existing_filter_ids = select(_SF.id)
    orphan_stmt = select(_CP.id, _CP.search_filter_id, _CP.registered_accounts).where(
        and_(
            _CP.search_filter_id != None,
            _CP.search_filter_id.notin_(existing_filter_ids),
        )
    )
    orphans = (await session.execute(orphan_stmt)).all()

    # 마켓등록 상품은 제외
    registered = [
        o for o in orphans if o.registered_accounts and len(o.registered_accounts) > 0
    ]
    deletable = [
        o
        for o in orphans
        if not o.registered_accounts or len(o.registered_accounts) == 0
    ]

    if deletable:
        del_ids = [o.id for o in deletable]
        await session.execute(sa_delete(_CP).where(_CP.id.in_(del_ids)))
        await session.commit()
        logger.info(
            f"고아 상품 정리: {len(deletable)}건 삭제 (마켓등록 {len(registered)}건 보존)"
        )

    return {
        "ok": True,
        "deleted": len(deletable),
        "preserved_registered": len(registered),
        "total_orphans_found": len(orphans),
    }


@router.get("/filters/tree")
async def get_filter_tree(session: AsyncSession = Depends(get_read_session_dependency)):
    """검색그룹 트리 구조 반환. 사이트 > 폴더 > 리프 그룹."""
    svc = _get_services(session)
    all_filters = await svc.list_filters(limit=10000)

    # 각 필터별 수집상품 카운트 — 단일 쿼리로 일괄 조회
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import func as _func

    leaf_ids = [f.id for f in all_filters if not f.is_folder]
    count_map: dict[str, int] = {}
    market_reg_map: dict[str, int] = {}
    ai_tag_map: dict[str, int] = {}
    tag_applied_map: dict[str, int] = {}
    if leaf_ids:
        from sqlalchemy import case, and_, cast, String, literal

        count_stmt = (
            select(
                _CP.search_filter_id,
                _func.count().label("cnt"),
                _func.count(
                    case(
                        (
                            and_(
                                _CP.registered_accounts != None,
                                cast(_CP.registered_accounts, String) != "null",
                                cast(_CP.registered_accounts, String) != "[]",
                                _CP.market_product_nos != None,
                                cast(_CP.market_product_nos, String) != "null",
                                cast(_CP.market_product_nos, String) != "{}",
                            ),
                            literal(1),
                        )
                    )
                ).label("market_registered"),
                _func.count(
                    case(
                        (
                            and_(cast(_CP.tags, String).like("%__ai_tagged__%")),
                            literal(1),
                        )
                    )
                ).label("ai_tagged"),
                _func.count(
                    case(
                        (
                            and_(
                                _CP.tags != None,
                                _func.length(cast(_CP.tags, String)) > 20,
                                ~cast(_CP.tags, String).like("%[]%"),
                            ),
                            literal(1),
                        )
                    )
                ).label("tag_applied"),
            )
            .where(_CP.search_filter_id.in_(leaf_ids))
            .group_by(_CP.search_filter_id)
        )
        count_result = await session.execute(count_stmt)
        for row in count_result.all():
            count_map[row[0]] = row[1]
            market_reg_map[row[0]] = row[2]
            ai_tag_map[row[0]] = row[3]
            tag_applied_map[row[0]] = row[4]

    filter_data = []
    for f in all_filters:
        data = {c.key: getattr(f, c.key) for c in f.__table__.columns}
        data["collected_count"] = count_map.get(f.id, 0) if not f.is_folder else 0
        data["market_registered_count"] = (
            market_reg_map.get(f.id, 0) if not f.is_folder else 0
        )
        data["ai_tagged_count"] = ai_tag_map.get(f.id, 0) if not f.is_folder else 0
        data["tag_applied_count"] = (
            tag_applied_map.get(f.id, 0) if not f.is_folder else 0
        )
        filter_data.append(data)

    # 트리 빌드: parent_id 기반 + 고아 노드 source_site별 자동 그룹핑
    by_id = {f["id"]: f for f in filter_data}
    roots = []
    orphans_by_site: dict[str, list] = {}
    for f in filter_data:
        f["children"] = []
    for f in filter_data:
        pid = f.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(f)
        elif not pid:
            # 폴더는 루트, 비폴더(리프)는 source_site별 가상 폴더로
            if f.get("is_folder"):
                roots.append(f)
            else:
                site = f.get("source_site") or "기타"
                orphans_by_site.setdefault(site, []).append(f)

    # 가상 사이트 폴더 생성 (기존 폴더와 병합)
    existing_site_folders = {r["source_site"]: r for r in roots if r.get("is_folder")}
    for site, orphans in orphans_by_site.items():
        if site in existing_site_folders:
            # 기존 사이트 폴더에 고아 노드 추가
            existing_site_folders[site]["children"].extend(orphans)
        else:
            # 가상 사이트 폴더 생성
            virtual = {
                "id": f"__virtual_{site}",
                "source_site": site,
                "name": site,
                "is_folder": True,
                "children": orphans,
                "collected_count": 0,
            }
            roots.append(virtual)

    return roots


@router.post("/filters/folder", status_code=201)
async def create_folder(
    body: FolderCreateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """폴더(분류) 노드 생성."""
    svc = _get_services(session)
    data = {
        "source_site": body.source_site,
        "name": body.name,
        "parent_id": body.parent_id,
        "is_folder": True,
        "requested_count": 0,
    }
    return await svc.create_filter(data)


@router.patch("/filters/{filter_id}/move")
async def move_filter(
    filter_id: str,
    body: MoveFilterRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """필터/폴더를 다른 폴더로 이동."""
    svc = _get_services(session)
    result = await svc.update_filter(filter_id, {"parent_id": body.parent_id})
    if not result:
        raise HTTPException(404, "필터를 찾을 수 없습니다")
    return result


# ── Collected Products ──


@router.get("/products/scroll")
async def scroll_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=10000),
    search: str = Query("", max_length=200),
    search_type: str = Query("name"),
    source_site: Optional[str] = None,
    status: Optional[str] = None,
    ai_filter: Optional[str] = None,
    search_filter_id: Optional[str] = None,
    sort_by: str = Query("collect-desc"),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """서버사이드 필터/정렬/페이지네이션 — 무한스크롤용.

    Returns: {items: [...], total: int, sites: [str]}
    """
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import (
        func,
        cast,
        String,
        and_,
        text,
        select,
        inspect as _sa_inspect,
    )

    mapper = _sa_inspect(_CP)

    # 기본 조건
    conditions = []

    # 텍스트 검색
    q = search.strip()
    if q:
        if search_type == "name":
            # 원상품명 + 등록상품명 + 마켓등록명 통합 부분 일치 (공백 무시)
            q_no_space = q.replace(" ", "")
            conditions.append(
                or_(
                    _CP.name.ilike(f"%{q}%"),
                    func.replace(_CP.name, " ", "").ilike(f"%{q_no_space}%"),
                    _CP.name_en.ilike(f"%{q}%"),
                    func.replace(func.coalesce(_CP.name_en, ""), " ", "").ilike(
                        f"%{q_no_space}%"
                    ),
                    func.coalesce(cast(_CP.market_names, String), "").ilike(f"%{q}%"),
                    func.coalesce(_CP.brand, "").ilike(f"%{q}%"),
                    func.coalesce(_CP.style_code, "").ilike(f"%{q}%"),
                    _CP.site_product_id.ilike(f"%{q}%"),
                )
            )
        elif search_type == "name_all":
            # 상품명 + 등록상품명 구성 요소(brand/style_code/site_product_id 포함) 동시 검색
            # composeProductName()이 조합하는 모든 필드를 커버해야 등록명 내 모델코드 검색이 동작함
            q_no_space = q.replace(" ", "")
            conditions.append(
                or_(
                    _CP.name.ilike(f"%{q}%"),
                    func.replace(_CP.name, " ", "").ilike(f"%{q_no_space}%"),
                    _CP.name_en.ilike(f"%{q}%"),
                    func.replace(func.coalesce(_CP.name_en, ""), " ", "").ilike(
                        f"%{q_no_space}%"
                    ),
                    func.coalesce(_CP.brand, "").ilike(f"%{q}%"),
                    func.coalesce(_CP.style_code, "").ilike(f"%{q}%"),
                    _CP.site_product_id.ilike(f"%{q}%"),
                )
            )
        elif search_type == "no":
            conditions.append(_CP.site_product_id.ilike(f"%{q}%"))
        elif search_type == "filter":
            # 검색필터 이름으로 검색 → search_filter_id 서브쿼리
            from backend.domain.samba.collector.model import SambaSearchFilter as _SF

            sf_ids = select(_SF.id).where(_SF.name.ilike(f"%{q}%"))
            conditions.append(_CP.search_filter_id.in_(sf_ids))
        elif search_type == "brand":
            conditions.append(_CP.brand.ilike(f"%{q}%"))
        elif search_type == "id":
            conditions.append(_CP.id == q)
        elif search_type == "policy":
            from backend.domain.samba.policy.model import SambaPolicy as _POL

            pol_ids = select(_POL.id).where(_POL.name.ilike(f"%{q}%"))
            conditions.append(_CP.applied_policy_id.in_(pol_ids))

    # 소싱처 필터
    if source_site:
        conditions.append(_CP.source_site == source_site)

    # 그룹(검색필터) 필터
    if search_filter_id:
        conditions.append(_CP.search_filter_id == search_filter_id)

    # 상태 필터
    # ※ "market_registered/market_unregistered"는 registered_accounts(실제 마켓 등록 계정) 기준
    #    "registered/collected/saved"는 상품 처리 상태(status 컬럼) 기준 — 혼동 주의
    _KNOWN_STATUS_VALUES = {"collected", "saved", "registered"}
    if status == "has_orders":
        from backend.api.v1.routers.samba.collector_common import (
            build_has_orders_conditions,
        )

        conditions.extend(await build_has_orders_conditions(session, _CP))
    elif status == "free_ship":
        conditions.append(_CP.free_shipping == True)
    elif status == "same_day":
        conditions.append(_CP.same_day_delivery == True)
    elif status == "free_same":
        conditions.append(_CP.free_shipping == True)
        conditions.append(_CP.same_day_delivery == True)
    elif status == "market_registered":
        # 마켓등록상품 공통 조건 (registered_accounts + market_product_nos)
        from backend.api.v1.routers.samba.collector_common import (
            build_market_registered_conditions,
        )

        conditions.extend(build_market_registered_conditions(_CP))
    elif status == "market_unregistered":
        # 마켓 미등록 상품: registered_accounts가 null이거나 빈 배열
        conditions.append(
            or_(
                _CP.registered_accounts.is_(None),
                cast(_CP.registered_accounts, String) == "null",
                cast(_CP.registered_accounts, String) == "[]",
            )
        )
    elif status == "sold_out":
        conditions.append(
            or_(_CP.sale_status == "sold_out", _all_options_sold_out(_CP))
        )
    elif status and status.startswith("mtype_reg_"):
        # 마켓타입별 등록 필터: 해당 마켓타입의 계정 중 하나라도 등록된 상품
        market_type = status[10:]
        from backend.domain.samba.account.model import SambaMarketAccount as _MA

        acc_result = await session.execute(
            select(_MA.id).where(_MA.market_type == market_type, _MA.is_active == True)
        )
        acc_ids = acc_result.scalars().all()
        if acc_ids:
            conditions.append(
                or_(
                    *[
                        cast(_CP.registered_accounts, String).like(f'%"{aid}"%')
                        for aid in acc_ids
                    ]
                )
            )
        else:
            conditions.append(text("1=0"))
    elif status and status.startswith("mtype_unreg_"):
        # 마켓타입별 미등록 필터: 해당 마켓타입의 계정이 하나도 등록되지 않은 상품
        market_type = status[12:]
        from backend.domain.samba.account.model import SambaMarketAccount as _MA

        acc_result = await session.execute(
            select(_MA.id).where(_MA.market_type == market_type, _MA.is_active == True)
        )
        acc_ids = acc_result.scalars().all()
        if acc_ids:
            conditions.append(
                or_(
                    _CP.registered_accounts.is_(None),
                    cast(_CP.registered_accounts, String) == "null",
                    cast(_CP.registered_accounts, String) == "[]",
                    and_(
                        *[
                            ~cast(_CP.registered_accounts, String).like(f'%"{aid}"%')
                            for aid in acc_ids
                        ]
                    ),
                )
            )
    elif status and status.startswith("reg_"):
        # 특정 계정에 등록된 상품: registered_accounts JSON에 account_id 포함
        account_id = status[4:]  # "reg_ma_xxx" → "ma_xxx"
        conditions.append(
            cast(_CP.registered_accounts, String).like(f'%"{account_id}"%')
        )
    elif status and status.startswith("unreg_"):
        # 특정 계정에 미등록된 상품: registered_accounts에 account_id 미포함
        account_id = status[6:]  # "unreg_ma_xxx" → "ma_xxx"
        conditions.append(
            or_(
                _CP.registered_accounts.is_(None),
                cast(_CP.registered_accounts, String) == "null",
                cast(_CP.registered_accounts, String) == "[]",
                ~cast(_CP.registered_accounts, String).like(f'%"{account_id}"%'),
            )
        )
    elif status and status in _KNOWN_STATUS_VALUES:
        conditions.append(_CP.status == status)

    # AI 필터 (JSON 태그/이미지 패턴)
    if ai_filter == "sold_out":
        conditions.append(
            or_(_CP.sale_status == "sold_out", _all_options_sold_out(_CP))
        )
    elif ai_filter == "ai_tag_yes":
        conditions.append(cast(_CP.tags, String).like('%"__ai_tagged__"%'))
    elif ai_filter == "ai_tag_no":
        conditions.append(
            or_(
                _CP.tags.is_(None),
                ~cast(_CP.tags, String).like('%"__ai_tagged__"%'),
            )
        )
    elif ai_filter == "ai_img_yes":
        conditions.append(cast(_CP.tags, String).like('%"__ai_image__"%'))
    elif ai_filter == "ai_img_no":
        conditions.append(
            or_(
                _CP.tags.is_(None),
                ~cast(_CP.tags, String).like('%"__ai_image__"%'),
            )
        )
    elif ai_filter == "filter_yes":
        conditions.append(cast(_CP.tags, String).like('%"__img_filtered__"%'))
    elif ai_filter == "filter_no":
        conditions.append(
            or_(
                _CP.tags.is_(None),
                ~cast(_CP.tags, String).like('%"__img_filtered__"%'),
            )
        )
    elif ai_filter == "img_edit_yes":
        conditions.append(cast(_CP.tags, String).like('%"__img_edited__"%'))
    elif ai_filter == "img_edit_no":
        conditions.append(
            or_(
                _CP.tags.is_(None),
                ~cast(_CP.tags, String).like('%"__img_edited__"%'),
            )
        )
    elif ai_filter == "video_yes":
        conditions.append(_CP.video_url.isnot(None))
        conditions.append(_CP.video_url != "")
    elif ai_filter == "video_no":
        conditions.append(or_(_CP.video_url.is_(None), _CP.video_url == ""))
    elif ai_filter == "has_orders":
        from backend.api.v1.routers.samba.collector_common import (
            build_has_orders_conditions,
        )

        conditions.extend(await build_has_orders_conditions(session, _CP))

    # 목록에 필요한 컬럼 선택 (heavy 필드만 제외)
    list_cols = [c for c in mapper.columns if c.key not in _HEAVY_FIELDS]

    # COUNT + 데이터 + 소싱처 + KPI 병렬 실행
    count_stmt = select(func.count()).select_from(_CP)
    for c in conditions:
        count_stmt = count_stmt.where(c)

    # 소싱처 목록 (캐시 TTL 5분)
    sites = await cache.get("products:sites")
    sites_task = None
    if not sites:
        sites_stmt = (
            select(_CP.source_site).distinct().where(_CP.source_site.isnot(None))
        )
        sites_task = session.execute(sites_stmt)

    # KPI 카운트 (캐시 TTL 30초)
    counts = await cache.get("products:counts")
    counts_task = None
    if not counts:
        from sqlalchemy import case, literal

        counts_stmt = select(
            func.count().label("total"),
            func.count(case((_CP.status == "registered", literal(1)))).label(
                "registered"
            ),
            func.count(case((_CP.applied_policy_id != None, literal(1)))).label(
                "policy_applied"
            ),
            func.count(
                case(
                    (
                        or_(
                            _CP.sale_status == "sold_out",
                            _all_options_sold_out(_CP),
                        ),
                        literal(1),
                    )
                )
            ).label("sold_out"),
        ).select_from(_CP)
        counts_task = session.execute(counts_stmt)

    # 데이터 쿼리
    data_stmt = select(*list_cols)
    for c in conditions:
        data_stmt = data_stmt.where(c)

    # 정렬
    if sort_by == "collect-asc":
        data_stmt = data_stmt.order_by(_CP.created_at.asc())
    elif sort_by == "update-desc":
        data_stmt = data_stmt.order_by(
            _CP.updated_at.desc().nullslast(), _CP.created_at.desc()
        )
    elif sort_by == "update-asc":
        data_stmt = data_stmt.order_by(
            _CP.updated_at.asc().nullsfirst(), _CP.created_at.asc()
        )
    else:
        data_stmt = data_stmt.order_by(_CP.created_at.desc())

    data_stmt = data_stmt.offset(skip).limit(limit)

    # 순차 실행 (같은 세션에서 asyncio.gather 사용 시 asyncpg 충돌 방지)
    count_result = await session.execute(count_stmt)
    total = count_result.scalar() or 0

    data_result = await session.execute(data_stmt)
    rows = data_result.mappings().all()

    # 사이트/카운트 결과 수집
    if sites_task:
        sites_result = await sites_task
        sites = sorted([r[0] for r in sites_result.all() if r[0]])
        await cache.set("products:sites", sites, ttl=300)
    if counts_task:
        counts_row = (await counts_task).one()
        counts = {
            "total": counts_row.total,
            "registered": counts_row.registered,
            "policy_applied": counts_row.policy_applied,
            "sold_out": counts_row.sold_out,
        }
        await cache.set("products:counts", counts, ttl=30)

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "sites": sites,
        "counts": counts
        or {"total": 0, "registered": 0, "policy_applied": 0, "sold_out": 0},
    }


@router.get("/products/init-data")
async def products_init_data(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """상품관리 페이지 초기 데이터 통합 API — 8개 API를 1개로 병합.

    Returns: { policies, filters, deletion_words, accounts, order_product_ids,
               name_rules, category_mappings, detail_templates }
    각 섹션이 독립적으로 try/except 처리 — 부분 실패 시에도 나머지 데이터 반환.
    """
    from backend.domain.samba.policy.model import SambaPolicy
    from backend.domain.samba.collector.model import SambaSearchFilter as _SF
    from backend.domain.samba.forbidden.model import SambaForbiddenWord
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.order.model import SambaOrder
    from backend.domain.samba.category.model import SambaCategoryMapping

    # SQLModel 인스턴스를 dict로 변환
    def to_dict(obj):
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "__dict__"):
            d = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
            return d
        return obj

    # 기본값 초기화 (각 섹션 실패 시 빈 배열 반환)
    policies: list = []
    filters: list = []
    words: list = []
    accounts: list = []
    mappings: list = []
    order_pids: list = []
    rules: list = []
    templates: list = []

    # 1차: 핵심 메타데이터 (정책/필터/금지어/계정/카테고리) 병렬 조회
    try:
        core_results = await asyncio.gather(
            session.execute(select(SambaPolicy).limit(50)),
            session.execute(select(_SF).where(_SF.is_folder == False).limit(500)),
            session.execute(
                select(SambaForbiddenWord).where(
                    SambaForbiddenWord.type == "deletion",
                    SambaForbiddenWord.is_active == True,
                )
            ),
            session.execute(
                select(SambaMarketAccount).where(SambaMarketAccount.is_active == True)
            ),
            session.execute(select(SambaCategoryMapping)),
        )
        pol_r, filter_r, words_r, accs_r, map_r = core_results
        policies = [to_dict(r) for r in pol_r.scalars().all()]
        filters = [to_dict(r) for r in filter_r.scalars().all()]
        words = [r.word for r in words_r.scalars().all()]
        accounts = [to_dict(r) for r in accs_r.scalars().all()]
        mappings = [to_dict(r) for r in map_r.scalars().all()]
    except Exception as e:
        logger.exception(f"[init-data] 핵심 메타데이터 조회 실패: {e}")

    # 2차: order_pids (캐시 우선, 주문 테이블 풀 스캔 방지 — 30초 TTL)
    try:
        order_pids = await cache.get("init_data:order_pids") or []
        if not order_pids:
            order_r = await session.execute(
                select(SambaOrder.product_id)
                .where(SambaOrder.product_id.isnot(None))
                .distinct()
            )
            order_pids = [r[0] for r in order_r.all()]
            await cache.set("init_data:order_pids", order_pids, ttl=30)
    except Exception as e:
        logger.exception(f"[init-data] order_pids 조회 실패: {e}")

    # 3차: name_rules + detail_templates (policy 도메인)
    try:
        from backend.domain.samba.policy.model import SambaNameRule, SambaDetailTemplate

        rules_r, tpl_r = await asyncio.gather(
            session.execute(select(SambaNameRule)),
            session.execute(select(SambaDetailTemplate)),
        )
        rules = [to_dict(r) for r in rules_r.scalars().all()]
        templates = [to_dict(r) for r in tpl_r.scalars().all()]
    except Exception as e:
        logger.exception(f"[init-data] name_rules/detail_templates 조회 실패: {e}")

    return {
        "policies": policies,
        "filters": filters,
        "deletion_words": words,
        "accounts": accounts,
        "order_product_ids": order_pids,
        "name_rules": rules,
        "category_mappings": mappings,
        "detail_templates": templates,
    }


@router.get("/products/counts")
async def product_counts(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """상품 카운트 통계 (대시보드용) — 10만건이어도 즉시 응답."""
    # 캐시 조회 (TTL 30초)
    cached = await cache.get("products:counts")
    if cached:
        return cached

    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import func, case, literal

    stmt = select(
        func.count().label("total"),
        func.count(case((_CP.registered_accounts != None, literal(1)))).label(
            "registered"
        ),
        func.count(case((_CP.applied_policy_id != None, literal(1)))).label(
            "policy_applied"
        ),
        func.count(
            case(
                (
                    or_(
                        _CP.sale_status == "sold_out",
                        _all_options_sold_out(_CP),
                    ),
                    literal(1),
                )
            )
        ).label("sold_out"),
    ).select_from(_CP)
    row = (await session.execute(stmt)).one()
    result = {
        "total": row.total,
        "registered": row.registered,
        "policy_applied": row.policy_applied,
        "sold_out": row.sold_out,
    }
    await cache.set("products:counts", result, ttl=30)
    return result


@router.get("/products/dashboard-stats")
async def product_dashboard_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """대시보드 현황판 — 소싱처별 수집현황 + 마켓/계정별 등록현황."""
    cached = await cache.get("products:dashboard-stats")
    if cached:
        return cached

    from backend.domain.samba.account.model import SambaMarketAccount as _MA
    from sqlalchemy import text

    # 1) 소싱처별 수집현황 — raw SQL로 json/jsonb 호환
    site_stmt = text("""
        SELECT source_site,
               COUNT(*) AS total,
               COUNT(*) FILTER (
                   WHERE registered_accounts IS NOT NULL
                     AND registered_accounts::text != 'null'
                     AND registered_accounts::text != '[]'
               ) AS registered,
               COUNT(*) FILTER (WHERE sale_status = 'sold_out') AS sold_out
        FROM samba_collected_product
        WHERE source_site IS NOT NULL AND source_site != ''
        GROUP BY source_site
        ORDER BY total DESC
    """)
    site_rows = (await session.execute(site_stmt)).all()
    by_source = [
        {
            "source_site": r.source_site,
            "total": r.total,
            "registered": r.registered,
            "sold_out": r.sold_out,
        }
        for r in site_rows
    ]

    # 2) 마켓/계정별 등록현황 — jsonb_array_elements_text 사용 (cast로 호환)
    by_account: list[dict] = []
    try:
        acct_stmt = text("""
            SELECT aid, COUNT(*) AS cnt
            FROM (
                SELECT jsonb_array_elements_text(registered_accounts::jsonb) AS aid
                FROM samba_collected_product
                WHERE registered_accounts IS NOT NULL
                  AND registered_accounts::text != 'null'
                  AND registered_accounts::text != '[]'
            ) sub
            GROUP BY aid
            ORDER BY cnt DESC
        """)
        acct_rows = (await session.execute(acct_stmt)).all()

        # 계정 ID → 마켓명/계정라벨 매핑
        acct_ids = [r.aid for r in acct_rows]
        acct_map: dict[str, dict[str, str]] = {}
        if acct_ids:
            ma_stmt = select(_MA.id, _MA.market_name, _MA.account_label).where(
                _MA.id.in_(acct_ids)
            )
            ma_rows = (await session.execute(ma_stmt)).all()
            for m in ma_rows:
                acct_map[m.id] = {
                    "market_name": m.market_name,
                    "account_label": m.account_label,
                }

        by_account = [
            {
                "account_id": r.aid,
                "market_name": acct_map.get(r.aid, {}).get("market_name", "알 수 없음"),
                "account_label": acct_map.get(r.aid, {}).get("account_label", ""),
                "registered": r.cnt,
            }
            for r in acct_rows
        ]
    except Exception as e:
        logger.warning("대시보드 계정별 통계 조회 실패: %s", e)
        by_account = []

    result = {"by_source": by_source, "by_account": by_account}
    await cache.set("products:dashboard-stats", result, ttl=60)
    return result


@router.get("/products/category-tree")
async def product_category_tree(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """소싱처별 카테고리 트리 (카테고리매핑용) — 상품 전체 로드 없이 GROUP BY."""
    # 캐시 조회 (TTL 5분)
    cached = await cache.get("products:category-tree")
    if cached:
        return cached

    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import func

    stmt = (
        select(
            _CP.source_site,
            _CP.category,
            func.count().label("cnt"),
        )
        .where(
            _CP.source_site != None,
            _CP.category != None,
            _CP.category != "",
            # fallback 카테고리 제외 (category가 source_site와 동일한 경우)
            _CP.category != _CP.source_site,
        )
        .group_by(_CP.source_site, _CP.category)
        .order_by(_CP.source_site, _CP.category)
    )
    rows = (await session.execute(stmt)).all()
    result = [{"source_site": r[0], "category": r[1], "count": r[2]} for r in rows]
    await cache.set("products:category-tree", result, ttl=300)
    return result


@router.get("/products")
async def list_collected_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100000),
    status: Optional[str] = None,
    source_site: Optional[str] = None,
    category: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import inspect as _sa_inspect

    # DB 레벨에서 무거운 컬럼 제외하여 조회 (응답 크기 93% 절감)
    mapper = _sa_inspect(_CP)
    light_cols = [c for c in mapper.columns if c.key not in _HEAVY_FIELDS]

    stmt = select(*light_cols)
    if status:
        stmt = stmt.where(_CP.status == status)
    if source_site:
        stmt = stmt.where(_CP.source_site == source_site)
    if category:
        # prefix 매칭: "여성" → "여성" 또는 "여성 > ..." 모두 포함
        stmt = stmt.where(
            (_CP.category == category) | (_CP.category.startswith(category + " > "))
        )
    stmt = stmt.order_by(_CP.created_at.desc()).offset(skip).limit(limit)

    result = await session.execute(stmt)
    rows = result.mappings().all()
    return [dict(r) for r in rows]


@router.post("/products/by-ids")
async def get_products_by_ids(
    body: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """ID 리스트로 상품 조회 (light 컬럼만)."""
    ids = body.get("ids", [])
    if not ids:
        return []
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import inspect as _sa_inspect

    mapper = _sa_inspect(_CP)
    light_cols = [c for c in mapper.columns if c.key not in _HEAVY_FIELDS]
    stmt = select(*light_cols).where(_CP.id.in_(ids))
    result = await session.execute(stmt)
    rows = result.mappings().all()
    return [dict(r) for r in rows]


@router.get("/products/with-orders")
async def get_product_ids_with_orders(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """주문 이력이 있는 상품 ID 목록 조회."""
    from sqlmodel import text

    result = await session.execute(
        text("SELECT DISTINCT product_id FROM samba_order WHERE product_id IS NOT NULL")
    )
    return [row[0] for row in result.all()]


@router.get("/products/search")
async def search_collected_products(
    q: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_services(session)
    return await svc.search_collected_products(q, limit)


@router.get("/products/{product_id}")
async def get_collected_product(
    product_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_services(session)
    p = await svc.get_collected_product(product_id)
    if not p:
        raise HTTPException(404, "상품을 찾을 수 없습니다")
    return p


@router.get("/products/{product_id}/price-history")
async def get_price_history(
    product_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """가격변경이력만 경량 조회 (price_history 컬럼만 SELECT)."""
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from sqlalchemy import select as _sel

    # 상품 존재 여부와 price_history 값을 분리 조회
    # scalar_one_or_none()은 컬럼값이 NULL일 때도 None 반환하므로
    # id 컬럼을 함께 SELECT하여 상품 존재 여부를 정확히 판단
    stmt = _sel(_CP.id, _CP.price_history).where(_CP.id == product_id)
    result = await session.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise HTTPException(404, "상품을 찾을 수 없습니다")
    raw = row[1] or []
    # null/non-dict 엔트리 제거 — 데이터 손상 방어
    return [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []


@router.post("/products", status_code=201)
async def create_collected_product(
    body: CollectedProductCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    from fastapi.responses import JSONResponse

    svc = _get_services(session)
    result = await svc.create_collected_product(body.model_dump(exclude_unset=True))
    if result is None:
        return JSONResponse(
            status_code=409,
            content={"detail": "동일 소싱처에 동일 원 상품명이 이미 존재합니다."},
        )
    # 상품 생성 시 캐시 무효화
    await cache.clear_pattern("products:*")
    return result


@router.get("/products/lookup-by-market-no/{market_product_no}")
async def lookup_by_market_product_no(
    market_product_no: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """마켓 상품번호로 수집상품 조회 (원문링크/이미지 등 반환)."""
    from sqlalchemy import text as sa_text

    # 하이픈/공백 제거한 정규화 값 (IQ2245-068 → IQ2245068)
    spid_norm = market_product_no.replace("-", "").replace(" ", "")
    sql = sa_text(
        "SELECT id, source_site, site_product_id, name, images, source_url "
        "FROM samba_collected_product "
        "WHERE market_product_nos::text LIKE :pattern "
        "   OR market_product_nos::text LIKE :pattern_bare "
        "   OR site_product_id = :spid "
        "   OR REPLACE(site_product_id, '-', '') = :spid_norm "
        "LIMIT 1"
    )
    result = await session.execute(
        sql,
        {
            "pattern": f'%"{market_product_no}"%',
            "pattern_bare": f"%{market_product_no}%",
            "spid": market_product_no,
            "spid_norm": spid_norm,
        },
    )
    row = result.fetchone()
    if not row:
        return {"found": False}
    pid, source_site, site_product_id, name, images, source_url = row
    thumb = images[0] if images and isinstance(images, list) and images else ""
    return {
        "found": True,
        "id": pid,
        "source_site": source_site,
        "site_product_id": site_product_id,
        "name": name,
        "original_link": source_url or "",
        "product_image": thumb,
    }


@router.post("/products/bulk", status_code=201)
async def bulk_create_collected_products(
    body: BulkCreateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    items = [item.model_dump(exclude_unset=True) for item in body.items]
    created_count = await svc.bulk_create_products(items)
    # 상품 일괄 생성 시 캐시 무효화
    await cache.clear_pattern("products:*")
    return {"created": created_count}


@router.post("/products/images/bulk-remove")
async def bulk_remove_image(
    body: BulkImageRemoveRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """특정 이미지 URL을 모든 상품에서 일괄 삭제 (추적삭제)."""
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlalchemy import cast, String
    from sqlmodel import select

    # fields 우선, 없으면 기존 field 하위호환
    target_fields = body.fields if body.fields else [body.field]
    image_url = body.image_url

    # DB 레벨에서 해당 이미지 URL을 포함하는 상품만 필터링 (전체 로드 방지)
    conditions = []
    if "images" in target_fields:
        conditions.append(
            cast(SambaCollectedProduct.images, String).like(f"%{image_url}%")
        )
    if "detail_images" in target_fields:
        conditions.append(
            cast(SambaCollectedProduct.detail_images, String).like(f"%{image_url}%")
        )
    if not conditions:
        return {"removed": 0}

    stmt = select(SambaCollectedProduct).where(or_(*conditions))
    result = await session.exec(stmt)
    removed_count = 0
    for p in result.all():
        found = False
        if "images" in target_fields and p.images and image_url in p.images:
            p.images = [u for u in p.images if u != image_url]
            found = True
        if (
            "detail_images" in target_fields
            and p.detail_images
            and image_url in p.detail_images
        ):
            p.detail_images = [u for u in p.detail_images if u != image_url]
            found = True
        if found:
            tags = list(p.tags or [])
            if "__img_edited__" not in tags:
                tags.append("__img_edited__")
                p.tags = tags
            session.add(p)
            removed_count += 1
    await session.commit()
    return {"removed": removed_count}


@router.put("/products/{product_id}")
async def update_collected_product(
    product_id: str,
    body: CollectedProductUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    result = await svc.update_collected_product(
        product_id, body.model_dump(exclude_unset=True)
    )
    if not result:
        raise HTTPException(404, "상품을 찾을 수 없습니다")
    return result


@router.post("/products/{product_id}/reset-registration")
async def reset_product_registration(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품의 마켓 등록 정보(registered_accounts, market_product_nos) 초기화."""
    svc = _get_services(session)
    result = await svc.update_collected_product(
        product_id,
        {
            "registered_accounts": None,
            "market_product_nos": None,
            "status": "collected",
        },
    )
    if not result:
        raise HTTPException(404, "상품을 찾을 수 없습니다")
    return {"ok": True}


@router.delete("/products/{product_id}")
async def delete_collected_product(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    if not await svc.delete_collected_product(product_id):
        raise HTTPException(404, "상품을 찾을 수 없습니다")
    return {"ok": True}


@router.post("/products/bulk-delete")
async def bulk_delete_products(
    body: BulkProductIdsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품 일괄 삭제 — 단일 DELETE 쿼리."""
    from sqlalchemy import delete as sa_delete
    from sqlmodel import col
    from backend.domain.samba.collector.model import SambaCollectedProduct

    stmt = sa_delete(SambaCollectedProduct).where(
        col(SambaCollectedProduct.id).in_(body.ids)
    )
    result = await session.exec(stmt)  # type: ignore[arg-type]
    await session.commit()
    # 상품 삭제 시 캐시 무효화
    await cache.clear_pattern("products:*")
    return {"deleted": result.rowcount}


@router.post("/products/block-and-delete")
async def block_and_delete_products(
    body: BlockProductRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """수집차단 + 삭제 — 블랙리스트 등록 후 상품 삭제."""
    from sqlalchemy import delete as sa_delete
    from sqlmodel import col, select
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    # 삭제 대상 상품 정보 조회
    stmt = select(SambaCollectedProduct).where(
        col(SambaCollectedProduct.id).in_(body.product_ids)
    )
    result = await session.execute(stmt)
    products = result.scalars().all()

    if not products:
        raise HTTPException(404, "상품을 찾을 수 없습니다")

    # 블랙리스트 로드
    settings_repo = SambaSettingsRepository(session)
    row = await settings_repo.find_by_async(key="collection_blacklist")
    blacklist: list[dict] = []
    if row and isinstance(row.value, list):
        blacklist = row.value

    # 블랙리스트에 추가
    existing_keys = {f"{b['source_site']}:{b['site_product_id']}" for b in blacklist}
    added = 0
    for p in products:
        key = f"{p.source_site}:{p.site_product_id}"
        if key not in existing_keys and p.source_site and p.site_product_id:
            blacklist.append(
                {
                    "source_site": p.source_site,
                    "site_product_id": p.site_product_id,
                    "name": (p.name or "")[:50],
                    "blocked_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            existing_keys.add(key)
            added += 1

    # 블랙리스트 저장
    if row:
        row.value = blacklist
        session.add(row)
    else:
        from backend.domain.samba.forbidden.model import SambaSettings

        new_row = SambaSettings(key="collection_blacklist", value=blacklist)
        session.add(new_row)

    # 상품 삭제
    del_stmt = sa_delete(SambaCollectedProduct).where(
        col(SambaCollectedProduct.id).in_(body.product_ids)
    )
    del_result = await session.exec(del_stmt)  # type: ignore[arg-type]
    await session.commit()
    await cache.clear_pattern("products:*")
    _invalidate_blacklist_cache()

    return {"ok": True, "blocked": added, "deleted": del_result.rowcount}


@router.post("/products/bulk-reset-registration")
async def bulk_reset_registration(
    body: BulkProductIdsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품 마켓 등록 정보 일괄 초기화 — 단일 UPDATE 쿼리."""
    from sqlalchemy import update as sa_update
    from sqlmodel import col
    from backend.domain.samba.collector.model import SambaCollectedProduct

    stmt = (
        sa_update(SambaCollectedProduct)
        .where(col(SambaCollectedProduct.id).in_(body.ids))
        .values(registered_accounts=None, market_product_nos=None, status="collected")
    )
    result = await session.exec(stmt)  # type: ignore[arg-type]
    await session.commit()
    return {"reset": result.rowcount}


@router.post("/products/fix-nike-categories")
async def fix_nike_categories(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """기존 Nike 상품 카테고리를 search_filter.category_filter 기반으로 보정."""
    from backend.domain.samba.collector.model import (
        SambaCollectedProduct,
        SambaSearchFilter,
    )

    stmt = (
        select(SambaCollectedProduct, SambaSearchFilter.category_filter)
        .join(
            SambaSearchFilter,
            SambaCollectedProduct.search_filter_id == SambaSearchFilter.id,
        )
        .where(SambaCollectedProduct.source_site == "Nike")
    )
    rows = (await session.execute(stmt)).all()

    updated = 0
    for product, cat_filter in rows:
        if not cat_filter:
            continue
        # "남성_러닝화" → cat2="남성", cat3="러닝화"
        # "가방" (언더스코어 없음) → cat2="", cat3="가방"
        parts = cat_filter.split("_", 1)
        if len(parts) == 2:
            cat2, cat3 = parts
        else:
            cat2, cat3 = "", parts[0]
        new_category = " > ".join([x for x in [cat2, cat3] if x])
        if product.category != new_category:
            product.category = new_category
            product.category2 = cat2
            product.category3 = cat3
            session.add(product)
            updated += 1

    await session.commit()
    # category-tree 캐시 무효화
    await cache.delete("products:category-tree")
    await cache.delete("products:counts")
    return {"updated": updated, "total": len(rows)}


@router.post("/products/bulk-update-tags")
async def bulk_update_tags(
    body: BulkTagUpdateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품 태그/SEO키워드 일괄 업데이트."""
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlmodel import col

    stmt = select(SambaCollectedProduct).where(
        col(SambaCollectedProduct.id).in_(body.ids)
    )
    results = await session.exec(stmt)
    products = results.all()
    for p in products:
        if body.tags is not None:
            p.tags = body.tags
        if body.seo_keywords is not None:
            p.seo_keywords = body.seo_keywords
        session.add(p)
    await session.commit()
    return {"updated": len(products)}


@router.post("/products/bulk-add-account")
async def bulk_add_registered_account(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """플레이오토 API에서 등록 상품 조회 → site_product_id 매칭 → registered_accounts에 계정 추가."""
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.playauto import PlayAutoClient

    # 플레이오토 계정 조회
    pa_stmt = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "playauto",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    pa_result = await session.exec(pa_stmt)
    pa_acc = pa_result.first()
    if not pa_acc:
        raise HTTPException(400, "플레이오토 계정이 없습니다")

    pa_extras = pa_acc.additional_fields or {}
    pa_api_key = pa_extras.get("apiKey", "") or getattr(pa_acc, "api_key", "")
    if not pa_api_key:
        raise HTTPException(400, "플레이오토 API Key가 없습니다")

    # 플레이오토 API에서 등록 상품 조회
    client = PlayAutoClient(pa_api_key)
    try:
        pa_products = await client.get_products()
    finally:
        await client.close()

    # ModelName(=site_product_id) 추출
    pa_model_names = set()
    for pp in pa_products:
        mn = str(pp.get("ModelName", "") or "").strip()
        if mn:
            pa_model_names.add(mn)

    if not pa_model_names:
        return {"error": "플레이오토에 등록된 상품이 없습니다", "pa_count": 0}

    # DB에서 매칭되는 상품 조회
    stmt = select(SambaCollectedProduct).where(
        SambaCollectedProduct.status == "registered",
        SambaCollectedProduct.site_product_id.in_(pa_model_names),
    )
    results = await session.exec(stmt)
    products = results.all()

    updated = 0
    already = 0
    for p in products:
        reg = list(p.registered_accounts or [])
        if pa_acc.id not in reg:
            reg.append(pa_acc.id)
            p.registered_accounts = reg
            session.add(p)
            updated += 1
        else:
            already += 1

    if updated > 0:
        await session.commit()
    return {
        "pa_products": len(pa_model_names),
        "matched": len(products),
        "updated": updated,
        "already": already,
        "account_id": pa_acc.id,
    }
