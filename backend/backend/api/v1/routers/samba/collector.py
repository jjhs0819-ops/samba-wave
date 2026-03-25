"""SambaWave Collector API router - 수집 필터 + 수집 상품."""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.cache import cache
from backend.domain.samba.proxy.musinsa import RateLimitError
from backend.domain.samba.collector.grouping import generate_group_key, parse_color_from_name
from backend.domain.samba.collector.refresher import _site_intervals, _site_consecutive_errors

router = APIRouter(prefix="/collector", tags=["samba-collector"])


def _build_product_data(
    detail: dict, goods_no: str, filter_id: str, site: str,
    cost: float, sale_price: float, original_price: float,
    raw_cat: str, cat_parts: list, raw_detail_html: str,
) -> dict:
    """수집 상품 데이터 빌드 (collect_by_url / collect_by_filter 공통)."""
    initial_snapshot = {
        "date": datetime.now(timezone.utc).isoformat(),
        "sale_price": sale_price,
        "original_price": original_price,
        "cost": cost,
        "options": detail.get("options", []),
    }
    return {
        "source_site": site,
        "site_product_id": goods_no,
        "search_filter_id": filter_id,
        "name": detail.get("name", ""),
        "brand": detail.get("brand", ""),
        "original_price": original_price,
        "sale_price": sale_price,
        "cost": cost,
        "images": detail.get("images", []),
        "detail_images": detail.get("detailImages") or [],
        "options": detail.get("options", []),
        "category": raw_cat,
        "category1": cat_parts[0] if len(cat_parts) > 0 else None,
        "category2": cat_parts[1] if len(cat_parts) > 1 else None,
        "category3": cat_parts[2] if len(cat_parts) > 2 else None,
        "category4": cat_parts[3] if len(cat_parts) > 3 else None,
        "manufacturer": detail.get("manufacturer"),
        "origin": detail.get("origin"),
        "material": detail.get("material"),
        "color": detail.get("color"),
        "style_code": detail.get("style_code", ""),
        "sex": detail.get("sex", ""),
        "season": detail.get("season", ""),
        "care_instructions": detail.get("care_instructions", ""),
        "quality_guarantee": detail.get("quality_guarantee", ""),
        "detail_html": raw_detail_html,
        "status": "collected",
        "is_sold_out": detail.get("saleStatus") == "sold_out",
        "sale_status": detail.get("saleStatus", "in_stock"),
        "free_shipping": detail.get("freeShipping", False),
        "same_day_delivery": detail.get("sameDayDelivery", False),
        "price_history": [initial_snapshot],
    }


def _trim_history(history: list) -> list:
    """price_history를 최초 수집 1개 + 최근 4개 = 최대 5개로 제한."""
    if len(history) <= 5:
        return history
    # history[0]이 최신, history[-1]이 최초
    return history[:4] + [history[-1]]


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


class CollectByUrlRequest(BaseModel):
    url: str
    source_site: Optional[str] = None  # auto-detect if not provided


class CollectByKeywordRequest(BaseModel):
    source_site: str = "MUSINSA"
    keyword: str
    page: int = 1
    size: int = 30


# ── Helper ──

def _get_services(session: AsyncSession):
    from backend.domain.samba.collector.repository import (
        SambaCollectedProductRepository,
        SambaSearchFilterRepository,
    )
    from backend.domain.samba.collector.service import SambaCollectorService

    return SambaCollectorService(
        SambaSearchFilterRepository(session),
        SambaCollectedProductRepository(session),
    )


# ── KREAM 가격이력 스냅샷 헬퍼 ──

def _build_kream_price_snapshot(sale_price, original_price, cost, options):
    """KREAM 전용 가격이력 스냅샷 — 빠른배송/일반배송 최저가 포함."""
    from datetime import datetime, timezone

    fast_prices = [o.get("kreamFastPrice", 0) for o in (options or []) if o.get("kreamFastPrice", 0) > 0]
    general_prices = [o.get("kreamGeneralPrice", 0) for o in (options or []) if o.get("kreamGeneralPrice", 0) > 0]

    return {
        "date": datetime.now(timezone.utc).isoformat(),
        "sale_price": sale_price,
        "original_price": original_price,
        "cost": cost,
        "kream_fast_min": min(fast_prices) if fast_prices else 0,
        "kream_general_min": min(general_prices) if general_prices else 0,
        "options": [
            {
                "name": o.get("name", ""),
                "price": o.get("price", 0),
                "stock": o.get("stock", 0),
                "kreamFastPrice": o.get("kreamFastPrice", 0),
                "kreamGeneralPrice": o.get("kreamGeneralPrice", 0),
            }
            for o in (options or [])
        ],
    }


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
    except Exception:
        pass
    return {"status": "error", "message": "무신사 인증 필요"}


# ── Search Filters ──

