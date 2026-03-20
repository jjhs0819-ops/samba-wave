"""SambaWave Collector API router - 수집 필터 + 수집 상품."""

import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.proxy.musinsa import RateLimitError
from backend.domain.samba.collector.refresher import _site_intervals, _site_consecutive_errors

router = APIRouter(prefix="/collector", tags=["samba-collector"])


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
    tags: Optional[list] = None


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
    filters = await svc.list_filters()

    # 각 필터별 수집상품 카운트 추가
    result = []
    for f in filters:
        data = {c.key: getattr(f, c.key) for c in f.__table__.columns}
        count = await svc.product_repo.count_async(
            filters={"search_filter_id": f.id}
        )
        data["collected_count"] = count
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


# ── Collected Products ──

@router.get("/products")
async def list_collected_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=10000),
    status: Optional[str] = None,
    source_site: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_services(session)
    return await svc.list_collected_products(skip=skip, limit=limit, status=status, source_site=source_site)


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
    return await svc.create_collected_product(body.model_dump(exclude_unset=True))


@router.post("/products/bulk", status_code=201)
async def bulk_create_collected_products(
    body: BulkCreateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_services(session)
    items = [item.model_dump(exclude_unset=True) for item in body.items]
    created = await svc.bulk_create_collected_products(items)
    return {"created": len(created)}


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

            # 일괄 저장 데이터 준비 (remaining 개수만큼만)
            from datetime import datetime, timezone
            skipped_sold_out = 0
            bulk_items = []
            for item in all_items:
                # 요청 상품수 도달 시 종료
                if len(bulk_items) >= remaining:
                    break

                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue

                # 품절 상품 수집 제외
                if item.get("isSoldOut", False):
                    skipped_sold_out += 1
                    continue

                raw_cat = item.get("category", "") or ""
                cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                _sale_price = item.get("salePrice", item.get("price", 0))
                _original_price = item.get("originalPrice", item.get("normalPrice", 0))

                bulk_items.append({
                    "source_site": "MUSINSA",
                    "site_product_id": site_pid,
                    "search_filter_id": filter_id,
                    "name": item.get("name", item.get("goodsName", "")),
                    "brand": item.get("brand", item.get("brandName", "")),
                    "original_price": _original_price,
                    "sale_price": _sale_price,
                    "images": item.get("images", []),
                    "options": item.get("options", []),
                    "category": raw_cat,
                    "category1": cat_parts[0] if len(cat_parts) > 0 else None,
                    "category2": cat_parts[1] if len(cat_parts) > 1 else None,
                    "category3": cat_parts[2] if len(cat_parts) > 2 else None,
                    "category4": cat_parts[3] if len(cat_parts) > 3 else None,
                    "status": "collected",
                    "is_sold_out": item.get("isSoldOut", False),
                    "sale_status": "sold_out" if item.get("isSoldOut", False) else "in_stock",
                    "price_history": [{
                        "date": datetime.now(timezone.utc).isoformat(),
                        "sale_price": _sale_price,
                        "original_price": _original_price,
                        "cost": None,
                        "options": [],
                    }],
                })

            # 단일 트랜잭션 일괄 저장
            created = []
            if bulk_items:
                created = await svc.bulk_create_collected_products(bulk_items)

            # 새로 저장된 상품에 대해 상세 보강 (상품당 1초 대기)
            enriched = 0
            skipped_preorder = 0
            skipped_boutique = 0
            for product in created:
                try:
                    detail = await client.get_goods_detail(product.site_product_id)
                    if detail and detail.get("name"):
                        # 예약배송 수집제외
                        if exclude_preorder and detail.get("saleStatus") == "preorder":
                            await svc.delete_collected_product(product.id)
                            skipped_preorder += 1
                            continue
                        # 부티끄 수집제외
                        if exclude_boutique and detail.get("isBoutique"):
                            await svc.delete_collected_product(product.id)
                            skipped_boutique += 1
                            continue

                        # 최대혜택가 체크 시 bestBenefitPrice, 미체크 시 salePrice를 원가로 사용
                        if use_max_discount:
                            _raw_cost = detail.get("bestBenefitPrice")
                            new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else None
                        else:
                            new_cost = detail.get("salePrice") or product.sale_price
                        enrich_updates = {
                            "category": detail.get("category") or product.category,
                            "category1": detail.get("category1"),
                            "category2": detail.get("category2"),
                            "category3": detail.get("category3"),
                            "category4": detail.get("category4"),
                            "original_price": detail.get("originalPrice") if detail.get("originalPrice") is not None else product.original_price,
                            "sale_price": detail.get("salePrice") if detail.get("salePrice") is not None else product.sale_price,
                            "cost": new_cost,
                            "brand": detail.get("brand") or product.brand,
                            "manufacturer": detail.get("manufacturer"),
                            "origin": detail.get("origin"),
                            "images": detail.get("images") or product.images,
                            "detail_images": detail.get("detailImages") or None,
                            "material": detail.get("material"),
                            "color": detail.get("color"),
                            "detail_html": detail.get("detailHtml") or None,
                            "options": detail.get("options", []),
                            "is_sold_out": detail.get("saleStatus") == "sold_out",
                            "sale_status": detail.get("saleStatus", "in_stock"),
                        }
                        # 상세 보강 시 가격/옵션 이력 스냅샷 추가
                        enrich_snapshot = {
                            "date": datetime.now(timezone.utc).isoformat(),
                            "sale_price": detail.get("salePrice") or product.sale_price,
                            "original_price": detail.get("originalPrice") or product.original_price,
                            "cost": new_cost,
                            "options": detail.get("options", []),
                        }
                        history = list(product.price_history or [])
                        history.insert(0, enrich_snapshot)
                        enrich_updates["price_history"] = history[:200]
                        await svc.update_collected_product(product.id, enrich_updates)
                        enriched += 1
                except Exception as e:
                    logger.warning(f"[상세보강 실패] {product.site_product_id}: {e}")
                await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌

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
                "total_found": len(all_items),
                "saved": len(created) - skipped_preorder - skipped_boutique,
                "enriched": enriched,
                "skipped_duplicates": len(all_items) - len(created) - skipped_sold_out,
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

            collected = await svc.create_collected_product({
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
                "color": data.get("color", ""),
                "detail_html": raw_detail_html,
                "status": "collected",
                "is_sold_out": sale_status == "sold_out",
                "sale_status": sale_status,
                "price_history": [initial_snapshot],
            })
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

            collected = await svc.create_collected_product({
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
                "status": "collected",
                "price_history": [_snapshot],
            })
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

    keyword = search_filter.name
    if keyword_or_url and ("http" in keyword_or_url):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(keyword_or_url).query)
        keyword = qs.get("keyword", [keyword])[0]

    def _sse(event: str, data: dict) -> str:
        return f"data: {_json.dumps({**data, 'event': event}, ensure_ascii=False)}\n\n"

    async def _stream_musinsa():
        import asyncio as _asyncio

        cookie = await _get_musinsa_cookie()
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

            bulk_items = []
            for item in search_items:
                if total_enriched + len(bulk_items) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    total_skipped_sold_out += 1
                    continue

                raw_cat = item.get("category", "") or ""
                cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                _sale_price = item.get("salePrice", item.get("price", 0))
                _original_price = item.get("originalPrice", item.get("normalPrice", 0))
                bulk_items.append({
                    "source_site": "MUSINSA", "site_product_id": site_pid,
                    "search_filter_id": filter_id,
                    "name": item.get("name", item.get("goodsName", "")),
                    "brand": item.get("brand", item.get("brandName", "")),
                    "original_price": _original_price, "sale_price": _sale_price,
                    "images": item.get("images", []), "options": item.get("options", []),
                    "category": raw_cat,
                    "category1": cat_parts[0] if len(cat_parts) > 0 else None,
                    "category2": cat_parts[1] if len(cat_parts) > 1 else None,
                    "category3": cat_parts[2] if len(cat_parts) > 2 else None,
                    "category4": cat_parts[3] if len(cat_parts) > 3 else None,
                    "status": "collected",
                    "is_sold_out": item.get("isSoldOut", False),
                    "sale_status": "sold_out" if item.get("isSoldOut", False) else "in_stock",
                    "price_history": [{"date": datetime.now(timezone.utc).isoformat(), "sale_price": _sale_price, "original_price": _original_price, "cost": None, "options": []}],
                })

            if not bulk_items:
                search_page += 1
                continue

            created = await svc.bulk_create_collected_products(bulk_items)
            total_saved += len(created)
            yield _sse("log", {"message": f"{len(created)}건 저장. 상세 보강 중..."})

            # 상세 보강 (개별 상품마다 로그)
            for product in created:
                try:
                    detail = await client.get_goods_detail(product.site_product_id)
                    if detail and detail.get("name"):
                        p_name = detail.get("name", "")[:30]

                        if _exclude_preorder and detail.get("saleStatus") == "preorder":
                            await svc.delete_collected_product(product.id)
                            total_skipped_preorder += 1
                            total_saved -= 1
                            yield _sse("log", {"message": f"  {p_name} — 예약배송 제외"})
                            await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌
                            continue
                        if _exclude_boutique and detail.get("isBoutique"):
                            await svc.delete_collected_product(product.id)
                            total_skipped_boutique += 1
                            total_saved -= 1
                            yield _sse("log", {"message": f"  {p_name} — 부티끄 제외"})
                            await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌
                            continue

                        if _use_max_discount:
                            _raw_cost = detail.get("bestBenefitPrice")
                            new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else None
                        else:
                            new_cost = detail.get("salePrice") or product.sale_price

                        enrich_updates = {
                            "category": detail.get("category") or product.category,
                            "category1": detail.get("category1"), "category2": detail.get("category2"),
                            "category3": detail.get("category3"), "category4": detail.get("category4"),
                            "original_price": detail.get("originalPrice") if detail.get("originalPrice") is not None else product.original_price,
                            "sale_price": detail.get("salePrice") if detail.get("salePrice") is not None else product.sale_price,
                            "cost": new_cost,
                            "brand": detail.get("brand") or product.brand,
                            "manufacturer": detail.get("manufacturer"), "origin": detail.get("origin"),
                            "images": detail.get("images") or product.images,
                            "detail_images": detail.get("detailImages") or None,
                            "material": detail.get("material"),
                            "color": detail.get("color"),
                            "options": detail.get("options", []),
                            # 확장 상품정보 (kream_data 필드에 JSON으로 저장)
                            "kream_data": {
                                "color": detail.get("color", ""),
                                "material": detail.get("material", ""),
                                "sizeInfo": detail.get("sizeInfo", ""),
                                "season": detail.get("season", ""),
                                "styleCode": detail.get("styleCode", ""),
                                "brandNation": detail.get("brandNation", ""),
                                "sex": detail.get("sex", []),
                                "qualityGuarantee": detail.get("qualityGuarantee", ""),
                                "careInstructions": detail.get("careInstructions", ""),
                            },
                            "is_sold_out": detail.get("saleStatus") == "sold_out",
                            "sale_status": detail.get("saleStatus", "in_stock"),
                        }
                        enrich_snapshot = {
                            "date": datetime.now(timezone.utc).isoformat(),
                            "sale_price": detail.get("salePrice") or product.sale_price,
                            "original_price": detail.get("originalPrice") or product.original_price,
                            "cost": new_cost, "options": detail.get("options", []),
                        }
                        history = list(product.price_history or [])
                        history.insert(0, enrich_snapshot)
                        enrich_updates["price_history"] = history[:200]
                        await svc.update_collected_product(product.id, enrich_updates)
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
                        break
                    yield _sse("warning", {"message": f"차단 감지(HTTP {rle.status}), 속도 조절 중... (인터벌 {_site_intervals['MUSINSA']}초)"})
                    if rle.retry_after > 0:
                        await _asyncio.sleep(rle.retry_after)
                    else:
                        await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                    continue
                except Exception as e:
                    logger.warning(f"[보강 실패] {product.site_product_id}: {e}")
                    yield _sse("log", {"message": f"  {product.site_product_id} — 보강 실패"})
                await _asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌

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
        return StreamingResponse(_stream_musinsa(), media_type="text/event-stream")

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

                    product_data = {
                        "source_site": "KREAM",
                        "site_product_id": single_pid,
                        "search_filter_id": filter_id,
                        "name": pd.get("nameKo") or pd.get("name", ""),
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
                            enrich_updates["price_history"] = history[:200]

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

        return StreamingResponse(_stream_kream(), media_type="text/event-stream")

    # ── 패션플러스 / Nike / Adidas (백엔드 직접 API) ──
    DIRECT_API_SITES = {"FashionPlus", "Nike", "Adidas"}
    # ── 확장앱 기반 사이트 ──
    EXTENSION_SITES = {"ABCmart", "GrandStage", "OKmall", "LOTTEON", "GSShop", "ElandMall", "SSF"}

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

        return StreamingResponse(_stream_generic(), media_type="text/event-stream")

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

        client = MusinsaClient(cookie=cookie or "")
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
        updates["price_history"] = history[:200]

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
        updates["price_history"] = history[:200]

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
            updates["price_history"] = history[:200]

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

    # 대상 상품 조회
    if body.product_ids:
        products = []
        for pid in body.product_ids:
            p = await repo.get_async(pid)
            if p:
                products.append(p)
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

    # 변동 감지된 상품 DB 업데이트
    now = datetime.now(timezone.utc)
    changed_ids: list[str] = []
    soldout_ids: list[str] = []

    for r in results:
        if r.error:
            # 에러 카운트 증가
            product = await repo.get_async(r.product_id)
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

        # 상품 조회 (변동 여부와 관계없이 이력 기록 위해)
        product = await repo.get_async(r.product_id)
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
        updates["price_history"] = history[:200]

        # 이미지/소재/색상 — 기존에 비어있으면 갱신 (재수집 시 자동 보충)
        if r.new_images and not product.images:
            updates["images"] = r.new_images
        if r.new_detail_images and not getattr(product, "detail_images", None):
            updates["detail_images"] = r.new_detail_images
        if r.new_material and not getattr(product, "material", None):
            updates["material"] = r.new_material
        if r.new_color and not getattr(product, "color", None):
            updates["color"] = r.new_color

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

        # 가격 변동 상품 → 재전송 (등록된 마켓 계정으로)
        price_changed = [pid for pid in changed_ids if pid not in soldout_ids]
        for pid in price_changed:
            product = await repo.get_async(pid)
            if product and product.registered_accounts:
                try:
                    await ship_svc.start_update(
                        [pid], ["price"], product.registered_accounts, skip_unchanged=False
                    )
                    retransmitted += 1
                except Exception as e:
                    logger.error(f"[refresh] 재전송 실패 {pid}: {e}")

        # 품절 상품 → 마켓 판매중지/삭제 → 삼바 DB 삭제
        from backend.domain.samba.shipment.dispatcher import delete_from_market
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        account_repo = SambaMarketAccountRepository(session)

        deleted_ids: list[str] = []
        for pid in soldout_ids:
            product = await repo.get_async(pid)
            if not product:
                continue

            # lock_delete 플래그가 켜져 있으면 삭제하지 않음
            if getattr(product, "lock_delete", False):
                logger.info(f"[refresh] {pid} 품절이지만 lock_delete=True, 삭제 건너뜀")
                continue

            product_dict = product.model_dump()

            # 등록된 마켓 계정에서 판매중지 시도
            if product.registered_accounts:
                for account_id in product.registered_accounts:
                    try:
                        account = await account_repo.get_async(account_id)
                        if not account:
                            continue
                        # 상품번호 주입
                        m_nos = product.market_product_nos or {}
                        product_dict["market_product_no"] = {account.market_type: m_nos.get(account_id, "")}
                        result = await delete_from_market(
                            session, account.market_type, product_dict, account=account
                        )
                        if result.get("success"):
                            logger.info(f"[refresh] {pid} → {account.market_type} 판매중지 완료")
                        else:
                            logger.warning(f"[refresh] {pid} → {account.market_type} 판매중지 실패: {result.get('message')}")
                    except Exception as e:
                        logger.error(f"[refresh] {pid} → 마켓 삭제 오류: {e}")

            # 삼바 DB에서 상품 삭제
            try:
                await repo.delete_async(pid)
                deleted_ids.append(pid)
                logger.info(f"[refresh] 품절 상품 삭제 완료: {pid}")
            except Exception as e:
                logger.error(f"[refresh] 품절 상품 DB 삭제 실패 {pid}: {e}")

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


@router.post("/scheduler/tick")
async def scheduler_tick(
    x_scheduler_key: Optional[str] = Header(None, alias="X-Scheduler-Key"),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """스케줄러 tick — 외부 cron이 10분마다 호출.

    SCHEDULER_SECRET 환경변수로 인증 키 검증.
    """
    from backend.core.config import settings
    secret = settings.scheduler_secret
    if secret and x_scheduler_key != secret:
        raise HTTPException(status_code=403, detail="인증 키가 올바르지 않습니다.")

    from backend.domain.samba.collector.scheduler import get_refresh_candidates
    from backend.domain.samba.collector.refresher import refresh_products_bulk
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    now = datetime.now(timezone.utc)
    candidates = await get_refresh_candidates(session, now)

    # 모니터링 서비스 초기화
    from backend.domain.samba.warroom.service import SambaMonitorService
    monitor = SambaMonitorService(session)

    if not candidates:
        return {"candidates": 0, "refreshed": 0, "changed": 0, "sold_out": 0}

    repo = SambaCollectedProductRepository(session)
    products = []
    for pid in candidates:
        p = await repo.get_async(pid)
        if p:
            products.append(p)

    results, summary = await refresh_products_bulk(products)

    # DB 업데이트
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

        # 가격이력 스냅샷 — 변동 여부와 관계없이 항상 기록
        snapshot: dict = {
            "date": now.isoformat(),
            "source": "scheduler",
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
        updates["price_history"] = history[:200]

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

        await repo.update_async(r.product_id, **updates)

    await session.commit()

    # 모니터링: 스케줄러 tick 완료
    await monitor.emit(
        "scheduler_tick", "info",
        summary=f"스케줄러 tick — {len(candidates)}건 후보, {summary.refreshed}건 갱신, {summary.changed}건 변동",
        detail={
            "candidates": len(candidates),
            "refreshed": summary.refreshed,
            "changed": summary.changed,
            "sold_out": summary.sold_out,
        },
    )
    await session.commit()

    return {
        "candidates": len(candidates),
        "refreshed": summary.refreshed,
        "changed": summary.changed,
        "sold_out": summary.sold_out,
    }


# ══════════════════════════════════════════════════════════════
# 오토튠 백그라운드 루프 (무한 반복)
# ══════════════════════════════════════════════════════════════

import asyncio as _asyncio

_autotune_task: Optional[_asyncio.Task] = None
_autotune_running = False
_autotune_last_tick: Optional[str] = None
_autotune_cycle_count = 0


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
                from backend.domain.samba.collector.scheduler import get_refresh_candidates
                from backend.domain.samba.collector.refresher import refresh_products_bulk
                from backend.domain.samba.collector.repository import SambaCollectedProductRepository
                from backend.domain.samba.warroom.service import SambaMonitorService

                now = datetime.now(timezone.utc)
                candidates = await get_refresh_candidates(session, now)

                if candidates:
                    repo = SambaCollectedProductRepository(session)
                    products = []
                    for pid in candidates:
                        p = await repo.get_async(pid)
                        if p:
                            products.append(p)

                    results, summary = await refresh_products_bulk(products)

                    # DB 업데이트
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
                        updates["price_history"] = history[:200]

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

                        await repo.update_async(r.product_id, **updates)

                    await session.commit()

                    monitor = SambaMonitorService(session)
                    await monitor.emit(
                        "scheduler_tick", "info",
                        summary=f"오토튠 — {len(candidates)}건 후보, {summary.refreshed}건 갱신, {summary.changed}건 변동",
                        detail={
                            "candidates": len(candidates),
                            "refreshed": summary.refreshed,
                            "changed": summary.changed,
                            "sold_out": summary.sold_out,
                        },
                    )
                    await session.commit()
                    log.info("[오토튠] tick 완료: %d건 후보, %d건 갱신", len(candidates), summary.refreshed)
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


@router.post("/autotune/start")
async def autotune_start():
    """오토튠 무한 루프 시작."""
    global _autotune_task, _autotune_running, _autotune_cycle_count
    if _autotune_running:
        return {"ok": True, "status": "already_running"}
    _autotune_running = True
    _autotune_cycle_count = 0
    _autotune_task = _asyncio.create_task(_autotune_loop())
    return {"ok": True, "status": "started"}


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
