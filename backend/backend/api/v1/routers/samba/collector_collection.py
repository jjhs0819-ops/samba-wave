"""SambaWave Collector — 수집/보강 엔드포인트."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.cache import cache
from backend.domain.samba.proxy.musinsa import RateLimitError
from backend.domain.samba.collector.grouping import generate_group_key, parse_color_from_name
from backend.domain.samba.collector.refresher import _site_intervals, _site_consecutive_errors

from backend.api.v1.routers.samba.collector_common import (
    _blacklist_cache,
    _load_blacklist,
    _invalidate_blacklist_cache,
    _is_blacklisted,
    _clean_text,
    _build_product_data,
    _trim_history,
    _build_kream_price_snapshot,
    _get_services,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collector", tags=["samba-collector"])


# ── Inline DTOs ──

class CollectByUrlRequest(BaseModel):
    url: str
    source_site: Optional[str] = None  # auto-detect if not provided


class CollectByKeywordRequest(BaseModel):
    source_site: str = "MUSINSA"
    keyword: str
    page: int = 1
    size: int = 30


class BlockProductRequest(BaseModel):
    product_ids: list[str]


# ── 블랙리스트 ──

@router.get("/blacklist")
async def get_collection_blacklist(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """수집 블랙리스트 조회."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key="collection_blacklist")
    return row.value if row and isinstance(row.value, list) else []