@router.get("/filters")
async def list_filters(session: AsyncSession = Depends(get_read_session_dependency)):
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
    count_stmt = (
        select(
            _CP.search_filter_id,
            func.count().label("collected_count"),
            func.count(case((and_(_CP.registered_accounts != None), literal(1)))).label("market_registered_count"),
            func.count(case((and_(_CP.applied_policy_id != None), literal(1)))).label("policy_applied_count"),
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
        }

    result = []
    for f in filters:
        data = {c.key: getattr(f, c.key) for c in f.__table__.columns}
        counts = count_map.get(f.id, {})
        data["collected_count"] = counts.get("collected_count", 0)
        data["market_registered_count"] = counts.get("market_registered_count", 0)
        data["policy_applied_count"] = counts.get("policy_applied_count", 0)
        data["ai_tagged_count"] = 0
        data["ai_image_count"] = 0
        data["tag_applied_count"] = 0
        result.append(data)
    return result


@router.post("/filters", status_code=201)
async def create_filter(
    body: SearchFilterCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    return await svc.create_filter(body.model_dump(exclude_unset=True))


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

    # 정책 적용 시 해당 그룹 상품에 자동 전파
    if "applied_policy_id" in data and data["applied_policy_id"]:
        from backend.domain.samba.policy.repository import SambaPolicyRepository
        policy_repo = SambaPolicyRepository(session)
        policy = await policy_repo.get_async(data["applied_policy_id"])
        policy_data = None
        if policy and policy.pricing:
            pr = policy.pricing if isinstance(policy.pricing, dict) else {}
            policy_data = {
                "margin_rate": pr.get("marginRate", 15),
                "shipping_cost": pr.get("shippingCost", 0),
                "extra_charge": pr.get("extraCharge", 0),
            }
        count = await svc.apply_policy_to_filter_products(
            filter_id, data["applied_policy_id"], policy_data
        )
        logger.info(f"정책 전파: 필터 {filter_id} → {count}개 상품")

    return result


@router.delete("/filters/{filter_id}")
async def delete_filter(
    filter_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    if not await svc.delete_filter(filter_id):
        raise HTTPException(404, "필터를 찾을 수 없습니다")
    return {"ok": True}


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
    if leaf_ids:
        count_stmt = (
            select(_CP.search_filter_id, _func.count().label("cnt"))
            .where(_CP.search_filter_id.in_(leaf_ids))
            .group_by(_CP.search_filter_id)
        )
        count_result = await session.execute(count_stmt)
        for row in count_result.all():
            count_map[row[0]] = row[1]

    filter_data = []
    for f in all_filters:
        data = {c.key: getattr(f, c.key) for c in f.__table__.columns}
        data["collected_count"] = count_map.get(f.id, 0) if not f.is_folder else 0
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


class FolderCreateRequest(BaseModel):
    source_site: str
    name: str
    parent_id: Optional[str] = None


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


class MoveFilterRequest(BaseModel):
    parent_id: Optional[str] = None


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

_HEAVY_FIELDS = {"price_history", "detail_html", "detail_images", "last_sent_data", "care_instructions"}


@router.get("/products/scroll")
async def scroll_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
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
    from sqlalchemy import inspect as _sa_inspect, func, cast, String, text

    mapper = _sa_inspect(_CP)
    light_cols = [c for c in mapper.columns if c.key not in _HEAVY_FIELDS]

    # 기본 조건
    conditions = []

    # 텍스트 검색
    q = search.strip()
    if q:
        if search_type == "name":
            conditions.append(_CP.name.ilike(f"%{q}%"))
        elif search_type == "name_all":
            # 상품명 + 등록상품명(name_en) 동시 검색
            conditions.append(or_(_CP.name.ilike(f"%{q}%"), _CP.name_en.ilike(f"%{q}%")))
        elif search_type == "no":
            conditions.append(_CP.site_product_id.ilike(f"%{q}%"))
        elif search_type == "filter":
            # 검색필터 이름으로 검색 → search_filter_id 서브쿼리
            from backend.domain.samba.collector.model import SambaSearchFilter as _SF
            sf_ids = select(_SF.id).where(_SF.name.ilike(f"%{q}%"))
            conditions.append(_CP.search_filter_id.in_(sf_ids))
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
    if status == "has_orders":
        from backend.domain.samba.order.model import SambaOrder
        order_pids = select(SambaOrder.product_id).where(SambaOrder.product_id.isnot(None)).distinct()
        conditions.append(_CP.id.in_(order_pids))
    elif status == "free_ship":
        conditions.append(_CP.free_shipping == True)
    elif status == "same_day":
        conditions.append(_CP.same_day_delivery == True)
    elif status == "free_same":
        conditions.append(_CP.free_shipping == True)
        conditions.append(_CP.same_day_delivery == True)
    elif status:
        conditions.append(_CP.status == status)

    # AI 필터 (JSON 태그/이미지 패턴)
    if ai_filter == "sold_out":
        conditions.append(or_(_CP.is_sold_out == True, _CP.sale_status == "sold_out"))
    elif ai_filter == "ai_tag_yes":
        conditions.append(cast(_CP.tags, String).like('%"__ai_tagged__"%'))
    elif ai_filter == "ai_tag_no":
        conditions.append(or_(
            _CP.tags.is_(None),
            ~cast(_CP.tags, String).like('%"__ai_tagged__"%'),
        ))
    elif ai_filter == "ai_img_yes":
        conditions.append(or_(
            cast(_CP.images, String).like('%/transformed/%'),
            cast(_CP.images, String).like('%/static/images/ai_%'),
        ))
    elif ai_filter == "ai_img_no":
        conditions.append(or_(
            _CP.images.is_(None),
            ~cast(_CP.images, String).like('%/transformed/%'),
        ))
    elif ai_filter == "filter_yes":
        conditions.append(cast(_CP.tags, String).like('%"__img_filtered__"%'))
    elif ai_filter == "filter_no":
        conditions.append(or_(
            _CP.tags.is_(None),
            ~cast(_CP.tags, String).like('%"__img_filtered__"%'),
        ))
    elif ai_filter == "img_edit_yes":
        conditions.append(or_(
            cast(_CP.tags, String).like('%"__ai_image__"%'),
            cast(_CP.tags, String).like('%"__img_filtered__"%'),
            cast(_CP.tags, String).like('%"__img_edited__"%'),
        ))
    elif ai_filter == "img_edit_no":
        conditions.append(~or_(
            cast(_CP.tags, String).like('%"__ai_image__"%'),
            cast(_CP.tags, String).like('%"__img_filtered__"%'),
            cast(_CP.tags, String).like('%"__img_edited__"%'),
        ))
    elif ai_filter == "video_yes":
        conditions.append(_CP.video_url.isnot(None))
        conditions.append(_CP.video_url != "")
    elif ai_filter == "video_no":
        conditions.append(or_(_CP.video_url.is_(None), _CP.video_url == ""))
    elif ai_filter == "has_orders":
        from backend.domain.samba.order.model import SambaOrder
        order_pids = select(SambaOrder.product_id).where(SambaOrder.product_id.isnot(None)).distinct()
        conditions.append(_CP.id.in_(order_pids))

    # 카운트 쿼리 (가볍게)
    count_stmt = select(func.count()).select_from(_CP)
    for c in conditions:
        count_stmt = count_stmt.where(c)
    total = (await session.execute(count_stmt)).scalar() or 0

    # 소싱처 목록 (전체 — 필터 무관, 캐시 TTL 5분)
    sites = await cache.get("products:sites")
    if not sites:
        sites_stmt = select(_CP.source_site).distinct().where(_CP.source_site.isnot(None))
        sites_result = await session.execute(sites_stmt)
        sites = sorted([r[0] for r in sites_result.all() if r[0]])
        await cache.set("products:sites", sites, ttl=300)

    # 데이터 쿼리
    data_stmt = select(*light_cols)
    for c in conditions:
        data_stmt = data_stmt.where(c)

    # 정렬
    if sort_by == "collect-asc":
        data_stmt = data_stmt.order_by(_CP.created_at.asc())
    elif sort_by == "update-desc":
        data_stmt = data_stmt.order_by(_CP.updated_at.desc().nullslast(), _CP.created_at.desc())
    elif sort_by == "update-asc":
        data_stmt = data_stmt.order_by(_CP.updated_at.asc().nullsfirst(), _CP.created_at.asc())
    else:
        data_stmt = data_stmt.order_by(_CP.created_at.desc())

    data_stmt = data_stmt.offset(skip).limit(limit)
    result = await session.execute(data_stmt)
    rows = result.mappings().all()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "sites": sites,
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
        func.count(case((_CP.registered_accounts != None, literal(1)))).label("registered"),
        func.count(case((_CP.applied_policy_id != None, literal(1)))).label("policy_applied"),
        func.count(case((_CP.is_sold_out == True, literal(1)))).label("sold_out"),
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
        .where(_CP.source_site != None, _CP.category != None)
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
    limit: int = Query(50, ge=1, le=10000),
    status: Optional[str] = None,
    source_site: Optional[str] = None,
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
    stmt = stmt.order_by(_CP.created_at.desc()).offset(skip).limit(limit)

    result = await session.execute(stmt)
    rows = result.mappings().all()
    return [dict(r) for r in rows]


@router.get("/products/with-orders")
async def get_product_ids_with_orders(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """주문 이력이 있는 상품 ID 목록 조회."""
    from sqlmodel import text
    result = await session.execute(text(
        "SELECT DISTINCT product_id FROM samba_order WHERE product_id IS NOT NULL"
    ))
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


@router.post("/products", status_code=201)
async def create_collected_product(
    body: CollectedProductCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    result = await svc.create_collected_product(body.model_dump(exclude_unset=True))
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
    sql = sa_text(
        "SELECT id, source_site, site_product_id, name, images "
        "FROM samba_collected_product "
        "WHERE market_product_nos::text LIKE :pattern "
        "LIMIT 1"
    )
    result = await session.execute(sql, {"pattern": f'%"{market_product_no}"%'})
    row = result.fetchone()
    if not row:
        return {"found": False}
    pid, source_site, site_product_id, name, images = row
    sourcing_urls = {
        "MUSINSA": f"https://www.musinsa.com/app/goods/{site_product_id}",
        "KREAM": f"https://kream.co.kr/products/{site_product_id}",
        "LOTTEON": f"https://www.lotteon.com/product/{site_product_id}",
        "SSG": f"https://www.ssg.com/item/itemView.ssg?itemId={site_product_id}",
        "ABCmart": f"https://abcmart.a-rt.com/product/{site_product_id}",
        "FashionPlus": f"https://www.fashionplus.co.kr/goods/{site_product_id}",
        "Nike": f"https://www.nike.com/kr/t/{site_product_id}",
        "Adidas": f"https://www.adidas.co.kr/{site_product_id}",
    }
    thumb = images[0] if images and isinstance(images, list) and images else ""
    return {
        "found": True,
        "id": pid,
        "source_site": source_site,
        "site_product_id": site_product_id,
        "name": name,
        "original_link": sourcing_urls.get(source_site, ""),
        "product_image": thumb,
    }


@router.post("/products/bulk", status_code=201)
async def bulk_create_collected_products(
    body: BulkCreateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    items = [item.model_dump(exclude_unset=True) for item in body.items]
    created = await svc.bulk_create_collected_products(items)
    # 상품 일괄 생성 시 캐시 무효화
    await cache.clear_pattern("products:*")
    return {"created": len(created)}


class BulkImageRemoveRequest(BaseModel):
    image_url: str
    field: str = "images"  # images 또는 detail_images


@router.post("/products/images/bulk-remove")
async def bulk_remove_image(
    body: BulkImageRemoveRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """특정 이미지 URL을 모든 상품에서 일괄 삭제 (추적삭제)."""
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlmodel import select

    stmt = select(SambaCollectedProduct)
    result = await session.exec(stmt)
    removed_count = 0
    for p in result.all():
        found = False
        # images와 detail_images 둘 다 검색
        if p.images and body.image_url in p.images:
            p.images = [u for u in p.images if u != body.image_url]
            found = True
        if p.detail_images and body.image_url in p.detail_images:
            p.detail_images = [u for u in p.detail_images if u != body.image_url]
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
    result = await svc.update_collected_product(product_id, body.model_dump(exclude_unset=True))
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
    result = await svc.update_collected_product(product_id, {
        "registered_accounts": None,
        "market_product_nos": None,
        "status": "collected",
    })
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


class BulkProductIdsRequest(BaseModel):
    ids: list[str]


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


class BulkTagUpdateRequest(BaseModel):
    ids: list[str]
    tags: list[str] | None = None
    seo_keywords: list[str] | None = None


@router.post("/products/bulk-update-tags")
async def bulk_update_tags(
    body: BulkTagUpdateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품 태그/SEO키워드 일괄 업데이트."""
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


# ── 실제 수집 (프록시 통합) ──

@router.post("/collect-by-url", status_code=201)
async def collect_by_url(
    body: CollectByUrlRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """URL로 소싱사이트에서 상품 수집 → DB 저장."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    from backend.domain.samba.proxy.kream import KreamClient

    url = body.url.strip()
    site = body.source_site

    # 사이트 자동 감지
    if not site:
        if "musinsa.com" in url:
            site = "MUSINSA"
        elif "kream.co.kr" in url:
            site = "KREAM"
        elif "ssg.com" in url:
            site = "SSG"
        elif "lotteon.com" in url:
            site = "LOTTEON"
        else:
            raise HTTPException(400, "지원하지 않는 URL입니다. source_site를 지정해주세요.")

    svc = _get_services(session)

    # 무신사 쿠키 로드 헬퍼
    async def _get_musinsa_cookie() -> str:
        from backend.domain.samba.forbidden.model import SambaSettings
        from sqlmodel import select
        try:
            result = await session.execute(
                select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
            )
            row = result.scalar_one_or_none()
            return (row.value if row and row.value else "") or ""
        except Exception:
            return ""

    if site == "MUSINSA":
        import re
        from urllib.parse import urlparse, parse_qs

        # 무신사 로그인(쿠키) 필수 체크
        cookie_check = await _get_musinsa_cookie()
        if not cookie_check:
            raise HTTPException(
                400,
                "무신사 수집은 로그인(쿠키)이 필요합니다. "
                "확장앱에서 무신사 로그인 후 다시 시도하세요.",
            )

        parsed = urlparse(url)
        is_search_url = "/search" in parsed.path or "keyword" in parsed.query

        if is_search_url:
            # ── 검색 URL → 키워드 추출 → 검색그룹 자동 생성 → 검색 API → 전체 일괄 저장 ──
            qs = parse_qs(parsed.query)
            keyword = qs.get("keyword", [""])[0]
            if not keyword:
                raise HTTPException(400, "검색 URL에서 키워드를 찾을 수 없습니다")

            # 카테고리 필터 추출
            category_filter = qs.get("category", [""])[0]

            # 수집 제외 옵션
            exclude_preorder = qs.get("excludePreorder", [""])[0] == "1"
            exclude_boutique = qs.get("excludeBoutique", [""])[0] == "1"
            # 최대혜택가 사용 여부 (체크 시 cost=bestBenefitPrice, 미체크 시 cost=salePrice)
            use_max_discount = qs.get("maxDiscount", [""])[0] == "1"

            # 검색그룹(SearchFilter) 자동 생성
            requested_count = 100  # 기본값
            search_filter = await svc.create_filter({
                "source_site": "MUSINSA",
                "name": keyword,
                "keyword": url,
                "category_filter": category_filter or None,
                "requested_count": requested_count,
            })
            filter_id = search_filter.id

            cookie = await _get_musinsa_cookie()
            client = MusinsaClient(cookie=cookie)

            # 기존 수집 상품 수 확인
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_count = await svc.product_repo.count_async(
                filters={"search_filter_id": filter_id}
            )
            remaining = max(0, requested_count - existing_count)
            if remaining <= 0:
                return {
                    "type": "search", "keyword": keyword, "filter_id": filter_id,
                    "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)",
                    "saved": 0, "enriched": 0,
                }

            # 필요한 만큼만 검색 (페이지당 100개)
            import asyncio as _asyncio
            all_items = []
            max_pages = max(1, (remaining // 100) + 1)
            for page in range(1, min(max_pages + 1, 11)):  # 최대 10페이지
                try:
                    data = await client.search_products(keyword=keyword, page=page, size=100)
                    items = data.get("data", [])
                    if not items:
                        break
                    all_items.extend(items)
                    await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌
                except Exception:
                    break

            if not all_items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            # 기존 상품 ID 일괄 조회 (중복 체크 — 단일 쿼리)
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in all_items]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "MUSINSA",
                CPModel.site_product_id.in_(candidate_ids),  # type: ignore[union-attr]
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            # 중복/품절 필터링 → 수집 대상 상품번호 추출
            skipped_sold_out = 0
            targets = []
            for item in all_items:
                if len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    skipped_sold_out += 1
                    continue
                targets.append(site_pid)

            # 각 상품 상세 수집 → 배치 저장 (10건씩 flush)
            saved = 0
            skipped_preorder = 0
            skipped_boutique = 0
            _batch_buf: list[dict] = []
            _BATCH_SIZE = 10
            rate_limited = False

            async def _flush_batch() -> int:
                """버퍼에 쌓인 상품을 한번에 DB 저장."""
                if not _batch_buf:
                    return 0
                cnt = await svc.bulk_create_products(list(_batch_buf))
                _batch_buf.clear()
                return cnt

            for goods_no in targets:
                try:
                    detail = await client.get_goods_detail(goods_no)
                    if not detail or not detail.get("name"):
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    if exclude_preorder and detail.get("saleStatus") == "preorder":
                        skipped_preorder += 1
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue
                    if exclude_boutique and detail.get("isBoutique"):
                        skipped_boutique += 1
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    # 최대혜택가 체크 시 bestBenefitPrice, 미체크 시 salePrice
                    if use_max_discount:
                        _raw_cost = detail.get("bestBenefitPrice")
                        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                    _sale_price = detail.get("salePrice", 0)
                    _original_price = detail.get("originalPrice", 0)

                    raw_detail_html = detail.get("detailHtml", "")
                    if not raw_detail_html:
                        detail_imgs = detail.get("detailImages") or []
                        if detail_imgs:
                            raw_detail_html = "\n".join(
                                f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                                for img in detail_imgs
                            )

                    product_data = _build_product_data(
                        detail, goods_no, filter_id, "MUSINSA",
                        new_cost, _sale_price, _original_price,
                        raw_cat, cat_parts, raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch()
                except RateLimitError:
                    logger.warning(f"[무신사] 요청 제한 감지 — 수집 중단 (수집완료: {saved}/{len(targets)})")
                    rate_limited = True
                    break
                except Exception as e:
                    logger.warning(f"[수집 실패] {goods_no}: {e}")
                await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))

            # 잔여 버퍼 flush
            await _flush_batch()

            # 검색그룹에 최근수집일 업데이트
            await svc.update_filter(filter_id, {
                "last_collected_at": datetime.now(timezone.utc),
            })

            return {
                "type": "search",
                "keyword": keyword,
                "filter_id": filter_id,
                "filter_name": keyword,
                "total_found": len(all_items),
                "saved": saved,
                "enriched": saved,
                "skipped_duplicates": len(all_items) - len(targets) - skipped_sold_out,
                "skipped_sold_out": skipped_sold_out,
                "skipped_preorder": skipped_preorder,
                "skipped_boutique": skipped_boutique,
            }

        else:
            # ── 단일 상품 URL → 상품번호 추출 → 상세 API ──
            match = re.search(r'/products/(\d+)', url) or re.search(r'goodsNo=(\d+)', url) or re.search(r'/(\d+)', url)
            if not match:
                raise HTTPException(400, "무신사 상품 URL에서 상품번호를 찾을 수 없습니다")
            goods_no = match.group(1)

            cookie = await _get_musinsa_cookie()
            client = MusinsaClient(cookie=cookie)
            data = await client.get_goods_detail(goods_no)
            if not data or not data.get("name"):
                raise HTTPException(502, "무신사 상품 조회 실패")

            from datetime import datetime, timezone
            # 가격이력 초기 스냅샷
            initial_snapshot = {
                "date": datetime.now(timezone.utc).isoformat(),
                "sale_price": data.get("salePrice", 0),
                "original_price": data.get("originalPrice", 0),
                "options": data.get("options", []),
            }
            sale_status = data.get("saleStatus", "in_stock")
            # 상세 HTML: 수집 데이터의 detailHtml 사용
            raw_detail_html = data.get("detailHtml", "")
            if not raw_detail_html:
                # 상세 이미지가 있으면 이미지로 HTML 생성
                detail_imgs = data.get("detailImages") or []
                if detail_imgs:
                    raw_detail_html = "\n".join(
                        f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                        for img in detail_imgs
                    )

            # 중복 체크: 기존 상품이 있으면 업데이트 (upsert)
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_stmt = select(CPModel).where(
                CPModel.source_site == "MUSINSA",
                CPModel.site_product_id == goods_no,
            )
            existing_row = (await session.execute(existing_stmt)).scalar_one_or_none()

            # 그룹상품용 similarNo 추출
            similar_no = str(data.get("similarNo", "0"))

            product_data = {
                "source_site": "MUSINSA",
                "site_product_id": goods_no,
                "name": data.get("name", ""),
                "brand": data.get("brand", ""),
                "original_price": data.get("originalPrice", 0),
                "sale_price": data.get("salePrice", 0),
                "cost": data.get("bestBenefitPrice") or None,
                "images": data.get("images", []),
                "detail_images": data.get("detailImages") or [],
                "options": data.get("options", []),
                "category": data.get("category", ""),
                "category1": data.get("category1", ""),
                "category2": data.get("category2", ""),
                "category3": data.get("category3", ""),
                "category4": data.get("category4", ""),
                "manufacturer": data.get("manufacturer", ""),
                "origin": data.get("origin", ""),
                "material": data.get("material", ""),
                "color": data.get("color", "") or parse_color_from_name(data.get("name", "")),
                "similar_no": similar_no,
                "style_code": data.get("styleNo", ""),
                "group_key": generate_group_key(
                    brand=data.get("brand", ""),
                    similar_no=similar_no,
                    style_code=data.get("styleNo", ""),
                    name=data.get("name", ""),
                ),
                "detail_html": raw_detail_html,
                "status": "collected",
                "is_sold_out": sale_status == "sold_out",
                "sale_status": sale_status,
                "free_shipping": data.get("freeShipping", False),
                "same_day_delivery": data.get("sameDayDelivery", False),
                "price_history": [initial_snapshot],
            }

            if existing_row:
                # 기존 상품 → 가격이력 누적 후 업데이트
                history = list(existing_row.price_history or [])
                history.insert(0, initial_snapshot)
                product_data["price_history"] = _trim_history(history)
                # 재수집 시 기존 태그 보존 (확장앱은 tags를 보내지 않음)
                if "tags" not in product_data or not product_data.get("tags"):
                    product_data.pop("tags", None)
                collected = await svc.update_collected_product(existing_row.id, product_data)
                return {"type": "single", "saved": 1, "updated": True, "product": collected}
            else:
                collected = await svc.create_collected_product(product_data)
                return {"type": "single", "saved": 1, "product": collected}

    elif site == "KREAM":
        import re
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(url)
        is_search_url = "/search" in parsed.path or "keyword" in parsed.query

        if is_search_url:
            qs = parse_qs(parsed.query)
            keyword = qs.get("keyword", qs.get("tab", [""]))[0]
            if not keyword:
                raise HTTPException(400, "KREAM 검색 URL에서 키워드를 찾을 수 없습니다")

            # 검색그룹(SearchFilter) 자동 생성
            search_filter = await svc.create_filter({
                "source_site": "KREAM",
                "name": keyword,
                "keyword": url,
            })
            filter_id = search_filter.id

            client = KreamClient()
            try:
                items = await client.search(keyword, 100)
            except Exception as e:
                raise HTTPException(
                    504,
                    f"KREAM 검색 타임아웃: {str(e)}. "
                    "웨일 브라우저 확장앱이 실행 중인지 확인하세요.",
                )

            if not items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            items_list = items if isinstance(items, list) else []

            # 기존 상품 ID 일괄 조회
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            candidate_ids = [
                str(item.get("siteProductId") or item.get("id") or "")
                for item in items_list
            ]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "KREAM",
                CPModel.site_product_id.in_(candidate_ids),  # type: ignore[union-attr]
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            bulk_items = []
            for item in items_list:
                # 확장앱 검색결과: siteProductId / id 둘 다 지원
                site_pid = str(
                    item.get("siteProductId")
                    or item.get("id")
                    or ""
                )
                if not site_pid or site_pid in existing_ids:
                    continue
                bulk_items.append({
                    "source_site": "KREAM",
                    "site_product_id": site_pid,
                    "search_filter_id": filter_id,
                    "name": item.get("name", ""),
                    "brand": item.get("brand", ""),
                    "original_price": item.get("originalPrice", item.get("retailPrice", 0)),
                    "sale_price": item.get("salePrice", item.get("retailPrice", 0)),
                    "images": item.get("images", [item.get("imageUrl", "")]) if (item.get("images") or item.get("imageUrl")) else [],
                    "similar_no": None,
                    "group_key": generate_group_key(
                        brand=item.get("brand", ""),
                        similar_no=None,
                        style_code=item.get("styleCode", ""),
                        name=item.get("name", ""),
                    ),
                    "status": "collected",
                })

            created = []
            if bulk_items:
                created = await svc.bulk_create_collected_products(bulk_items)

            # 검색그룹에 최근수집일 업데이트
            from datetime import datetime, timezone
            await svc.update_filter(filter_id, {
                "last_collected_at": datetime.now(timezone.utc),
            })

            return {
                "type": "search",
                "keyword": keyword,
                "filter_id": filter_id,
                "filter_name": keyword,
                "total_found": len(items_list),
                "saved": len(created),
                "skipped_duplicates": len(items_list) - len(created),
            }

        else:
            match = re.search(r'/products/(\d+)', url)
            if not match:
                raise HTTPException(400, "KREAM 상품 URL에서 상품번호를 찾을 수 없습니다")
            product_id = match.group(1)

            client = KreamClient()
            try:
                data = await client.get_product(product_id)
            except Exception as e:
                raise HTTPException(
                    504,
                    f"KREAM 상품 조회 타임아웃: {str(e)}. "
                    "웨일 브라우저 확장앱이 실행 중인지 확인하세요.",
                )

            if not data:
                raise HTTPException(502, "KREAM 상품 조회 실패")

            # 확장앱 수집 결과: { success, product: { ... } }
            product_data = data.get("product", data)

            _sp = product_data.get("salePrice", product_data.get("retailPrice", 0))
            _op = product_data.get("originalPrice", product_data.get("retailPrice", 0))
            _opts = product_data.get("options", [])
            _snapshot = _build_kream_price_snapshot(_sp, _op, _sp, _opts)

            # 중복 체크: 기존 상품이 있으면 업데이트 (upsert)
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_stmt = select(CPModel).where(
                CPModel.source_site == "KREAM",
                CPModel.site_product_id == product_id,
            )
            existing_row = (await session.execute(existing_stmt)).scalar_one_or_none()

            kream_product_data = {
                "source_site": "KREAM",
                "site_product_id": product_id,
                "name": product_data.get("name", ""),
                "brand": product_data.get("brand", ""),
                "original_price": _op,
                "sale_price": _sp,
                "images": product_data.get("images", []),
                "options": _opts,
                "category": product_data.get("category", ""),
                "category1": product_data.get("category1", ""),
                "category2": product_data.get("category2", ""),
                "category3": product_data.get("category3", ""),
                "similar_no": None,
                "color": parse_color_from_name(product_data.get("name", "")),
                "group_key": generate_group_key(
                    brand=product_data.get("brand", ""),
                    similar_no=None,
                    style_code=product_data.get("styleCode", ""),
                    name=product_data.get("name", ""),
                ),
                "status": "collected",
                "price_history": [_snapshot],
            }

            if existing_row:
                # 기존 상품 → 가격이력 누적 후 업데이트
                history = list(existing_row.price_history or [])
                history.insert(0, _snapshot)
                kream_product_data["price_history"] = _trim_history(history)
                # 재수집 시 기존 태그 보존
                if "tags" not in kream_product_data or not kream_product_data.get("tags"):
                    kream_product_data.pop("tags", None)
                collected = await svc.update_collected_product(existing_row.id, kream_product_data)
                return {"type": "single", "saved": 1, "updated": True, "product": collected}
            else:
                collected = await svc.create_collected_product(kream_product_data)
                return {"type": "single", "saved": 1, "product": collected}

    # ── SSG 수집 ──
    elif site == "SSG":
        import re
        from urllib.parse import urlparse, parse_qs
        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        parsed = urlparse(url)
        is_search_url = "/search" in parsed.path or "query" in parsed.query

        if is_search_url:
            qs = parse_qs(parsed.query)
            keyword = qs.get("query", [""])[0]
            if not keyword:
                raise HTTPException(400, "검색 URL에서 키워드를 찾을 수 없습니다")

            use_max_discount = qs.get("maxDiscount", [""])[0] == "1"

            # 검색그룹 자동 생성
            search_filter = await svc.create_filter({
                "source_site": "SSG",
                "name": keyword,
                "keyword": url,
                "requested_count": 100,
            })
            filter_id = search_filter.id

            client = SSGSourcingClient()

            # 기존 수집 수 확인
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_count = await svc.product_repo.count_async(filters={"search_filter_id": filter_id})
            remaining = max(0, 100 - existing_count)
            if remaining <= 0:
                return {"type": "search", "keyword": keyword, "filter_id": filter_id,
                        "message": f"이미 {existing_count}개 수집됨", "saved": 0, "enriched": 0}

            # 검색
            import asyncio as _asyncio
            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(keyword=keyword, page=page, size=40)
                    if not items:
                        break
                    all_items.extend(items)
                    await _asyncio.sleep(_site_intervals.get("SSG", 1.0))
                except Exception:
                    break

            if not all_items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            # 중복 필터
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in all_items]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "SSG",
                CPModel.site_product_id.in_(candidate_ids),
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            targets = []
            skipped_sold_out = 0
            for item in all_items:
                if len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    skipped_sold_out += 1
                    continue
                targets.append(site_pid)

            # 상세 수집 + 배치 저장
            saved = 0
            _batch_buf: list[dict] = []
            _BATCH_SIZE = 10

            async def _flush_batch() -> int:
                if not _batch_buf:
                    return 0
                cnt = await svc.bulk_create_products(list(_batch_buf))
                _batch_buf.clear()
                return cnt

            for item_id in targets:
                try:
                    detail = await client.get_product_detail(item_id)
                    if not detail or not detail.get("name"):
                        await _asyncio.sleep(_site_intervals.get("SSG", 1.0))
                        continue

                    if use_max_discount:
                        _raw_cost = detail.get("bestBenefitPrice")
                        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                    _sale_price = detail.get("salePrice", 0)
                    _original_price = detail.get("originalPrice", 0)

                    raw_detail_html = ""
                    detail_imgs = detail.get("detailImages") or []
                    if detail_imgs:
                        raw_detail_html = "\n".join(
                            f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                            for img in detail_imgs
                        )

                    product_data = _build_product_data(
                        detail, item_id, filter_id, "SSG",
                        new_cost, _sale_price, _original_price,
                        raw_cat, cat_parts, raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch()
                except Exception as e:
                    logger.warning(f"[SSG 수집 실패] {item_id}: {e}")
                await _asyncio.sleep(_site_intervals.get("SSG", 1.0))

            await _flush_batch()
            await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})

            return {
                "type": "search", "keyword": keyword, "filter_id": filter_id,
                "total_found": len(all_items), "saved": saved, "enriched": saved,
                "skipped_sold_out": skipped_sold_out,
            }

        else:
            # 단일 상품 URL
            match = re.search(r'itemId=(\d+)', url) or re.search(r'/item/(\d+)', url)
            if not match:
                raise HTTPException(400, "SSG 상품 URL에서 상품번호를 찾을 수 없습니다")
            item_id = match.group(1)

            client = SSGSourcingClient()
            data = await client.get_product_detail(item_id)
            if not data or not data.get("name"):
                raise HTTPException(502, "SSG 상품 조회 실패")

            initial_snapshot = {
                "date": datetime.now(timezone.utc).isoformat(),
                "sale_price": data.get("salePrice", 0),
                "original_price": data.get("originalPrice", 0),
                "options": data.get("options", []),
            }
            sale_status = data.get("saleStatus", "in_stock")
            raw_detail_html = ""
            detail_imgs = data.get("detailImages") or []
            if detail_imgs:
                raw_detail_html = "\n".join(
                    f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                    for img in detail_imgs
                )

            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_stmt = select(CPModel).where(
                CPModel.source_site == "SSG", CPModel.site_product_id == item_id,
            )
            existing_row = (await session.execute(existing_stmt)).scalar_one_or_none()

            product_data = {
                "source_site": "SSG",
                "site_product_id": item_id,
                "name": data.get("name", ""),
                "brand": data.get("brand", ""),
                "original_price": data.get("originalPrice", 0),
                "sale_price": data.get("salePrice", 0),
                "cost": data.get("bestBenefitPrice") or None,
                "images": data.get("images", []),
                "detail_images": data.get("detailImages") or [],
                "options": data.get("options", []),
                "category": data.get("category", ""),
                "category1": data.get("category1", ""),
                "category2": data.get("category2", ""),
                "category3": data.get("category3", ""),
                "category4": data.get("category4", ""),
                "detail_html": raw_detail_html,
                "status": "collected",
                "is_sold_out": sale_status == "sold_out",
                "sale_status": sale_status,
                "free_shipping": data.get("freeShipping", False),
                "same_day_delivery": data.get("sameDayDelivery", False),
                "price_history": [initial_snapshot],
            }

            if existing_row:
                history = list(existing_row.price_history or [])
                history.insert(0, initial_snapshot)
                product_data["price_history"] = _trim_history(history)
                if "tags" not in product_data or not product_data.get("tags"):
                    product_data.pop("tags", None)
                collected = await svc.update_collected_product(existing_row.id, product_data)
                return {"type": "single", "saved": 1, "updated": True, "product": collected}
            else:
                collected = await svc.create_collected_product(product_data)
                return {"type": "single", "saved": 1, "product": collected}

    # ── 롯데ON 수집 ──
    elif site == "LOTTEON":
        import re
        from urllib.parse import urlparse, parse_qs
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        parsed = urlparse(url)
        is_search_url = "/search/" in parsed.path or "q=" in parsed.query

        if is_search_url:
            qs = parse_qs(parsed.query)
            keyword = qs.get("q", [""])[0]
            if not keyword:
                raise HTTPException(400, "검색 URL에서 키워드를 찾을 수 없습니다")

            use_max_discount = qs.get("maxDiscount", [""])[0] == "1"

            # 검색그룹 자동 생성
            search_filter = await svc.create_filter({
                "source_site": "LOTTEON",
                "name": keyword,
                "keyword": url,
                "requested_count": 100,
            })
            filter_id = search_filter.id

            client = LotteonSourcingClient()

            # 기존 수집 수 확인
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_count = await svc.product_repo.count_async(filters={"search_filter_id": filter_id})
            remaining = max(0, 100 - existing_count)
            if remaining <= 0:
                return {"type": "search", "keyword": keyword, "filter_id": filter_id,
                        "message": f"이미 {existing_count}개 수집됨", "saved": 0, "enriched": 0}

            # 검색
            import asyncio as _asyncio
            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(keyword=keyword, page=page, size=40)
                    if not items:
                        break
                    all_items.extend(items)
                    await _asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
                except Exception:
                    break

            if not all_items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            # 중복 필터
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in all_items]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "LOTTEON",
                CPModel.site_product_id.in_(candidate_ids),
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            targets = []
            skipped_sold_out = 0
            for item in all_items:
                if len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    skipped_sold_out += 1
                    continue
                targets.append(site_pid)

            # 상세 수집 + 배치 저장
            saved = 0
            _batch_buf: list[dict] = []
            _BATCH_SIZE = 10

            async def _flush_batch() -> int:
                if not _batch_buf:
                    return 0
                cnt = await svc.bulk_create_products(list(_batch_buf))
                _batch_buf.clear()
                return cnt

            for item_id in targets:
                try:
                    detail = await client.get_product_detail(item_id)
                    if not detail or not detail.get("name"):
                        await _asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
                        continue

                    if use_max_discount:
                        _raw_cost = detail.get("bestBenefitPrice")
                        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                    _sale_price = detail.get("salePrice", 0)
                    _original_price = detail.get("originalPrice", 0)

                    raw_detail_html = ""
                    detail_imgs = detail.get("detailImages") or []
                    if detail_imgs:
                        raw_detail_html = "\n".join(
                            f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                            for img in detail_imgs
                        )

                    product_data = _build_product_data(
                        detail, item_id, filter_id, "LOTTEON",
                        new_cost, _sale_price, _original_price,
                        raw_cat, cat_parts, raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch()
                except Exception as e:
                    logger.warning(f"[LOTTEON 수집 실패] {item_id}: {e}")
                await _asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))

            await _flush_batch()
            await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})

            return {
                "type": "search", "keyword": keyword, "filter_id": filter_id,
                "total_found": len(all_items), "saved": saved, "enriched": saved,
                "skipped_sold_out": skipped_sold_out,
            }

        else:
            # 단일 상품 URL
            match = re.search(r'/product/(LO\d+)', url) or re.search(r'/product/(\d+)', url)
            if not match:
                raise HTTPException(400, "롯데ON 상품 URL에서 상품번호를 찾을 수 없습니다")
            item_id = match.group(1)

            client = LotteonSourcingClient()
            data = await client.get_product_detail(item_id)
            if not data or not data.get("name"):
                raise HTTPException(502, "롯데ON 상품 조회 실패")

            initial_snapshot = {
                "date": datetime.now(timezone.utc).isoformat(),
                "sale_price": data.get("salePrice", 0),
                "original_price": data.get("originalPrice", 0),
                "options": data.get("options", []),
            }
            sale_status = data.get("saleStatus", "in_stock")
            raw_detail_html = ""
            detail_imgs = data.get("detailImages") or []
            if detail_imgs:
                raw_detail_html = "\n".join(
                    f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                    for img in detail_imgs
                )

            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_stmt = select(CPModel).where(
                CPModel.source_site == "LOTTEON", CPModel.site_product_id == item_id,
            )
            existing_row = (await session.execute(existing_stmt)).scalar_one_or_none()

            product_data = {
                "source_site": "LOTTEON",
                "site_product_id": item_id,
                "name": data.get("name", ""),
                "brand": data.get("brand", ""),
                "original_price": data.get("originalPrice", 0),
                "sale_price": data.get("salePrice", 0),
                "cost": data.get("bestBenefitPrice") or None,
                "images": data.get("images", []),
                "detail_images": data.get("detailImages") or [],
                "options": data.get("options", []),
                "category": data.get("category", ""),
                "category1": data.get("category1", ""),
                "category2": data.get("category2", ""),
                "category3": data.get("category3", ""),
                "category4": data.get("category4", ""),
                "detail_html": raw_detail_html,
                "status": "collected",
                "is_sold_out": sale_status == "sold_out",
                "sale_status": sale_status,
                "free_shipping": data.get("freeShipping", False),
                "same_day_delivery": data.get("sameDayDelivery", False),
                "price_history": [initial_snapshot],
            }

            if existing_row:
                history = list(existing_row.price_history or [])
                history.insert(0, initial_snapshot)
                product_data["price_history"] = _trim_history(history)
                if "tags" not in product_data or not product_data.get("tags"):
                    product_data.pop("tags", None)
                collected = await svc.update_collected_product(existing_row.id, product_data)
                return {"type": "single", "saved": 1, "updated": True, "product": collected}
            else:
                collected = await svc.create_collected_product(product_data)
                return {"type": "single", "saved": 1, "product": collected}

    raise HTTPException(400, f"'{site}' 사이트 수집은 아직 지원하지 않습니다")


@router.post("/collect-filter/{filter_id}", status_code=200)
async def collect_by_filter(
    filter_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """검색그룹 기반 재수집 — SSE 스트리밍으로 개별 상품 로그 전송."""
    import json as _json
    from fastapi.responses import StreamingResponse
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    from backend.domain.samba.proxy.kream import KreamClient
    from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient
    from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

    svc = _get_services(session)
    search_filter = await svc.filter_repo.get_async(filter_id)
    if not search_filter:
        raise HTTPException(404, "필터를 찾을 수 없습니다")

    site = search_filter.source_site
    keyword_or_url = search_filter.keyword or search_filter.name

    async def _get_musinsa_cookie() -> str:
        from backend.domain.samba.forbidden.model import SambaSettings
        try:
            result = await session.execute(
                select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
            )
            row = result.scalar_one_or_none()
            return (row.value if row and row.value else "") or ""
        except Exception:
            return ""

    keyword = search_filter.keyword or search_filter.name
    if keyword_or_url and ("http" in keyword_or_url):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(keyword_or_url).query)
        keyword = qs.get("keyword", [keyword])[0]

    def _sse(event: str, data: dict) -> str:
        return f"data: {_json.dumps({**data, 'event': event}, ensure_ascii=False)}\n\n"

    async def _auto_apply_policy() -> str:
        """수집 완료 후 그룹에 정책이 설정되어 있으면 새 상품에 자동 전파."""
        if not search_filter.applied_policy_id:
            return ""
        try:
            from backend.domain.samba.policy.repository import SambaPolicyRepository
            policy_repo = SambaPolicyRepository(session)
            policy = await policy_repo.get_async(search_filter.applied_policy_id)
            policy_data = None
            if policy and policy.pricing:
                pr = policy.pricing if isinstance(policy.pricing, dict) else {}
                policy_data = {
                    "margin_rate": pr.get("marginRate", 15),
                    "shipping_cost": pr.get("shippingCost", 0),
                    "extra_charge": pr.get("extraCharge", 0),
                }
            count = await svc.apply_policy_to_filter_products(
                filter_id, search_filter.applied_policy_id, policy_data
            )
            return f"정책 자동 적용: {count}개 상품"
        except Exception as e:
            logger.error(f"[수집] 정책 자동 전파 실패: {e}")
            return ""

    async def _wrap_stream(inner_stream):
        """수집 스트림 래퍼 — done 이벤트 직전에 정책 자동 전파.

        새 소싱사이트를 추가해도 이 래퍼가 자동으로 정책 전파를 처리한다.
        각 사이트별 스트림 함수에서는 정책 전파를 신경 쓸 필요 없음.
        """
        async for chunk in inner_stream:
            # done 이벤트 감지 → 전송 전에 정책 전파 먼저 실행
            if '"event": "done"' in chunk:
                try:
                    data_str = chunk.split("data: ", 1)[1].strip()
                    data = _json.loads(data_str)
                    saved = data.get("saved", 0)
                    if saved and int(saved) > 0:
                        policy_msg = await _auto_apply_policy()
                        if policy_msg:
                            yield _sse("log", {"message": policy_msg})
                except Exception:
                    pass
            yield chunk

    async def _stream_musinsa():
        import asyncio as _asyncio

        cookie = await _get_musinsa_cookie()
        if not cookie:
            yield _sse("error", {
                "message": "무신사 수집은 로그인(쿠키)이 필요합니다. "
                           "확장앱에서 무신사 로그인 후 다시 시도하세요."
            })
            return
        client = MusinsaClient(cookie=cookie)

        # 요청 상품수 확인 + 기존 수집 수 차감
        requested_count = search_filter.requested_count or 100
        from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
        existing_count = await svc.product_repo.count_async(
            filters={"search_filter_id": filter_id}
        )
        remaining = max(0, requested_count - existing_count)
        if remaining <= 0:
            yield _sse("done", {"saved": 0, "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)"})
            return

        # URL에서 수집 제외 옵션 추출
        _exclude_preorder = False
        _exclude_boutique = False
        _use_max_discount = False
        if keyword_or_url and "http" in keyword_or_url:
            from urllib.parse import urlparse as _up, parse_qs as _pq
            _qs = _pq(_up(keyword_or_url).query)
            _exclude_preorder = _qs.get("excludePreorder", [""])[0] == "1"
            _exclude_boutique = _qs.get("excludeBoutique", [""])[0] == "1"
            _use_max_discount = _qs.get("maxDiscount", [""])[0] == "1"

        yield _sse("log", {"message": f"'{keyword}' 검색 중... (목표 {remaining}개)"})

        from datetime import datetime, timezone
        total_enriched = 0
        total_skipped_preorder = 0
        total_skipped_boutique = 0
        total_skipped_sold_out = 0
        total_saved = 0
        search_page = 1
        no_more_results = False

        # remaining 목표를 채울 때까지 반복 (페이지별 검색 → 저장 → 보강)
        while total_enriched < remaining and not no_more_results and search_page <= 10:
            # 검색
            try:
                data = await client.search_products(keyword=keyword, page=search_page, size=100)
                search_items = data.get("data", [])
                if not search_items:
                    no_more_results = True
                    break
                yield _sse("log", {"message": f"검색 {search_page}페이지 ({len(search_items)}건)"})
                await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌
            except Exception:
                break

            # 중복/품절 필터링
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in search_items]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "MUSINSA",
                CPModel.site_product_id.in_(candidate_ids),  # type: ignore[union-attr]
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            # 중복/품절 필터링 → 수집 대상 상품번호 추출
            targets = []
            for item in search_items:
                if total_saved + len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    total_skipped_sold_out += 1
                    continue
                targets.append(site_pid)

            if not targets:
                search_page += 1
                continue

            yield _sse("log", {"message": f"수집 대상 {len(targets)}건. 상세 수집 중..."})

            # 각 상품 상세 수집 → 성공 시에만 저장 (완전한 데이터만)
            rate_limited = False
            for goods_no in targets:
                try:
                    detail = await client.get_goods_detail(goods_no)
                    if not detail or not detail.get("name"):
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    p_name = detail.get("name", "")[:30]

                    if _exclude_preorder and detail.get("saleStatus") == "preorder":
                        total_skipped_preorder += 1
                        yield _sse("log", {"message": f"  {p_name} — 예약배송 제외"})
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue
                    if _exclude_boutique and detail.get("isBoutique"):
                        total_skipped_boutique += 1
                        yield _sse("log", {"message": f"  {p_name} — 부티끄 제외"})
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    # 최대혜택가 체크 시 bestBenefitPrice, 미체크 시 salePrice
                    if _use_max_discount:
                        _raw_cost = detail.get("bestBenefitPrice")
                        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                    _sale_price = detail.get("salePrice", 0)
                    _original_price = detail.get("originalPrice", 0)

                    raw_detail_html = detail.get("detailHtml", "")
                    if not raw_detail_html:
                        detail_imgs = detail.get("detailImages") or []
                        if detail_imgs:
                            raw_detail_html = "\n".join(
                                f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                                for img in detail_imgs
                            )

                    product_data = _build_product_data(
                        detail, goods_no, filter_id, "MUSINSA",
                        new_cost, _sale_price, _original_price,
                        raw_cat, cat_parts, raw_detail_html,
                    )
                    await svc.create_collected_product(product_data)
                    total_saved += 1
                    total_enriched += 1

                    cost_str = f"₩{int(new_cost):,}" if new_cost else "-"
                    yield _sse("product", {
                        "message": f"  [{total_enriched}/{remaining}] {p_name} — 원가 {cost_str}",
                        "index": total_enriched, "total": remaining,
                    })

                    # 목표 달성 시 즉시 종료
                    if total_enriched >= remaining:
                        break
                except RateLimitError as rle:
                    # 차단 감지 → 인터벌 증가 + SSE 경고
                    current = _site_intervals.get("MUSINSA", 1.0)
                    _site_intervals["MUSINSA"] = min(30.0, current * 2)
                    _site_consecutive_errors["MUSINSA"] = _site_consecutive_errors.get("MUSINSA", 0) + 1
                    if _site_consecutive_errors["MUSINSA"] >= 5:
                        yield _sse("blocked", {"message": f"소싱처 차단으로 수집 일시 중단 (HTTP {rle.status}, 연속 {_site_consecutive_errors['MUSINSA']}회)"})
                        rate_limited = True
                        break
                    yield _sse("warning", {"message": f"차단 감지(HTTP {rle.status}), 속도 조절 중... (인터벌 {_site_intervals['MUSINSA']}초)"})
                    if rle.retry_after > 0:
                        await _asyncio.sleep(rle.retry_after)
                    else:
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                    continue
                except Exception as e:
                    logger.warning(f"[수집 실패] {goods_no}: {e}")
                    yield _sse("log", {"message": f"  {goods_no} — 수집 실패"})
                await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))

            if rate_limited:
                break
            search_page += 1

        await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})

        yield _sse("done", {
            "saved": total_saved,
            "enriched": total_enriched,
            "skipped_sold_out": total_skipped_sold_out,
            "skipped_preorder": total_skipped_preorder,
            "skipped_boutique": total_skipped_boutique,
        })

    if site == "MUSINSA":
        return StreamingResponse(_wrap_stream(_stream_musinsa()), media_type="text/event-stream")

    elif site == "KREAM":
        async def _stream_kream():
            import asyncio as _asyncio
            import re as _re
            from datetime import datetime, timezone

            client = KreamClient()

            # ── 단일 상품 URL 감지 ──
            product_match = _re.search(r'/products/(\d+)', keyword_or_url or '')
            if product_match:
                single_pid = product_match.group(1)
                yield _sse("log", {"message": f"[단일상품] KREAM #{single_pid} 상세 수집 중..."})
                try:
                    raw = await client.get_product_via_extension(single_pid)
                    if isinstance(raw, dict) and raw.get("success") and raw.get("product"):
                        pd = raw["product"]
                    elif isinstance(raw, dict) and raw.get("name"):
                        pd = raw
                    else:
                        pd = None

                    if not pd:
                        yield _sse("done", {"saved": 0, "message": f"KREAM #{single_pid} 상세 데이터 없음"})
                        return

                    opts = pd.get("options", [])
                    cat_str = pd.get("category", "")
                    cat_parts = [c.strip() for c in cat_str.split(">") if c.strip()] if cat_str else []

                    fast_prices = [o.get("kreamFastPrice", 0) for o in opts if o.get("kreamFastPrice", 0) > 0]
                    general_prices = [o.get("kreamGeneralPrice", 0) for o in opts if o.get("kreamGeneralPrice", 0) > 0]
                    sale_p = min(fast_prices) if fast_prices else (pd.get("salePrice") or 0)
                    cost_p = min(general_prices) if general_prices else sale_p

                    snapshot = _build_kream_price_snapshot(sale_p, pd.get("originalPrice") or sale_p, cost_p, opts)

                    _kream_name = pd.get("nameKo") or pd.get("name", "")
                    product_data = {
                        "source_site": "KREAM",
                        "site_product_id": single_pid,
                        "search_filter_id": filter_id,
                        "name": _kream_name,
                        "name_en": pd.get("nameEn", ""),
                        "brand": pd.get("brand", ""),
                        "original_price": pd.get("originalPrice") or sale_p,
                        "sale_price": sale_p,
                        "cost": cost_p,
                        "images": pd.get("images", []),
                        "options": opts,
                        "category": cat_str,
                        "category1": cat_parts[0] if len(cat_parts) > 0 else "",
                        "category2": cat_parts[1] if len(cat_parts) > 1 else "",
                        "category3": cat_parts[2] if len(cat_parts) > 2 else "",
                        "category4": cat_parts[3] if len(cat_parts) > 3 else "",
                        "similar_no": None,
                        "color": parse_color_from_name(_kream_name),
                        "group_key": generate_group_key(
                            brand=pd.get("brand", ""),
                            similar_no=None,
                            style_code=pd.get("styleCode", ""),
                            name=_kream_name,
                        ),
                        "status": "collected",
                        "kream_data": {
                            "styleCode": pd.get("styleCode", ""),
                            "nameKo": pd.get("nameKo", ""),
                            "nameEn": pd.get("nameEn", ""),
                        },
                        "price_history": [snapshot],
                    }

                    await svc.create_collected_product(product_data)
                    yield _sse("product", {
                        "message": f"  [1/1] {product_data['name'][:30]} — ₩{sale_p:,}",
                        "index": 1, "total": 1,
                    })
                except Exception as e:
                    yield _sse("log", {"message": f"  KREAM #{single_pid} — 수집 실패: {str(e)[:60]}"})

                await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})
                yield _sse("done", {"saved": 1})
                return

            # ── 검색 기반 수집 ──
            requested_count = search_filter.requested_count or 100
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_count = await svc.product_repo.count_async(
                filters={"search_filter_id": filter_id}
            )
            remaining = max(0, requested_count - existing_count)
            if remaining <= 0:
                yield _sse("done", {"saved": 0, "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)"})
                return

            yield _sse("log", {"message": f"[검색] KREAM '{keyword}' 상품목록 조회 중... (목표 {remaining}개)"})
            yield _sse("log", {"message": "[검색] 확장앱으로 검색 페이지를 열고 있습니다..."})

            try:
                # SSR/API 차단으로 확장앱 방식 사용
                items = await client.search_via_extension(keyword)
            except Exception as e:
                yield _sse("done", {"saved": 0, "message": f"KREAM 검색 실패: {str(e)}. 웨일 브라우저 확장앱이 실행 중인지 확인하세요."})
                return

            items_list = items if isinstance(items, list) else []
            if not items_list:
                yield _sse("done", {"saved": 0, "message": f"'{keyword}' 검색 결과가 없습니다"})
                return

            yield _sse("log", {"message": f"[검색] 상품목록 {len(items_list)}건 조회 완료. 수집 시작..."})

            # 중복 체크
            candidate_ids = [str(item.get("siteProductId") or item.get("id") or "") for item in items_list]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "KREAM",
                CPModel.site_product_id.in_(candidate_ids),  # type: ignore[union-attr]
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            saved = 0
            saved_products = []
            for item in items_list:
                if saved >= remaining:
                    break
                site_pid = str(item.get("siteProductId") or item.get("id") or "")
                if not site_pid or site_pid in existing_ids:
                    continue

                sale_price = item.get("salePrice") or item.get("retailPrice") or 0
                img_list = item.get("images") or ([item["imageUrl"]] if item.get("imageUrl") else [])
                p_name = item.get("name", "")

                product_data = {
                    "source_site": "KREAM",
                    "site_product_id": site_pid,
                    "search_filter_id": filter_id,
                    "name": p_name,
                    "brand": item.get("brand", ""),
                    "original_price": item.get("originalPrice") or sale_price,
                    "sale_price": sale_price,
                    "cost": sale_price,
                    "images": img_list,
                    "similar_no": None,
                    "group_key": generate_group_key(
                        brand=item.get("brand", ""),
                        similar_no=None,
                        style_code=item.get("styleCode", ""),
                        name=p_name,
                    ),
                    "status": "collected",
                    "price_history": [{
                        "date": datetime.now(timezone.utc).isoformat(),
                        "sale_price": sale_price,
                        "original_price": item.get("originalPrice") or sale_price,
                        "cost": sale_price,
                        "options": [],
                    }],
                }

                try:
                    created = await svc.create_collected_product(product_data)
                    saved += 1
                    saved_products.append(created)
                    yield _sse("product", {
                        "message": f"  [수집 {saved}/{remaining}] {p_name[:30]} — ₩{sale_price:,}",
                        "index": saved, "total": remaining,
                    })
                except Exception as e:
                    yield _sse("log", {"message": f"  {p_name[:30]} — 저장 실패: {e}"})
                await _asyncio.sleep(0.3)

            # 상세 보강: 확장앱으로 사이즈별 빠른배송/일반배송 가격 수집
            if saved_products:
                yield _sse("log", {"message": f"사이즈별 가격 수집 시작... ({len(saved_products)}건)"})
                yield _sse("log", {"message": "확장앱이 각 상품 페이지를 열어 사이즈별 가격을 수집합니다."})
                enriched = 0
                for idx, product in enumerate(saved_products):
                    try:
                        raw = await client.get_product_via_extension(product.site_product_id)
                        # 확장앱 응답: { success: true, product: {...} } 또는 직접 {...}
                        if isinstance(raw, dict) and raw.get("success") and raw.get("product"):
                            pd = raw["product"]
                        elif isinstance(raw, dict) and raw.get("name"):
                            pd = raw
                        else:
                            pd = None

                        if pd:
                            opts = pd.get("options", [])
                            cat_str = pd.get("category", "")
                            cat_parts = [c.strip() for c in cat_str.split(">") if c.strip()] if cat_str else []

                            # 크림 가격: 할인가=빠른배송 최저가, 원가=일반배송 최저가
                            fast_prices = [o.get("kreamFastPrice", 0) for o in opts if o.get("kreamFastPrice", 0) > 0]
                            general_prices = [o.get("kreamGeneralPrice", 0) for o in opts if o.get("kreamGeneralPrice", 0) > 0]
                            sale_p = min(fast_prices) if fast_prices else (pd.get("salePrice") or product.sale_price)
                            cost_p = min(general_prices) if general_prices else sale_p

                            enrich_updates = {
                                "name": pd.get("nameKo") or pd.get("name") or product.name,
                                "name_en": pd.get("nameEn", ""),
                                "brand": pd.get("brand") or product.brand,
                                "original_price": pd.get("originalPrice") or product.original_price,
                                "sale_price": sale_p,  # 할인가 = 빠른배송 최저가
                                "cost": cost_p,  # 원가 = 일반배송 최저가
                                "images": pd.get("images") or product.images,
                                "options": opts if opts else product.options,
                                "category": cat_str,
                                "category1": cat_parts[0] if len(cat_parts) > 0 else "",
                                "category2": cat_parts[1] if len(cat_parts) > 1 else "",
                                "category3": cat_parts[2] if len(cat_parts) > 2 else "",
                                "category4": cat_parts[3] if len(cat_parts) > 3 else "",
                                "kream_data": {
                                    "styleCode": pd.get("styleCode", ""),
                                    "nameKo": pd.get("nameKo", ""),
                                    "nameEn": pd.get("nameEn", ""),
                                },
                            }

                            # 가격이력 스냅샷 추가 (최대 200건)
                            enrich_snapshot = _build_kream_price_snapshot(
                                sale_p, pd.get("originalPrice") or product.original_price, cost_p, opts
                            )
                            history = list(product.price_history or [])
                            history.insert(0, enrich_snapshot)
                            enrich_updates["price_history"] = _trim_history(history)

                            await svc.update_collected_product(product.id, enrich_updates)
                            enriched += 1
                            opt_count = len(opts)
                            fast_count = sum(1 for o in opts if o.get("kreamFastPrice", 0) > 0)
                            yield _sse("product", {
                                "message": f"  [{idx+1}/{len(saved_products)}] {product.name[:25]} — {opt_count}개 사이즈 (빠른배송 {fast_count}개)",
                                "index": idx + 1, "total": len(saved_products),
                            })
                        else:
                            yield _sse("log", {"message": f"  [{idx+1}/{len(saved_products)}] {product.name[:25]} — 상세 데이터 없음"})
                    except Exception as e:
                        err_msg = str(e)[:60]
                        yield _sse("log", {"message": f"  [{idx+1}/{len(saved_products)}] {product.name[:25]} — 보강 실패: {err_msg}"})
                    await _asyncio.sleep(1.0)

            await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})
            yield _sse("done", {"saved": saved, "total_found": len(items_list), "skipped_duplicates": len(existing_ids)})

        return StreamingResponse(_wrap_stream(_stream_kream()), media_type="text/event-stream")

    # ── SSG 수집 (collect-by-filter) ──
    elif site == "SSG":
        async def _stream_ssg():
            import asyncio as _asyncio
            from datetime import datetime, timezone

            client = SSGSourcingClient()

            # 요청 상품수 확인 + 기존 수집 수 차감
            requested_count = search_filter.requested_count or 100
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_count = await svc.product_repo.count_async(
                filters={"search_filter_id": filter_id}
            )
            remaining = max(0, requested_count - existing_count)
            if remaining <= 0:
                yield _sse("done", {"saved": 0, "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)"})
                return

            # URL에서 옵션 추출
            _use_max_discount = False
            if keyword_or_url and "http" in keyword_or_url:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _qs = _pq(_up(keyword_or_url).query)
                _use_max_discount = _qs.get("maxDiscount", [""])[0] == "1"

            yield _sse("log", {"message": f"[SSG] '{keyword}' 검색 중... (목표 {remaining}개)"})

            # 검색
            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(keyword=keyword, page=page, size=40)
                    if not items:
                        break
                    all_items.extend(items)
                    yield _sse("log", {"message": f"  페이지 {page}: {len(items)}개 발견"})
                    await _asyncio.sleep(_site_intervals.get("SSG", 1.0))
                except Exception as e:
                    yield _sse("log", {"message": f"  페이지 {page} 검색 실패: {str(e)[:50]}"})
                    break

            if not all_items:
                yield _sse("done", {"saved": 0, "message": "검색 결과가 없습니다"})
                return

            # 중복 필터
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in all_items]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "SSG",
                CPModel.site_product_id.in_(candidate_ids),
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            targets = []
            skipped_sold_out = 0
            for item in all_items:
                if len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    skipped_sold_out += 1
                    continue
                targets.append(site_pid)

            yield _sse("log", {"message": f"총 {len(all_items)}개 중 {len(targets)}개 수집 대상 (중복 {len(existing_ids)}개, 품절 {skipped_sold_out}개 제외)"})

            # 상세 수집 + 배치 저장
            saved = 0
            _batch_buf: list[dict] = []
            _BATCH_SIZE = 10

            async def _flush_batch_ssg() -> int:
                if not _batch_buf:
                    return 0
                cnt = await svc.bulk_create_products(list(_batch_buf))
                _batch_buf.clear()
                return cnt

            for idx, item_id in enumerate(targets):
                try:
                    detail = await client.get_product_detail(item_id)
                    if not detail or not detail.get("name"):
                        yield _sse("log", {"message": f"  [{idx+1}/{len(targets)}] #{item_id} — 상세 없음"})
                        await _asyncio.sleep(_site_intervals.get("SSG", 1.0))
                        continue

                    if _use_max_discount:
                        _raw_cost = detail.get("bestBenefitPrice")
                        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                    _sale_price = detail.get("salePrice", 0)
                    _original_price = detail.get("originalPrice", 0)

                    raw_detail_html = ""
                    detail_imgs = detail.get("detailImages") or []
                    if detail_imgs:
                        raw_detail_html = "\n".join(
                            f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                            for img in detail_imgs
                        )

                    product_data = _build_product_data(
                        detail, item_id, filter_id, "SSG",
                        new_cost, _sale_price, _original_price,
                        raw_cat, cat_parts, raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    yield _sse("log", {"message": f"  [{idx+1}/{len(targets)}] {detail.get('name', '')[:30]} — 수집 완료"})
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch_ssg()
                except Exception as e:
                    yield _sse("log", {"message": f"  [{idx+1}/{len(targets)}] #{item_id} — 실패: {str(e)[:50]}"})
                await _asyncio.sleep(_site_intervals.get("SSG", 1.0))

            await _flush_batch_ssg()
            await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})
            yield _sse("done", {
                "saved": saved,
                "total_found": len(all_items),
                "skipped_sold_out": skipped_sold_out,
                "skipped_duplicates": len(existing_ids),
            })

        return StreamingResponse(_wrap_stream(_stream_ssg()), media_type="text/event-stream")

    # ── 롯데ON 수집 (collect-by-filter) ──
    elif site == "LOTTEON":
        async def _stream_lotteon():
            import asyncio as _asyncio
            from datetime import datetime, timezone

            client = LotteonSourcingClient()

            # 요청 상품수 확인 + 기존 수집 수 차감
            requested_count = search_filter.requested_count or 100
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            existing_count = await svc.product_repo.count_async(
                filters={"search_filter_id": filter_id}
            )
            remaining = max(0, requested_count - existing_count)
            if remaining <= 0:
                yield _sse("done", {"saved": 0, "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)"})
                return

            # URL에서 옵션 추출
            _use_max_discount = False
            if keyword_or_url and "http" in keyword_or_url:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _qs = _pq(_up(keyword_or_url).query)
                _use_max_discount = _qs.get("maxDiscount", [""])[0] == "1"

            yield _sse("log", {"message": f"[LOTTEON] '{keyword}' 검색 중... (목표 {remaining}개)"})

            # 검색
            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(keyword=keyword, page=page, size=40)
                    if not items:
                        break
                    all_items.extend(items)
                    yield _sse("log", {"message": f"  페이지 {page}: {len(items)}개 발견"})
                    await _asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
                except Exception as e:
                    yield _sse("log", {"message": f"  페이지 {page} 검색 실패: {str(e)[:50]}"})
                    break

            if not all_items:
                yield _sse("done", {"saved": 0, "message": "검색 결과가 없습니다"})
                return

            # 중복 필터
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in all_items]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "LOTTEON",
                CPModel.site_product_id.in_(candidate_ids),
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            targets = []
            skipped_sold_out = 0
            for item in all_items:
                if len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    skipped_sold_out += 1
                    continue
                targets.append(site_pid)

            yield _sse("log", {"message": f"총 {len(all_items)}개 중 {len(targets)}개 수집 대상 (중복 {len(existing_ids)}개, 품절 {skipped_sold_out}개 제외)"})

            # 상세 수집 + 배치 저장
            saved = 0
            _batch_buf: list[dict] = []
            _BATCH_SIZE = 10

            async def _flush_batch_lotteon() -> int:
                if not _batch_buf:
                    return 0
                cnt = await svc.bulk_create_products(list(_batch_buf))
                _batch_buf.clear()
                return cnt

            for idx, item_id in enumerate(targets):
                try:
                    detail = await client.get_product_detail(item_id)
                    if not detail or not detail.get("name"):
                        yield _sse("log", {"message": f"  [{idx+1}/{len(targets)}] #{item_id} — 상세 없음"})
                        await _asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
                        continue

                    if _use_max_discount:
                        _raw_cost = detail.get("bestBenefitPrice")
                        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                    _sale_price = detail.get("salePrice", 0)
                    _original_price = detail.get("originalPrice", 0)

                    raw_detail_html = ""
                    detail_imgs = detail.get("detailImages") or []
                    if detail_imgs:
                        raw_detail_html = "\n".join(
                            f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                            for img in detail_imgs
                        )

                    product_data = _build_product_data(
                        detail, item_id, filter_id, "LOTTEON",
                        new_cost, _sale_price, _original_price,
                        raw_cat, cat_parts, raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    yield _sse("log", {"message": f"  [{idx+1}/{len(targets)}] {detail.get('name', '')[:30]} — 수집 완료"})
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch_lotteon()
                except Exception as e:
                    yield _sse("log", {"message": f"  [{idx+1}/{len(targets)}] #{item_id} — 실패: {str(e)[:50]}"})
                await _asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))

            await _flush_batch_lotteon()
            await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})
            yield _sse("done", {
                "saved": saved,
                "total_found": len(all_items),
                "skipped_sold_out": skipped_sold_out,
                "skipped_duplicates": len(existing_ids),
            })

        return StreamingResponse(_wrap_stream(_stream_lotteon()), media_type="text/event-stream")

    # ── 패션플러스 / Nike / Adidas (백엔드 직접 API) ──
    DIRECT_API_SITES = {"FashionPlus", "Nike", "Adidas"}
    # ── 확장앱 기반 사이트 ──
    EXTENSION_SITES = {"ABCmart", "GrandStage", "OKmall", "GSShop", "ElandMall", "SSF"}

    if site in DIRECT_API_SITES or site in EXTENSION_SITES:
        async def _stream_generic():
            import asyncio as _asyncio
            from datetime import datetime, timezone

            yield _sse("log", {"message": f"[{site}] 수집 시작..."})

            keyword = keyword_or_url or ""
            # URL에서 키워드 추출
            if keyword.startswith("http"):
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(keyword)
                qs = parse_qs(parsed.query)
                keyword = (
                    qs.get("keyword", qs.get("searchWord", qs.get("q",
                    qs.get("query", qs.get("kwd", qs.get("tq", [""]))))))[0]
                )

            if not keyword:
                yield _sse("done", {"saved": 0, "message": "검색 키워드가 없습니다."})
                return

            yield _sse("log", {"message": f"[{site}] 검색 키워드: '{keyword}'"})

            try:
                if site in DIRECT_API_SITES:
                    # 직접 API 호출
                    client = None
                    if site == "FashionPlus":
                        from backend.domain.samba.proxy.fashionplus import FashionPlusClient
                        client = FashionPlusClient()
                    elif site == "Nike":
                        from backend.domain.samba.proxy.nike import NikeClient
                        client = NikeClient()
                    elif site == "Adidas":
                        from backend.domain.samba.proxy.adidas import AdidasClient
                        client = AdidasClient()

                    result = await client.search(keyword)
                    items_list = result.get("products", [])
                else:
                    # 확장앱 큐 기반
                    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
                    yield _sse("log", {"message": f"[{site}] 확장앱에 수집 요청 중... (최대 60초 대기)"})
                    request_id, future = SourcingQueue.add_search_job(site, keyword)
                    try:
                        result = await _asyncio.wait_for(future, timeout=60)
                    except _asyncio.TimeoutError:
                        SourcingQueue.resolvers.pop(request_id, None)
                        yield _sse("done", {"saved": 0, "message": "확장앱 응답 타임아웃. 확장앱이 실행 중인지 확인하세요."})
                        return
                    items_list = result.get("products", [])

                yield _sse("log", {"message": f"[{site}] {len(items_list)}건 검색됨"})

                saved = 0
                target = min(len(items_list), search_filter.requested_count or 100)
                for item in items_list[:target]:
                    p_name = item.get("name", "")
                    p_id = str(item.get("site_product_id", ""))
                    sale_price = int(item.get("sale_price", 0))
                    original_price = int(item.get("original_price", 0)) or sale_price

                    if not p_name and not sale_price:
                        continue

                    # 중복 체크
                    if p_id:
                        existing = await svc.product_repo.find_by_site_product_id(site, p_id)
                        if existing:
                            continue

                    images = item.get("images", [])
                    product_data = {
                        "source_site": site,
                        "search_filter_id": filter_id,
                        "site_product_id": p_id,
                        "name": p_name,
                        "brand": item.get("brand", ""),
                        "original_price": original_price,
                        "sale_price": sale_price,
                        "cost": sale_price,
                        "images": images,
                        "options": item.get("options", []),
                        "category": item.get("category", ""),
                        "category1": item.get("category1", ""),
                        "category2": item.get("category2", ""),
                        "category3": item.get("category3", ""),
                        "detail_html": item.get("detail_html", ""),
                        "similar_no": None,
                        "group_key": generate_group_key(
                            brand=item.get("brand", ""),
                            similar_no=None,
                            style_code=item.get("style_code", ""),
                            name=p_name,
                        ),
                        "status": "collected",
                        "price_history": [{
                            "date": datetime.now(timezone.utc).isoformat(),
                            "sale_price": sale_price,
                            "original_price": original_price,
                            "cost": sale_price,
                        }],
                    }
                    try:
                        await svc.create_collected_product(product_data)
                        saved += 1
                        yield _sse("product", {
                            "message": f"  [{saved}/{target}] {p_name[:30]} — ₩{sale_price:,}",
                            "index": saved, "total": target,
                        })
                    except Exception as e:
                        yield _sse("log", {"message": f"  {p_name[:30]} — 저장 실패: {e}"})
                    await _asyncio.sleep(0.1)

                await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})
                yield _sse("done", {"saved": saved, "total_found": len(items_list)})

            except Exception as e:
                yield _sse("done", {"saved": 0, "message": f"수집 실패: {str(e)}"})

        return StreamingResponse(_wrap_stream(_stream_generic()), media_type="text/event-stream")

    return StreamingResponse(
        (f"data: {__import__('json').dumps({'event': 'done', 'saved': 0, 'message': f'{site} 수집 미지원'}, ensure_ascii=False)}\n\n" for _ in [1]),
        media_type="text/event-stream",
    )


