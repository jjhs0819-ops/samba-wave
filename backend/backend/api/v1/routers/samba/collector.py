"""SambaWave Collector API router - 수집 필터 + 수집 상품."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency

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


class SearchFilterUpdate(BaseModel):
    name: Optional[str] = None
    keyword: Optional[str] = None
    category_filter: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    exclude_sold_out: Optional[bool] = None
    is_active: Optional[bool] = None


class CollectedProductCreate(BaseModel):
    source_site: str
    site_product_id: Optional[str] = None
    search_filter_id: Optional[str] = None
    name: str
    brand: Optional[str] = None
    original_price: float = 0
    sale_price: float = 0
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
    status: Optional[str] = None
    applied_policy_id: Optional[str] = None
    market_prices: Optional[dict] = None
    market_enabled: Optional[dict] = None
    is_sold_out: Optional[bool] = None


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
        data = f.model_dump() if hasattr(f, "model_dump") else dict(f)
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
    result = await svc.update_filter(filter_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "필터를 찾을 수 없습니다")
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
    limit: int = Query(50, ge=1, le=1000),
    status: Optional[str] = None,
    source_site: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_services(session)
    return await svc.list_collected_products(skip=skip, limit=limit, status=status)


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

            # 검색그룹(SearchFilter) 자동 생성
            search_filter = await svc.create_filter({
                "source_site": "MUSINSA",
                "name": keyword,
                "keyword": url,
                "category_filter": category_filter or None,
            })
            filter_id = search_filter.id

            cookie = await _get_musinsa_cookie()
            client = MusinsaClient(cookie=cookie)

            # 최대 3페이지 수집 (페이지당 100개)
            all_items = []
            for page in range(1, 4):
                try:
                    data = await client.search_products(keyword=keyword, page=page, size=100)
                    items = data.get("data", [])
                    if not items:
                        break
                    all_items.extend(items)
                except Exception:
                    break

            if not all_items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            # 기존 상품 ID 일괄 조회 (중복 체크 — 단일 쿼리)
            from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in all_items]
            existing_stmt = select(CPModel.site_product_id).where(
                CPModel.source_site == "MUSINSA",
                CPModel.site_product_id.in_(candidate_ids),  # type: ignore[union-attr]
            )
            existing_result = await session.execute(existing_stmt)
            existing_ids = {row[0] for row in existing_result.all()}

            # 일괄 저장 데이터 준비
            bulk_items = []
            for item in all_items:
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue

                raw_cat = item.get("category", "") or ""
                cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []

                bulk_items.append({
                    "source_site": "MUSINSA",
                    "site_product_id": site_pid,
                    "search_filter_id": filter_id,
                    "name": item.get("name", item.get("goodsName", "")),
                    "brand": item.get("brand", item.get("brandName", "")),
                    "original_price": item.get("originalPrice", item.get("normalPrice", 0)),
                    "sale_price": item.get("salePrice", item.get("price", 0)),
                    "images": item.get("images", []),
                    "options": item.get("options", []),
                    "category": raw_cat,
                    "category1": cat_parts[0] if len(cat_parts) > 0 else None,
                    "category2": cat_parts[1] if len(cat_parts) > 1 else None,
                    "category3": cat_parts[2] if len(cat_parts) > 2 else None,
                    "category4": cat_parts[3] if len(cat_parts) > 3 else None,
                    "status": "collected",
                    "is_sold_out": item.get("isSoldOut", False),
                })

            # 단일 트랜잭션 일괄 저장
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
                "total_found": len(all_items),
                "saved": len(created),
                "skipped_duplicates": len(all_items) - len(created),
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
            if not data.get("success"):
                raise HTTPException(502, data.get("message", "무신사 상품 조회 실패"))

            product_data = data.get("data", {})
            collected = await svc.create_collected_product({
                "source_site": "MUSINSA",
                "site_product_id": goods_no,
                "name": product_data.get("goodsNm", product_data.get("name", "")),
                "brand": product_data.get("brandNm", product_data.get("brand", "")),
                "original_price": product_data.get("normalPrice", product_data.get("originalPrice", 0)),
                "sale_price": product_data.get("goodsPrice", product_data.get("salePrice", 0)),
                "images": product_data.get("images", []),
                "options": product_data.get("options", []),
                "category": product_data.get("category", ""),
                "category1": product_data.get("category1", ""),
                "category2": product_data.get("category2", ""),
                "category3": product_data.get("category3", ""),
                "status": "collected",
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

            collected = await svc.create_collected_product({
                "source_site": "KREAM",
                "site_product_id": product_id,
                "name": product_data.get("name", ""),
                "brand": product_data.get("brand", ""),
                "original_price": product_data.get("originalPrice", product_data.get("retailPrice", 0)),
                "sale_price": product_data.get("salePrice", product_data.get("retailPrice", 0)),
                "images": product_data.get("images", []),
                "options": product_data.get("options", []),
                "category": product_data.get("category", ""),
                "category1": product_data.get("category1", ""),
                "category2": product_data.get("category2", ""),
                "category3": product_data.get("category3", ""),
                "status": "collected",
            })
            return {"type": "single", "saved": 1, "product": collected}

    raise HTTPException(400, f"'{site}' 사이트 수집은 아직 지원하지 않습니다")


@router.post("/collect-filter/{filter_id}", status_code=200)
async def collect_by_filter(
    filter_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """검색그룹 기반 재수집 — 필터의 keyword(URL)로 collect-by-url 재실행."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    from backend.domain.samba.proxy.kream import KreamClient

    svc = _get_services(session)
    search_filter = await svc.filter_repo.get_async(filter_id)
    if not search_filter:
        raise HTTPException(404, "필터를 찾을 수 없습니다")

    site = search_filter.source_site
    keyword_or_url = search_filter.keyword or search_filter.name

    # 무신사 쿠키 로드 헬퍼
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

    # 키워드 추출
    keyword = search_filter.name
    if keyword_or_url and ("http" in keyword_or_url):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(keyword_or_url).query)
        keyword = qs.get("keyword", [keyword])[0]

    if site == "MUSINSA":
        cookie = await _get_musinsa_cookie()
        client = MusinsaClient(cookie=cookie)

        all_items = []
        for page in range(1, 4):
            try:
                data = await client.search_products(keyword=keyword, page=page, size=100)
                items = data.get("data", [])
                if not items:
                    break
                all_items.extend(items)
            except Exception:
                break

        if not all_items:
            return {"saved": 0, "message": f"'{keyword}' 검색 결과가 없습니다"}

        # 중복 체크
        from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
        candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in all_items]
        existing_stmt = select(CPModel.site_product_id).where(
            CPModel.source_site == "MUSINSA",
            CPModel.site_product_id.in_(candidate_ids),  # type: ignore[union-attr]
        )
        existing_result = await session.execute(existing_stmt)
        existing_ids = {row[0] for row in existing_result.all()}

        bulk_items = []
        for item in all_items:
            site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
            if site_pid in existing_ids:
                continue
            raw_cat = item.get("category", "") or ""
            cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
            bulk_items.append({
                "source_site": "MUSINSA",
                "site_product_id": site_pid,
                "search_filter_id": filter_id,
                "name": item.get("name", item.get("goodsName", "")),
                "brand": item.get("brand", item.get("brandName", "")),
                "original_price": item.get("originalPrice", item.get("normalPrice", 0)),
                "sale_price": item.get("salePrice", item.get("price", 0)),
                "images": item.get("images", []),
                "options": item.get("options", []),
                "category": raw_cat,
                "category1": cat_parts[0] if len(cat_parts) > 0 else None,
                "category2": cat_parts[1] if len(cat_parts) > 1 else None,
                "category3": cat_parts[2] if len(cat_parts) > 2 else None,
                "category4": cat_parts[3] if len(cat_parts) > 3 else None,
                "status": "collected",
                "is_sold_out": item.get("isSoldOut", False),
            })

        created = []
        if bulk_items:
            created = await svc.bulk_create_collected_products(bulk_items)

        from datetime import datetime, timezone
        await svc.update_filter(filter_id, {
            "last_collected_at": datetime.now(timezone.utc),
        })

        return {
            "saved": len(created),
            "total_found": len(all_items),
            "skipped_duplicates": len(all_items) - len(created),
        }

    elif site == "KREAM":
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
            return {"saved": 0, "message": f"'{keyword}' 검색 결과가 없습니다"}

        items_list = items if isinstance(items, list) else []

        # 중복 체크
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
            site_pid = str(item.get("siteProductId") or item.get("id") or "")
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

        from datetime import datetime, timezone
        await svc.update_filter(filter_id, {
            "last_collected_at": datetime.now(timezone.utc),
        })

        return {
            "saved": len(created),
            "total_found": len(items_list),
            "skipped_duplicates": len(items_list) - len(created),
        }

    return {"saved": 0, "message": f"'{site}' 수집은 아직 지원하지 않습니다"}


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
        updates = {
            "category": detail.get("category") or product.category,
            "category1": detail.get("category1") or product.category1,
            "category2": detail.get("category2") or product.category2,
            "category3": detail.get("category3") or product.category3,
            "category4": detail.get("category4") or product.category4,
            "original_price": detail.get("originalPrice") or product.original_price,
            "sale_price": detail.get("salePrice") or product.sale_price,
            "brand": detail.get("brand") or product.brand,
        }

        # 옵션 보강
        if detail.get("options"):
            updates["options"] = detail["options"]

        # 이미지 보강
        if detail.get("images"):
            updates["images"] = detail["images"]

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

            updates = {
                "category": detail.get("category") or product.category,
                "category1": detail.get("category1") or product.category1,
                "category2": detail.get("category2") or product.category2,
                "category3": detail.get("category3") or product.category3,
                "category4": detail.get("category4") or product.category4,
                "brand": detail.get("brand") or product.brand,
                "original_price": detail.get("originalPrice") or product.original_price,
                "sale_price": detail.get("salePrice") or product.sale_price,
            }
            if detail.get("options"):
                updates["options"] = detail["options"]
            if detail.get("images"):
                updates["images"] = detail["images"]

            await svc.update_collected_product(product.id, updates)
            enriched += 1

            # Rate limit: 0.3초 간격
            await asyncio.sleep(0.3)
        except Exception:
            continue

    return {"enriched": enriched, "total_targets": len(targets)}