@router.post("/blacklist/unblock")
async def unblock_products(
    body: BlockProductRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """블랙리스트에서 해제."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key="collection_blacklist")
    if not row or not isinstance(row.value, list):
        return {"ok": True, "removed": 0}
    remove_set = set(body.product_ids)  # site_product_id 목록
    before = len(row.value)
    row.value = [b for b in row.value if b.get("site_product_id") not in remove_set]
    session.add(row)
    await session.commit()
    _invalidate_blacklist_cache()
    return {"ok": True, "removed": before - len(row.value)}


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

            # 검색 필터 파라미터 추출 (브랜드, 가격 범위, 성별 등)
            brand_filter = qs.get("brand", [""])[0]
            min_price_raw = qs.get("minPrice", [""])[0]
            max_price_raw = qs.get("maxPrice", [""])[0]
            gf_filter = qs.get("gf", ["A"])[0]
            min_price = int(min_price_raw) if min_price_raw.isdigit() else None
            max_price = int(max_price_raw) if max_price_raw.isdigit() else None

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
                raise HTTPException(
                    status_code=200,
                    detail=f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)",
                )

            # 필요한 만큼만 검색 (페이지당 100개)

            all_items = []
            max_pages = max(1, (remaining // 100) + 1)
            for page in range(1, min(max_pages + 1, 11)):  # 최대 10페이지
                try:
                    data = await client.search_products(
                        keyword=keyword, page=page, size=100,
                        category=category_filter,
                        brand=brand_filter,
                        min_price=min_price,
                        max_price=max_price,
                        gf=gf_filter,
                    )
                    items = data.get("data", [])
                    if not items:
                        break
                    all_items.extend(items)
                    await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌
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
                # 블랙리스트 체크
                if await _is_blacklisted(session, "MUSINSA", goods_no):
                    logger.info(f"[수집] 블랙리스트 스킵: MUSINSA/{goods_no}")
                    continue
                try:
                    detail = await client.get_goods_detail(goods_no)
                    if not detail or not detail.get("name"):
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    if exclude_preorder and detail.get("saleStatus") == "preorder":
                        skipped_preorder += 1
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue
                    if exclude_boutique and detail.get("isBoutique"):
                        skipped_boutique += 1
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
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
                await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))

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

            # 블랙리스트 체크 — 수집차단된 상품 스킵
            if await _is_blacklisted(session, "MUSINSA", goods_no):
                raise HTTPException(400, f"수집차단된 상품입니다 ({goods_no})")

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

            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(keyword=keyword, page=page, size=40)
                    if not items:
                        break
                    all_items.extend(items)
                    await asyncio.sleep(_site_intervals.get("SSG", 1.0))
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
                        await asyncio.sleep(_site_intervals.get("SSG", 1.0))
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
                await asyncio.sleep(_site_intervals.get("SSG", 1.0))

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

            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(keyword=keyword, page=page, size=40)
                    if not items:
                        break
                    all_items.extend(items)
                    await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
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
                        await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
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
                await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))

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
                await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))  # 적응형 인터벌
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
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    p_name = detail.get("name", "")[:30]

                    if _exclude_preorder and detail.get("saleStatus") == "preorder":
                        total_skipped_preorder += 1
                        yield _sse("log", {"message": f"  {p_name} — 예약배송 제외"})
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue
                    if _exclude_boutique and detail.get("isBoutique"):
                        total_skipped_boutique += 1
                        yield _sse("log", {"message": f"  {p_name} — 부티끄 제외"})
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
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
                        await asyncio.sleep(rle.retry_after)
                    else:
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                    continue
                except Exception as e:
                    logger.warning(f"[수집 실패] {goods_no}: {e}")
                    yield _sse("log", {"message": f"  {goods_no} — 수집 실패"})
                await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))

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
                await asyncio.sleep(0.3)

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
                    await asyncio.sleep(1.0)

            await svc.update_filter(filter_id, {"last_collected_at": datetime.now(timezone.utc)})
            yield _sse("done", {"saved": saved, "total_found": len(items_list), "skipped_duplicates": len(existing_ids)})

        return StreamingResponse(_wrap_stream(_stream_kream()), media_type="text/event-stream")

    # ── SSG 수집 (collect-by-filter) ──
    elif site == "SSG":
        async def _stream_ssg():

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
                    await asyncio.sleep(_site_intervals.get("SSG", 1.0))
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
                        await asyncio.sleep(_site_intervals.get("SSG", 1.0))
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
                await asyncio.sleep(_site_intervals.get("SSG", 1.0))

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
                    await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
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
                        await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
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
                await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))

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
                    requested_count = search_filter.requested_count or 100
                    if site == "FashionPlus":
                        from backend.domain.samba.proxy.fashionplus import FashionPlusClient
                        client = FashionPlusClient()
                    elif site == "Nike":
                        from backend.domain.samba.proxy.nike import NikeClient
                        client = NikeClient()
                    elif site == "Adidas":
                        from backend.domain.samba.proxy.adidas import AdidasClient
                        client = AdidasClient()

                    result = await client.search(keyword, max_count=requested_count)
                    items_list = result.get("products", [])
                    total_found = result.get("total", 0)
                    last_error = result.get("last_error", "")
                    yield _sse("log", {"message": f"[{site}] API 총 상품수: {total_found}건, 수집됨: {len(items_list)}건"})
                    if last_error:
                        yield _sse("log", {"message": f"[{site}] 페이지네이션 중단 사유: {last_error}"})
                else:
                    # 확장앱 큐 기반
                    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
                    yield _sse("log", {"message": f"[{site}] 확장앱에 수집 요청 중... (최대 60초 대기)"})
                    request_id, future = SourcingQueue.add_search_job(site, keyword)
                    try:
                        result = await asyncio.wait_for(future, timeout=60)
                    except asyncio.TimeoutError:
                        SourcingQueue.resolvers.pop(request_id, None)
                        yield _sse("done", {"saved": 0, "message": "확장앱 응답 타임아웃. 확장앱이 실행 중인지 확인하세요."})
                        return
                    items_list = result.get("products", [])

                yield _sse("log", {"message": f"[{site}] {len(items_list)}건 검색됨"})

                saved = 0
                target = min(len(items_list), search_filter.requested_count or 100)
                target_items = items_list[:target]

                for item in target_items:
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
                        "color": item.get("color", ""),
                        "origin": item.get("origin", ""),
                        "material": item.get("material", ""),
                        "video_url": item.get("video_url", ""),
                        "style_code": item.get("style_code", ""),
                        "sex": item.get("sex", ""),
                        "manufacturer": item.get("manufacturer", ""),
                        "care_instructions": item.get("care_instructions", ""),
                        "quality_guarantee": item.get("quality_guarantee", ""),
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
                    await asyncio.sleep(0.1)

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

        # 옵션 보강 (HTML 태그 정제)
        if detail.get("options"):
            cleaned = []
            for opt in detail["options"]:
                if isinstance(opt, dict):
                    co = {**opt}
                    for k in ("name", "value", "label"):
                        if k in co and isinstance(co[k], str):
                            co[k] = _clean_text(co[k])
                    cleaned.append(co)
                else:
                    cleaned.append(opt)
            updates["options"] = cleaned

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

    if product.source_site == "Nike" and product.site_product_id:
        from backend.domain.samba.proxy.nike import NikeClient
        from datetime import datetime, timezone
        try:
            detail = await NikeClient().get_detail(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"Nike 상세 조회 실패: {e}")
        if detail.get("error"):
            raise HTTPException(502, detail["error"])

        updates = {}
        for field in ("style_code", "sex", "manufacturer", "origin", "material",
                      "care_instructions", "quality_guarantee", "color", "video_url",
                      "detail_html", "images", "options"):
            val = detail.get(field)
            if val is not None and val != "" and val != []:
                updates[field] = val

        sale_price = detail.get("sale_price")
        original_price = detail.get("original_price")
        if sale_price is not None:
            updates["sale_price"] = sale_price
        if original_price is not None:
            updates["original_price"] = original_price

        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sale_price": sale_price or product.sale_price,
            "original_price": original_price or product.original_price,
        }
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