@router.post("/collect-by-keyword", status_code=201)
async def collect_by_keyword(
    body: CollectByKeywordRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """키워드로 소싱사이트 검색 → 결과 반환 (저장은 별도)."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    from backend.domain.samba.proxy.kream import KreamClient

    if body.source_site == "MUSINSA":
        from backend.domain.samba.forbidden.repository import SambaSettingsRepository
        settings_repo = SambaSettingsRepository(session)
        cookie_setting = await settings_repo.get_async("musinsa_cookie")
        cookie = cookie_setting.value if cookie_setting and hasattr(cookie_setting, 'value') else ""

        if not cookie:
            raise HTTPException(
                400,
                "무신사 수집은 로그인(쿠키)이 필요합니다. "
                "확장앱에서 무신사 로그인 후 다시 시도하세요.",
            )

        client = MusinsaClient(cookie=cookie)
        data = await client.search_products(
            keyword=body.keyword, page=body.page, size=body.size
        )
        return data

    elif body.source_site == "KREAM":
        client = KreamClient()
        data = await client.search(body.keyword, body.size)
        return {"success": True, "data": data}

    raise HTTPException(400, f"'{body.source_site}' 키워드 검색은 아직 지원하지 않습니다")


@router.post("/enrich/{product_id}")
async def enrich_product(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """수집 상품의 상세 정보를 소싱사이트 API에서 보강 (카테고리, 옵션, 상세이미지 등)."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    from backend.domain.samba.forbidden.model import SambaSettings
    from sqlmodel import select

    svc = _get_services(session)
    product = await svc.get_collected_product(product_id)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다")

    if product.source_site == "MUSINSA" and product.site_product_id:
        # 무신사 쿠키 로드
        cookie = ""
        try:
            result = await session.execute(
                select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
            )
            row = result.scalar_one_or_none()
            cookie = (row.value if row and row.value else "") or ""
        except Exception:
            pass

        client = MusinsaClient(cookie=cookie)
        try:
            detail = await client.get_goods_detail(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"무신사 상세 조회 실패: {str(e)}")

        if not detail or not detail.get("name"):
            raise HTTPException(502, "무신사 상세 조회 실패: 데이터 없음")

        # get_goods_detail은 { category: "키즈 > ...", category1: "키즈", ... } 형태로 반환
        from datetime import datetime, timezone

        # 가격 0 허용: None이 아닌 경우에만 업데이트, 0도 유효한 값으로 처리
        api_sale = detail.get("salePrice")
        api_original = detail.get("originalPrice")
        new_sale_price = api_sale if api_sale is not None else product.sale_price
        new_original_price = api_original if api_original is not None else product.original_price

        new_sale_status = detail.get("saleStatus", "in_stock")
        # 최대혜택가: best_benefit_price → cost 컬럼에 저장 (0은 None으로 처리)
        _raw_cost = detail.get("bestBenefitPrice")
        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else None
        # 가격/재고만 업데이트 (카테고리, 브랜드, 상세HTML 등은 변경하지 않음)
        updates = {
            "original_price": new_original_price,
            "sale_price": new_sale_price,
            "cost": new_cost,
            "is_sold_out": new_sale_status == "sold_out",
            "sale_status": new_sale_status,
        }

        # 가격 변동 추적
        if new_sale_price != product.sale_price:
            updates["price_before_change"] = product.sale_price
            updates["price_changed_at"] = datetime.now(timezone.utc)

        # 가격/옵션 이력 스냅샷 추가 (최신순, 최대 200건)
        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sale_price": new_sale_price,
            "original_price": new_original_price,
            "cost": new_cost,
            "options": detail.get("options", []),
        }
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        # 옵션 보강
        if detail.get("options"):
            updates["options"] = detail["options"]

        # 이미지 보강
        if detail.get("images"):
            updates["images"] = detail["images"]

        updated = await svc.update_collected_product(product_id, updates)
        return {"success": True, "enriched_fields": list(updates.keys()), "product": updated}

    if product.source_site == "KREAM" and product.site_product_id:
        from backend.domain.samba.proxy.kream import KreamClient
        from datetime import datetime, timezone

        client = KreamClient()
        try:
            raw = await client.get_product_via_extension(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"KREAM 상세 조회 실패: {str(e)}")

        if isinstance(raw, dict) and raw.get("success") and raw.get("product"):
            pd = raw["product"]
        elif isinstance(raw, dict) and raw.get("name"):
            pd = raw
        else:
            raise HTTPException(502, "KREAM 상세 조회 실패: 데이터 없음")

        opts = pd.get("options", [])
        cat_str = pd.get("category", "")
        cat_parts = [c.strip() for c in cat_str.split(">") if c.strip()] if cat_str else []

        fast_prices = [o.get("kreamFastPrice", 0) for o in opts if o.get("kreamFastPrice", 0) > 0]
        general_prices = [o.get("kreamGeneralPrice", 0) for o in opts if o.get("kreamGeneralPrice", 0) > 0]
        sale_p = min(fast_prices) if fast_prices else (pd.get("salePrice") or product.sale_price)
        cost_p = min(general_prices) if general_prices else sale_p

        # 가격재고업데이트: 가격/재고(옵션)만 갱신, 상품명/브랜드/이미지/카테고리 스킵
        updates = {
            "original_price": pd.get("originalPrice") or product.original_price,
            "sale_price": sale_p,
            "cost": cost_p,
            "options": opts if opts else product.options,
        }

        # 가격이력 스냅샷 추가 (최대 200건)
        snapshot = _build_kream_price_snapshot(
            sale_p, pd.get("originalPrice") or product.original_price, cost_p, opts
        )
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        updated = await svc.update_collected_product(product_id, updates)
        return {"success": True, "enriched_fields": list(updates.keys()), "product": updated}

    raise HTTPException(400, f"'{product.source_site}' 상세 보강은 아직 지원하지 않습니다")


@router.post("/enrich-all")
async def enrich_all_products(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """카테고리가 비어있는 모든 MUSINSA 수집 상품의 상세 정보를 일괄 보강."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    from backend.domain.samba.forbidden.model import SambaSettings
    from sqlmodel import select
    import asyncio

    svc = _get_services(session)
    all_products = await svc.list_collected_products(skip=0, limit=1000)

    # 카테고리 없는 MUSINSA 상품만
    targets = [p for p in all_products
               if p.source_site == "MUSINSA" and p.site_product_id and not p.category1]

    if not targets:
        return {"enriched": 0, "message": "보강할 상품이 없습니다"}

    # 쿠키 로드
    cookie = ""
    try:
        result = await session.execute(
            select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
        )
        row = result.scalar_one_or_none()
        cookie = (row.value if row and row.value else "") or ""
    except Exception:
        pass

    client = MusinsaClient(cookie=cookie)
    enriched = 0

    for product in targets:
        try:
            detail = await client.get_goods_detail(product.site_product_id)
            if not detail or not detail.get("name"):
                continue

            new_sale_status = detail.get("saleStatus", "in_stock")
            api_sale = detail.get("salePrice")
            api_original = detail.get("originalPrice")
            new_sale_price = api_sale if api_sale is not None else product.sale_price
            new_original_price = api_original if api_original is not None else product.original_price
            _raw_cost = detail.get("bestBenefitPrice")
            new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else None

            updates = {
                "category": detail.get("category") or product.category,
                "category1": detail.get("category1") or product.category1,
                "category2": detail.get("category2") or product.category2,
                "category3": detail.get("category3") or product.category3,
                "category4": detail.get("category4") or product.category4,
                "brand": detail.get("brand") or product.brand,
                "original_price": new_original_price,
                "sale_price": new_sale_price,
                "cost": new_cost,
                # preorder(판매예정)는 품절이 아님
                "is_sold_out": new_sale_status == "sold_out",
                "sale_status": new_sale_status,
            }

            # 가격 변동 추적
            if new_sale_price != product.sale_price:
                from datetime import datetime, timezone as tz
                updates["price_before_change"] = product.sale_price
                updates["price_changed_at"] = datetime.now(tz.utc)

            # 가격/옵션 이력 스냅샷 추가 (최신순, 최대 200건)
            from datetime import datetime, timezone as tz
            snapshot = {
                "date": datetime.now(tz.utc).isoformat(),
                "sale_price": new_sale_price,
                "original_price": new_original_price,
                "cost": new_cost,
                "options": detail.get("options", []),
            }
            history = list(product.price_history or [])
            history.insert(0, snapshot)
            updates["price_history"] = _trim_history(history)

            if detail.get("options"):
                updates["options"] = detail["options"]
            if detail.get("images"):
                updates["images"] = detail["images"]

            await svc.update_collected_product(product.id, updates)
            enriched += 1

            # 적응형 인터벌: 차단 감지 시 자동 증가
            await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
        except Exception:
            continue

    return {"enriched": enriched, "total_targets": len(targets)}


# ══════════════════════════════════════════════════════════════
# 재고/가격 변동 모니터링 — 벌크 갱신 + 스케줄러
# ══════════════════════════════════════════════════════════════


class RefreshRequest(BaseModel):
    product_ids: Optional[List[str]] = None
    search_filter_ids: Optional[List[str]] = None  # 선택된 그룹(검색필터) ID
    priority: Optional[str] = None  # hot / warm / cold
    auto_retransmit: bool = True


@router.post("/products/refresh")
async def refresh_products(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """벌크 재크롤링 — 소싱처에서 최신 가격/재고 재수집 후 자동 업데이트."""
    from backend.domain.samba.collector.refresher import (
        refresh_products_bulk,
    )
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    repo = SambaCollectedProductRepository(session)

    # 대상 상품 조회 (배치 쿼리)
    if body.product_ids:
        from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
        _stmt = select(_CP).where(_CP.id.in_(body.product_ids))
        _result = await session.execute(_stmt)
        products = list(_result.scalars().all())
    elif body.search_filter_ids:
        # 선택된 그룹의 상품만 조회
        products = []
        for sf_id in body.search_filter_ids:
            group_products = await repo.filter_by_async(search_filter_id=sf_id, limit=10000)
            products.extend(group_products)
    elif body.priority:
        # 우선순위 기반 조회
        from sqlmodel import select as sel
        from backend.domain.samba.collector.model import SambaCollectedProduct
        stmt = sel(SambaCollectedProduct).where(
            SambaCollectedProduct.monitor_priority == body.priority
        ).limit(500)
        result = await session.execute(stmt)
        products = list(result.scalars().all())
    else:
        # 전체 (최대 500건)
        products = await repo.list_async(skip=0, limit=500, order_by="-updated_at")

    if not products:
        return {
            "total": 0, "refreshed": 0, "changed": 0,
            "sold_out": 0, "retransmitted": 0,
            "needs_extension": [], "errors": 0,
        }

    # 벌크 갱신 실행
    results, summary = await refresh_products_bulk(products)

    # 모니터링 서비스 초기화
    from backend.domain.samba.warroom.service import SambaMonitorService
    monitor = SambaMonitorService(session)

    # 상품 Map (재전송/품절 처리에서 재조회 방지)
    product_map = {p.id: p for p in products}

    # 변동 감지된 상품 DB 업데이트
    now = datetime.now(timezone.utc)
    changed_ids: list[str] = []
    soldout_ids: list[str] = []

    for r in results:
        if r.error:
            # 에러 카운트 증가 — product_map 활용 (N+1 제거)
            product = product_map.get(r.product_id)
            if product:
                await repo.update_async(
                    r.product_id,
                    refresh_error_count=(product.refresh_error_count or 0) + 1,
                    last_refreshed_at=now,
                )
                # 모니터링: 갱신 에러
                await monitor.emit(
                    "refresh_error", "warning",
                    summary=f"갱신 실패 — {product.name[:30] if product.name else r.product_id}",
                    source_site=getattr(product, "source_site", None),
                    product_id=r.product_id,
                    product_name=getattr(product, "name", None),
                    detail={"error": r.error},
                )
            continue
        if r.needs_extension:
            # 모니터링: 확장앱 타임아웃
            await monitor.emit(
                "extension_timeout", "warning",
                summary=f"KREAM 확장앱 타임아웃 — {r.product_id}",
                source_site="KREAM",
                product_id=r.product_id,
            )
            continue

        # 상품 조회 — product_map 활용 (N+1 제거)
        product = product_map.get(r.product_id)
        if not product:
            continue

        # 갱신 시각 업데이트 + 에러 카운트 리셋
        updates: dict = {
            "last_refreshed_at": now,
            "refresh_error_count": 0,
        }

        # 가격이력 스냅샷 — 변동 여부와 관계없이 항상 기록
        snapshot: dict = {
            "date": now.isoformat(),
            "source": "refresh",
            "sale_price": r.new_sale_price if r.new_sale_price is not None else product.sale_price,
            "original_price": r.new_original_price if r.new_original_price is not None else product.original_price,
            "cost": r.new_cost if r.new_cost is not None else product.cost,
            "sale_status": r.new_sale_status,
            "changed": r.changed,
        }
        # KREAM 옵션별 가격도 기록
        if r.new_options:
            snapshot["options"] = r.new_options
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        # 이미지/소재/색상 — 기존에 비어있고 편집 이력 없으면 갱신
        _tags = product.tags or []
        _img_edited = "__img_edited__" in _tags or "__img_filtered__" in _tags
        if r.new_images and not product.images and not _img_edited:
            updates["images"] = r.new_images
        if r.new_detail_images and not getattr(product, "detail_images", None) and not _img_edited:
            updates["detail_images"] = r.new_detail_images
        if r.new_material and not getattr(product, "material", None):
            updates["material"] = r.new_material
        if r.new_color and not getattr(product, "color", None):
            updates["color"] = r.new_color
        # 배송 정보 항상 갱신
        if r.new_free_shipping is not None:
            updates["free_shipping"] = r.new_free_shipping
        if r.new_same_day_delivery is not None:
            updates["same_day_delivery"] = r.new_same_day_delivery

        if r.changed:
            if r.new_sale_price is not None:
                updates["sale_price"] = r.new_sale_price
            if r.new_original_price is not None:
                updates["original_price"] = r.new_original_price
            if r.new_cost is not None:
                updates["cost"] = r.new_cost
            if r.new_options is not None:
                updates["options"] = r.new_options

            updates["sale_status"] = r.new_sale_status
            updates["is_sold_out"] = r.new_sale_status == "sold_out"

            # 가격 변동 추적
            old_price = product.sale_price or 0
            new_price = r.new_sale_price or 0
            if new_price != old_price:
                updates["price_before_change"] = old_price
                updates["price_changed_at"] = now
                # 모니터링: 가격 변동
                diff_pct = round((new_price - old_price) / old_price * 100, 1) if old_price else 0
                await monitor.emit(
                    "price_changed", "info",
                    summary=f"가격 변동 — {product.name[:30] if product.name else ''} ₩{int(old_price):,}→₩{int(new_price):,}",
                    source_site=product.source_site,
                    product_id=r.product_id,
                    product_name=product.name,
                    detail={"old_price": old_price, "new_price": new_price, "diff_pct": diff_pct},
                )

            changed_ids.append(r.product_id)
            if r.new_sale_status == "sold_out":
                soldout_ids.append(r.product_id)
                # 모니터링: 품절 감지
                await monitor.emit(
                    "sold_out", "warning",
                    summary=f"품절 감지 — {product.name[:30] if product.name else r.product_id}",
                    source_site=product.source_site,
                    product_id=r.product_id,
                    product_name=product.name,
                )

        await repo.update_async(r.product_id, **updates)

    await session.commit()

    # 자동 재전송 + 품절 삭제
    retransmitted = 0
    deleted_ids: list[str] = []
    if body.auto_retransmit and (changed_ids or soldout_ids):
        from backend.domain.samba.shipment.repository import SambaShipmentRepository
        from backend.domain.samba.shipment.service import SambaShipmentService

        ship_repo = SambaShipmentRepository(session)
        ship_svc = SambaShipmentService(ship_repo, session)

        # 가격 변동 상품 → 재전송 (계정별로 묶어서 배치 호출)
        price_changed = [pid for pid in changed_ids if pid not in soldout_ids]
        # 계정별 상품 그룹핑
        retransmit_groups: dict[str, list[str]] = {}
        for pid in price_changed:
            product = product_map.get(pid)
            if product and product.registered_accounts:
                acc_key = ",".join(sorted(product.registered_accounts))
                retransmit_groups.setdefault(acc_key, []).append(pid)
        for acc_key, pids in retransmit_groups.items():
            acc_ids = acc_key.split(",")
            try:
                await ship_svc.start_update(pids, ["price"], acc_ids, skip_unchanged=False)
                retransmitted += len(pids)
            except Exception as e:
                logger.error(f"[refresh] 재전송 실패 ({len(pids)}건): {e}")

        # 품절 상품 → 마켓 판매중지/삭제 → 삼바 DB 삭제
        import asyncio
        from backend.domain.samba.shipment.dispatcher import delete_from_market
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        account_repo = SambaMarketAccountRepository(session)

        # 계정 배치 조회 (N+1 방지)
        all_acc_ids = set()
        for pid in soldout_ids:
            product = product_map.get(pid)
            if product and product.registered_accounts:
                all_acc_ids.update(product.registered_accounts)
        acc_map: dict = {}
        if all_acc_ids:
            from backend.domain.samba.account.model import SambaMarketAccount as _MA
            _acc_stmt = select(_MA).where(_MA.id.in_(list(all_acc_ids)))
            _acc_result = await session.execute(_acc_stmt)
            acc_map = {a.id: a for a in _acc_result.scalars().all()}

        # 1단계: 삭제 대상 수집 (lock_delete 필터링, product_map 재사용)
        delete_targets: list[tuple] = []  # (pid, product_dict, account_id, account)
        deletable_pids: set[str] = set()  # DB 삭제 대상 pid
        for pid in soldout_ids:
            product = product_map.get(pid)
            if not product:
                continue
            if getattr(product, "lock_delete", False):
                logger.info(f"[refresh] {pid} 품절이지만 lock_delete=True, 삭제 건너뜀")
                continue
            deletable_pids.add(pid)
            product_dict = product.model_dump()
            if product.registered_accounts:
                for account_id in product.registered_accounts:
                    account = acc_map.get(account_id)
                    if not account:
                        continue
                    m_nos = product.market_product_nos or {}
                    pd = {**product_dict, "market_product_no": {account.market_type: m_nos.get(account_id, "")}}
                    delete_targets.append((pid, pd, account_id, account))

        # 2단계: 마켓 판매중지 병렬 처리 (5개씩)
        sem = asyncio.Semaphore(5)
        async def _do_market_delete(pid: str, pd: dict, acc: object) -> None:
            async with sem:
                try:
                    result = await delete_from_market(session, acc.market_type, pd, account=acc)  # type: ignore[union-attr]
                    if result.get("success"):
                        logger.info(f"[refresh] {pid} → {acc.market_type} 판매중지 완료")  # type: ignore[union-attr]
                    else:
                        logger.warning(f"[refresh] {pid} → {acc.market_type} 판매중지 실패: {result.get('message')}")  # type: ignore[union-attr]
                except Exception as e:
                    logger.error(f"[refresh] {pid} → 마켓 삭제 오류: {e}")

        if delete_targets:
            await asyncio.gather(*[_do_market_delete(pid, pd, acc) for pid, pd, _, acc in delete_targets])

        # 3단계: DB 일괄 삭제 (단일 쿼리)
        deleted_ids: list[str] = []
        if deletable_pids:
            from sqlalchemy import delete as sa_delete
            from sqlmodel import col
            from backend.domain.samba.collector.model import SambaCollectedProduct
            del_stmt = sa_delete(SambaCollectedProduct).where(col(SambaCollectedProduct.id).in_(list(deletable_pids)))
            await session.exec(del_stmt)  # type: ignore[arg-type]
            deleted_ids = list(deletable_pids)
            logger.info(f"[refresh] 품절 상품 {len(deleted_ids)}건 일괄 삭제 완료")

        await session.commit()

    summary.retransmitted = retransmitted

    # 모니터링: 재전송/삭제 이벤트
    if retransmitted > 0:
        await monitor.emit(
            "market_retransmit", "info",
            summary=f"가격변동 재전송 {retransmitted}건",
            detail={"count": retransmitted},
        )
    if body.auto_retransmit and deleted_ids:
        for did in deleted_ids:
            await monitor.emit(
                "market_deleted", "info",
                summary=f"품절 삭제 — {did}",
                product_id=did,
            )

    # 모니터링: 배치 갱신 완료
    await monitor.emit(
        "refresh_batch", "info",
        summary=f"배치 갱신 완료 — {summary.total}건 중 {summary.refreshed}건 갱신, {summary.changed}건 변동",
        detail={
            "total": summary.total,
            "refreshed": summary.refreshed,
            "changed": summary.changed,
            "sold_out": summary.sold_out,
            "deleted": len(deleted_ids) if body.auto_retransmit else 0,
            "retransmitted": retransmitted,
            "errors": summary.errors,
        },
    )
    await session.commit()

    return {
        "total": summary.total,
        "refreshed": summary.refreshed,
        "changed": summary.changed,
        "sold_out": summary.sold_out,
        "deleted": len(deleted_ids) if body.auto_retransmit else 0,
        "retransmitted": summary.retransmitted,
        "needs_extension": summary.needs_extension,
        "errors": summary.errors,
    }


class MonitorPriorityUpdate(BaseModel):
    product_ids: List[str]
    priority: str  # hot / warm / cold


@router.put("/products/monitor-priority")
async def update_monitor_priority(
    body: MonitorPriorityUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품 모니터링 우선순위 일괄 변경."""
    if body.priority not in ("hot", "warm", "cold"):
        raise HTTPException(status_code=400, detail="priority는 hot/warm/cold만 가능합니다.")

    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    repo = SambaCollectedProductRepository(session)

    updated = 0
    for pid in body.product_ids:
        result = await repo.update_async(pid, monitor_priority=body.priority)
        if result:
            updated += 1

    await session.commit()
    return {"updated": updated}


# ══════════════════════════════════════════════════════════════
# 무신사 차단 임계값 테스트
# ══════════════════════════════════════════════════════════════

class RateLimitTestRequest(BaseModel):
    goods_no: str = "4746833"  # 테스트용 상품번호
    count: int = 100  # 요청 횟수
    interval: float = 0.0  # 요청 간격 (초)
    mode: str = "autotune"  # autotune(상세+옵션 2개) / collect(상세+옵션+고시정보 3개)


@router.post("/test/rate-limit")
async def test_rate_limit(body: RateLimitTestRequest = RateLimitTestRequest()):
    """무신사 차단 임계값 테스트."""
    import asyncio
    import httpx
    import time

    from backend.domain.samba.collector.refresher import _get_musinsa_cookie
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    cookie = await _get_musinsa_cookie()
    if not cookie:
        return {"error": "무신사 쿠키 없음"}

    client = MusinsaClient(cookie)
    headers = client._headers()
    base = "https://goods-detail.musinsa.com/api2/goods"

    results = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        for i in range(body.count):
            start = time.monotonic()
            try:
                urls = [f"{base}/{body.goods_no}", f"{base}/{body.goods_no}/options"]
                if body.mode == "collect":
                    urls.append(f"{base}/{body.goods_no}/essential")

                statuses = []
                for url in urls:
                    r = await http.get(url, headers=headers)
                    statuses.append(r.status_code)
                    if r.status_code in (429, 403):
                        elapsed = round((time.monotonic() - start) * 1000)
                        retry_after = r.headers.get("Retry-After", "?")
                        api_name = url.split("/")[-1] if "/" in url else "detail"
                        results.append({"req": i + 1, "statuses": statuses, "ms": elapsed, "blocked": api_name})
                        return {
                            "blocked_at": {"request_no": i + 1, "status": r.status_code, "api": api_name, "retry_after": retry_after},
                            "total_ok": i,
                            "mode": body.mode,
                            "api_per_req": len(urls),
                            "total_api_calls": i * len(urls) + len(statuses),
                            "results": results[-10:],
                            "summary": f"{body.mode} 모드: {i + 1}번째에서 {api_name} API {r.status_code} 차단",
                        }

                elapsed = round((time.monotonic() - start) * 1000)
                results.append({"req": i + 1, "statuses": statuses, "ms": elapsed})
            except Exception as e:
                elapsed = round((time.monotonic() - start) * 1000)
                results.append({"req": i + 1, "error": str(e), "ms": elapsed})

            if body.interval > 0:
                await asyncio.sleep(body.interval)

    avg_ms = sum(r.get("ms", 0) for r in results) // len(results) if results else 0
    total_apis = body.count * (3 if body.mode == "collect" else 2)
    return {
        "blocked_at": None,
        "total_ok": len(results),
        "mode": body.mode,
        "api_per_req": 3 if body.mode == "collect" else 2,
        "total_api_calls": total_apis,
        "avg_ms": avg_ms,
        "results": results[-10:],
        "summary": f"{body.mode} 모드: {len(results)}회 성공 (API {total_apis}회, 평균 {avg_ms}ms/상품)",
    }


# ══════════════════════════════════════════════════════════════
# 오토튠 백그라운드 루프 (무한 반복)
# ══════════════════════════════════════════════════════════════

import asyncio as _asyncio

_autotune_task: Optional[_asyncio.Task] = None
_autotune_running = False
_autotune_last_tick: Optional[str] = None
_autotune_cycle_count = 0
_autotune_target = "all"  # all / registered / unregistered


async def _autotune_loop():
    """오토튠 무한 루프 — tick 완료 즉시 다음 tick 시작."""
    global _autotune_running, _autotune_last_tick, _autotune_cycle_count
    import logging
    log = logging.getLogger("autotune")
    log.info("[오토튠] 루프 시작")

    while _autotune_running:
        try:
            from backend.db.orm import get_write_session
            async with get_write_session() as session:
                from backend.domain.samba.collector.refresher import refresh_products_bulk
                from backend.domain.samba.collector.repository import SambaCollectedProductRepository
                from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
                from backend.domain.samba.warroom.service import SambaMonitorService

                now = datetime.now(timezone.utc)
                repo = SambaCollectedProductRepository(session)

                # target 기반으로 직접 상품 조회 (스케줄러 우회)
                stmt = select(_CP)
                if _autotune_target == "registered":
                    stmt = stmt.where(_CP.registered_accounts != None, _CP.status == "registered")
                elif _autotune_target == "unregistered":
                    stmt = stmt.where(or_(_CP.registered_accounts == None, _CP.status != "registered"))
                # 정책 적용된 상품만 + 품절 제외
                stmt = stmt.where(_CP.applied_policy_id != None)
                stmt = stmt.where(or_(_CP.is_sold_out == None, _CP.is_sold_out == False))
                result = await session.exec(stmt)
                products = list(result.all())
                candidates = products  # 로그용

                if products:
                    filtered_count = len(products)
                    results, summary = await refresh_products_bulk(products)

                    # DB 업데이트 + 변동/품절 추적
                    changed_ids: list[str] = []
                    stock_changed_ids: list[str] = []
                    soldout_ids: list[str] = []

                    for r in results:
                        if r.error:
                            product = await repo.get_async(r.product_id)
                            if product:
                                await repo.update_async(
                                    r.product_id,
                                    refresh_error_count=(product.refresh_error_count or 0) + 1,
                                    last_refreshed_at=now,
                                )
                            continue
                        if r.needs_extension:
                            continue

                        product = await repo.get_async(r.product_id)
                        if not product:
                            continue

                        updates: dict = {
                            "last_refreshed_at": now,
                            "refresh_error_count": 0,
                        }

                        snapshot: dict = {
                            "date": now.isoformat(),
                            "source": "autotune",
                            "sale_price": r.new_sale_price if r.new_sale_price is not None else product.sale_price,
                            "original_price": r.new_original_price if r.new_original_price is not None else product.original_price,
                            "cost": r.new_cost if r.new_cost is not None else product.cost,
                            "sale_status": r.new_sale_status,
                            "changed": r.changed,
                        }
                        if r.new_options:
                            snapshot["options"] = r.new_options
                        history = list(product.price_history or [])
                        history.insert(0, snapshot)
                        updates["price_history"] = _trim_history(history)

                        if r.changed:
                            if r.new_sale_price is not None:
                                updates["sale_price"] = r.new_sale_price
                            if r.new_original_price is not None:
                                updates["original_price"] = r.new_original_price
                            if r.new_cost is not None:
                                updates["cost"] = r.new_cost
                            if r.new_options is not None:
                                updates["options"] = r.new_options
                            updates["sale_status"] = r.new_sale_status
                            updates["is_sold_out"] = r.new_sale_status == "sold_out"
                            old_price = product.sale_price or 0
                            new_price = r.new_sale_price or 0
                            if new_price != old_price:
                                updates["price_before_change"] = old_price
                                updates["price_changed_at"] = now
                            # 품절이면 soldout, 아니면 가격변동으로 추적
                            if r.new_sale_status == "sold_out":
                                soldout_ids.append(r.product_id)
                            else:
                                changed_ids.append(r.product_id)
                        # 재고만 변동 (가격은 동일)
                        elif r.stock_changed:
                            if r.new_options is not None:
                                updates["options"] = r.new_options
                            stock_changed_ids.append(r.product_id)

                        await repo.update_async(r.product_id, **updates)

                    await session.commit()

                    # 마켓 반영: 가격변동 → 재전송, 재고변동 → 재전송, 품절 → 마켓삭제+DB삭제
                    retransmitted = 0
                    deleted_count = 0
                    if changed_ids or stock_changed_ids or soldout_ids:
                        from backend.domain.samba.shipment.repository import SambaShipmentRepository
                        from backend.domain.samba.shipment.service import SambaShipmentService

                        ship_repo = SambaShipmentRepository(session)
                        ship_svc = SambaShipmentService(ship_repo, session)

                        # 가격/재고 변동 → 계정별로 묶어서 배치 재전송
                        _all_retransmit = list(set(changed_ids) | set(stock_changed_ids))
                        _rt_groups: dict[str, list[str]] = {}
                        for pid in _all_retransmit:
                            product = await repo.get_async(pid)
                            if product and product.registered_accounts:
                                acc_key = ",".join(sorted(product.registered_accounts))
                                _rt_groups.setdefault(acc_key, []).append(pid)
                        for acc_key, pids in _rt_groups.items():
                            acc_ids = acc_key.split(",")
                            try:
                                await ship_svc.start_update(pids, [], acc_ids, skip_unchanged=False)
                                retransmitted += len(pids)
                            except Exception as e:
                                log.error("[오토튠] 재전송 실패 (%d건): %s", len(pids), e)

                        # 품절 → 마켓 판매중지 + DB 삭제
                        import asyncio as _aio
                        from backend.domain.samba.shipment.dispatcher import delete_from_market
                        from backend.domain.samba.account.repository import SambaMarketAccountRepository
                        account_repo = SambaMarketAccountRepository(session)

                        # 1단계: 삭제 대상 수집
                        _del_targets: list[tuple] = []
                        _del_pids: set[str] = set()
                        for pid in soldout_ids:
                            product = await repo.get_async(pid)
                            if not product:
                                continue
                            if getattr(product, "lock_delete", False):
                                log.info("[오토튠] %s 품절이지만 lock_delete=True, 삭제 건너뜀", pid)
                                continue
                            _del_pids.add(pid)
                            product_dict = product.model_dump()
                            if product.registered_accounts:
                                for account_id in product.registered_accounts:
                                    account = await account_repo.get_async(account_id)
                                    if not account:
                                        continue
                                    m_nos = product.market_product_nos or {}
                                    pd = {**product_dict, "market_product_no": {account.market_type: m_nos.get(account_id, "")}}
                                    _del_targets.append((pid, pd, account_id, account))

                        # 2단계: 마켓 판매중지 병렬 (5개씩)
                        _sem = _aio.Semaphore(5)
                        async def _at_del(pid: str, pd: dict, acc: object) -> None:
                            async with _sem:
                                try:
                                    r = await delete_from_market(session, acc.market_type, pd, account=acc)  # type: ignore[union-attr]
                                    if r.get("success"):
                                        log.info("[오토튠] %s → %s 판매중지 완료", pid, acc.market_type)  # type: ignore[union-attr]
                                    else:
                                        log.warning("[오토튠] %s → %s 판매중지 실패: %s", pid, acc.market_type, r.get("message"))  # type: ignore[union-attr]
                                except Exception as e:
                                    log.error("[오토튠] %s → 마켓 삭제 오류: %s", pid, e)

                        if _del_targets:
                            await _aio.gather(*[_at_del(pid, pd, acc) for pid, pd, _, acc in _del_targets])

                        # 3단계: DB 일괄 삭제
                        if _del_pids:
                            from sqlalchemy import delete as sa_delete
                            from sqlmodel import col
                            from backend.domain.samba.collector.model import SambaCollectedProduct
                            await session.exec(sa_delete(SambaCollectedProduct).where(col(SambaCollectedProduct.id).in_(list(_del_pids))))  # type: ignore[arg-type]
                            deleted_count = len(_del_pids)
                            log.info("[오토튠] 품절 상품 %d건 일괄 삭제 완료", deleted_count)

                        await session.commit()

                    monitor = SambaMonitorService(session)
                    await monitor.emit(
                        "scheduler_tick", "info",
                        summary=f"오토튠({_autotune_target}) — 대상 {filtered_count}건, {summary.refreshed}건 갱신, 재전송 {retransmitted}건, 품절삭제 {deleted_count}건",
                        detail={
                            "target": _autotune_target,
                            "total": filtered_count,
                            "refreshed": summary.refreshed,
                            "changed": summary.changed,
                            "sold_out": summary.sold_out,
                            "retransmitted": retransmitted,
                            "deleted": deleted_count,
                        },
                    )
                    await session.commit()
                    log.info("[오토튠] tick 완료: 대상 %d, 갱신 %d, 재전송 %d, 품절삭제 %d", filtered_count, summary.refreshed, retransmitted, deleted_count)
                else:
                    # 갱신 대상 없으면 5초 대기 후 재확인
                    await _asyncio.sleep(5)

                _autotune_last_tick = now.isoformat()
                _autotune_cycle_count += 1

        except _asyncio.CancelledError:
            log.info("[오토튠] 루프 취소됨")
            break
        except Exception as e:
            log.error("[오토튠] tick 오류: %s", e, exc_info=True)
            # 에러 시 10초 대기 후 재시도
            await _asyncio.sleep(10)

    log.info("[오토튠] 루프 종료")


class AutotuneStartRequest(BaseModel):
    target: str = "all"  # all / registered / unregistered


@router.post("/autotune/start")
async def autotune_start(body: AutotuneStartRequest = AutotuneStartRequest()):
    """오토튠 무한 루프 시작."""
    global _autotune_task, _autotune_running, _autotune_cycle_count, _autotune_target
    if _autotune_running:
        return {"ok": True, "status": "already_running"}
    _autotune_running = True
    _autotune_cycle_count = 0
    _autotune_target = body.target
    _autotune_task = _asyncio.create_task(_autotune_loop())
    return {"ok": True, "status": "started", "target": body.target}


@router.post("/autotune/stop")
async def autotune_stop():
    """오토튠 무한 루프 정지."""
    global _autotune_task, _autotune_running
    if not _autotune_running:
        return {"ok": True, "status": "already_stopped"}
    _autotune_running = False
    if _autotune_task and not _autotune_task.done():
        _autotune_task.cancel()
    _autotune_task = None
    return {"ok": True, "status": "stopped"}


@router.get("/autotune/status")
async def autotune_status():
    """오토튠 상태 조회."""
    return {
        "running": _autotune_running,
        "last_tick": _autotune_last_tick,
        "cycle_count": _autotune_cycle_count,
        "target": _autotune_target,
    }


# ══════════════════════════════════════════════════════════════
# 소싱처/마켓 Probe (구조 변경 감지)
# ══════════════════════════════════════════════════════════════


@router.get("/probe/status")
async def probe_status(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """최근 probe 결과 조회."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    repo = SambaSettingsRepository(session)
    results: dict = {"sources": {}, "markets": {}}

    # 소싱처 probe 결과
    from backend.domain.samba.probe.health_checker import PROBE_TARGETS, MARKET_PROBES
    for site in PROBE_TARGETS:
        row = await repo.find_by_async(key=f"probe_{site}")
        if row and row.value:
            results["sources"][site] = row.value

    # 마켓 probe 결과
    for mt in MARKET_PROBES:
        row = await repo.find_by_async(key=f"probe_market_{mt}")
        if row and row.value:
            results["markets"][mt] = row.value

    return results


@router.post("/probe/run")
async def probe_run(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """수동 probe 실행 — 전체 소싱처+마켓 헬스체크."""
    from backend.domain.samba.probe.health_checker import run_all_probes
    results = await run_all_probes(session)

    # 모니터링: probe 결과 이벤트 발행
    from backend.domain.samba.warroom.service import SambaMonitorService
    monitor = SambaMonitorService(session)

    for site, data in results.get("sources", {}).items():
        if not data.get("ok"):
            missing = data.get("missing_fields", [])
            if missing:
                await monitor.emit(
                    "api_structure_changed", "critical",
                    summary=f"API 구조 변경 감지 — {site} 필드 누락: {', '.join(missing)}",
                    source_site=site,
                    detail={"missing_fields": missing, "error": data.get("error")},
                )
            elif data.get("error"):
                await monitor.emit(
                    "probe_failed", "warning",
                    summary=f"Probe 실패 — {site}: {data.get('error')}",
                    source_site=site,
                    detail=data,
                )

    for mt, data in results.get("markets", {}).items():
        if not data.get("ok") and data.get("error"):
            await monitor.emit(
                "probe_failed", "warning",
                summary=f"마켓 Probe 실패 — {mt}: {data.get('error')}",
                market_type=mt,
                detail=data,
            )

    await session.commit()
    return results


# ══════════════════════════════════════════════════════════════
# Ken Burns 영상 생성
# ══════════════════════════════════════════════════════════════


class VideoGenerateRequest(BaseModel):
    product_id: str
    max_images: int = 3
    duration_per_image: float = 1.0


@router.post("/products/generate-video")
async def generate_product_video(
    body: VideoGenerateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품 이미지로 Ken Burns 효과 영상(2~3초) 생성 → R2/로컬 저장 → 상품에 매칭."""
    from backend.domain.samba.video.kenburns import generate_kenburns_video
    from backend.domain.samba.image.service import ImageTransformService
    import uuid
    from pathlib import Path

    svc = _get_services(session)
    product = await svc.get_collected_product(body.product_id)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다")

    images = product.images or []
    if not images:
        raise HTTPException(400, "상품 이미지가 없습니다")

    # AI 변환 이미지가 없으면 자동 생성
    ai_images = [u for u in images if '/transformed/' in u or '/ai_' in u]
    if not ai_images:
        logger.info(f"[영상생성] AI이미지 없음 — 자동 생성 시작 ({body.product_id})")
        img_svc_auto = ImageTransformService(session)
        try:
            # 대표이미지는 건드리지 않고 별도 생성
            ai_result = await img_svc_auto.transform_single_image(
                body.product_id, images[0], "video",
            )
            if ai_result:
                logger.info(f"[영상생성] AI이미지 자동 생성 완료")
                # 추가이미지 마지막에 추가
                updated_images = list(images)
                updated_images.append(ai_result)
                await svc.update_collected_product(body.product_id, {"images": updated_images})
                images = updated_images
                ai_images = [ai_result]
        except Exception as e:
            logger.warning(f"[영상생성] AI이미지 자동 생성 실패, 원본으로 진행: {e}")

    source_images = ai_images if ai_images else images

    try:
        output_path = generate_kenburns_video(
            image_urls=source_images,
            duration_per_image=body.duration_per_image,
            max_images=body.max_images,
        )
    except Exception as e:
        raise HTTPException(500, f"영상 생성 실패: {str(e)}")

    # R2/로컬 저장
    filename = f"video_{product.site_product_id or uuid.uuid4().hex[:8]}_{uuid.uuid4().hex[:6]}.mp4"
    video_bytes = Path(output_path).read_bytes()

    img_svc = ImageTransformService(session)
    r2 = await img_svc._get_r2_client()
    if r2:
        client, bucket_name, public_url = r2
        try:
            import io
            client.upload_fileobj(
                io.BytesIO(video_bytes),
                bucket_name,
                f"videos/{filename}",
                ExtraArgs={"ContentType": "video/mp4"},
            )
            video_url = f"{public_url}/videos/{filename}"
        except Exception:
            # R2 실패 시 로컬 저장
            local_dir = Path("static/videos")
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / filename).write_bytes(video_bytes)
            video_url = f"/static/videos/{filename}"
    else:
        local_dir = Path("static/videos")
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / filename).write_bytes(video_bytes)
        video_url = f"/static/videos/{filename}"

    # 상품에 video_url 매칭
    await svc.update_collected_product(body.product_id, {"video_url": video_url})

    # 임시파일 삭제
    Path(output_path).unlink(missing_ok=True)

    return {"success": True, "video_url": video_url}
