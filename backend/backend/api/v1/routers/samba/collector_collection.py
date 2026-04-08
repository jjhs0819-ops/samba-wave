"""SambaWave Collector — 수집/보강 엔드포인트."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.proxy.musinsa import RateLimitError
from backend.domain.samba.collector.grouping import (
    generate_group_key,
    parse_color_from_name,
)
from backend.domain.samba.collector.refresher import _site_intervals

from backend.api.v1.routers.samba.collector_common import (
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
            raise HTTPException(
                400, "지원하지 않는 URL입니다. source_site를 지정해주세요."
            )

    svc = _get_services(session)

    if site == "MUSINSA":
        import re
        from urllib.parse import urlparse, parse_qs
        from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie

        # 무신사 로그인(쿠키) 필수 체크
        cookie_check = await get_musinsa_cookie(session)
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
            search_filter = await svc.create_filter(
                {
                    "source_site": "MUSINSA",
                    "name": keyword,
                    "keyword": url,
                    "category_filter": category_filter or None,
                    "requested_count": requested_count,
                }
            )
            filter_id = search_filter.id

            cookie = await get_musinsa_cookie(session)
            client = MusinsaClient(cookie=cookie)

            # 기존 수집 상품 수 확인
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

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
                        keyword=keyword,
                        page=page,
                        size=100,
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
                    await asyncio.sleep(
                        _site_intervals.get("MUSINSA", 1.0)
                    )  # 적응형 인터벌
                except Exception:
                    break

            if not all_items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            # 기존 상품 ID 일괄 조회 (중복 체크 — 단일 쿼리)
            candidate_ids = [
                str(item.get("siteProductId", item.get("goodsNo", "")))
                for item in all_items
            ]
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
                    # 긴 상세이미지 분할 (추가이미지 보충분)
                    orig_cnt = detail.get(
                        "originalImageCount", len(detail.get("images", []))
                    )
                    if orig_cnt < len(detail.get("images", [])):
                        from backend.domain.samba.image.service import split_long_images

                        detail["images"] = await split_long_images(
                            detail["images"], orig_cnt, session
                        )

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
                        new_cost = (
                            _raw_cost
                            if (_raw_cost is not None and _raw_cost > 0)
                            else (detail.get("salePrice") or 0)
                        )
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = (
                        [c.strip() for c in raw_cat.split(">") if c.strip()]
                        if raw_cat
                        else []
                    )
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
                        detail,
                        goods_no,
                        filter_id,
                        "MUSINSA",
                        new_cost,
                        _sale_price,
                        _original_price,
                        raw_cat,
                        cat_parts,
                        raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch()
                except RateLimitError:
                    logger.warning(
                        f"[무신사] 요청 제한 감지 — 수집 중단 (수집완료: {saved}/{len(targets)})"
                    )
                    rate_limited = True
                    break
                except Exception as e:
                    logger.warning(f"[수집 실패] {goods_no}: {e}")
                await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))

            # 잔여 버퍼 flush
            await _flush_batch()

            # 검색그룹에 최근수집일 업데이트
            await svc.update_filter(
                filter_id,
                {
                    "last_collected_at": datetime.now(timezone.utc),
                },
            )

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
            match = (
                re.search(r"/products/(\d+)", url)
                or re.search(r"goodsNo=(\d+)", url)
                or re.search(r"/(\d+)", url)
            )
            if not match:
                raise HTTPException(
                    400, "무신사 상품 URL에서 상품번호를 찾을 수 없습니다"
                )
            goods_no = match.group(1)

            # 블랙리스트 체크 — 수집차단된 상품 스킵
            if await _is_blacklisted(session, "MUSINSA", goods_no):
                raise HTTPException(400, f"수집차단된 상품입니다 ({goods_no})")

            cookie = await get_musinsa_cookie(session)
            client = MusinsaClient(cookie=cookie)
            data = await client.get_goods_detail(goods_no)
            if not data or not data.get("name"):
                raise HTTPException(502, "무신사 상품 조회 실패")
            # 긴 상세이미지 분할 (추가이미지 보충분)
            orig_cnt = data.get("originalImageCount", len(data.get("images", [])))
            if orig_cnt < len(data.get("images", [])):
                from backend.domain.samba.image.service import split_long_images

                data["images"] = await split_long_images(
                    data["images"], orig_cnt, session
                )

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
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

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
                "color": data.get("color", "")
                or parse_color_from_name(data.get("name", "")),
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
                collected = await svc.update_collected_product(
                    existing_row.id, product_data
                )
                return {
                    "type": "single",
                    "saved": 1,
                    "updated": True,
                    "product": collected,
                }
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
            search_filter = await svc.create_filter(
                {
                    "source_site": "KREAM",
                    "name": keyword,
                    "keyword": url,
                }
            )
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
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

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
                site_pid = str(item.get("siteProductId") or item.get("id") or "")
                if not site_pid or site_pid in existing_ids:
                    continue
                bulk_items.append(
                    {
                        "source_site": "KREAM",
                        "site_product_id": site_pid,
                        "search_filter_id": filter_id,
                        "name": item.get("name", ""),
                        "brand": item.get("brand", ""),
                        "original_price": item.get(
                            "originalPrice", item.get("retailPrice", 0)
                        ),
                        "sale_price": item.get("salePrice", item.get("retailPrice", 0)),
                        "images": item.get("images", [item.get("imageUrl", "")])
                        if (item.get("images") or item.get("imageUrl"))
                        else [],
                        "similar_no": None,
                        "group_key": generate_group_key(
                            brand=item.get("brand", ""),
                            similar_no=None,
                            style_code=item.get("styleCode", ""),
                            name=item.get("name", ""),
                        ),
                        "status": "collected",
                    }
                )

            created_count = 0
            if bulk_items:
                created_count = await svc.bulk_create_products(bulk_items)

            # 검색그룹에 최근수집일 업데이트
            from datetime import datetime, timezone

            await svc.update_filter(
                filter_id,
                {
                    "last_collected_at": datetime.now(timezone.utc),
                },
            )

            return {
                "type": "search",
                "keyword": keyword,
                "filter_id": filter_id,
                "filter_name": keyword,
                "total_found": len(items_list),
                "saved": created_count,
                "skipped_duplicates": len(items_list) - created_count,
            }

        else:
            match = re.search(r"/products/(\d+)", url)
            if not match:
                raise HTTPException(
                    400, "KREAM 상품 URL에서 상품번호를 찾을 수 없습니다"
                )
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
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

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
                if "tags" not in kream_product_data or not kream_product_data.get(
                    "tags"
                ):
                    kream_product_data.pop("tags", None)
                collected = await svc.update_collected_product(
                    existing_row.id, kream_product_data
                )
                return {
                    "type": "single",
                    "saved": 1,
                    "updated": True,
                    "product": collected,
                }
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
            search_filter = await svc.create_filter(
                {
                    "source_site": "SSG",
                    "name": keyword,
                    "keyword": url,
                    "requested_count": 100,
                }
            )
            filter_id = search_filter.id

            client = SSGSourcingClient()

            # 기존 수집 수 확인
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

            existing_count = await svc.product_repo.count_async(
                filters={"search_filter_id": filter_id}
            )
            remaining = max(0, 100 - existing_count)
            if remaining <= 0:
                return {
                    "type": "search",
                    "keyword": keyword,
                    "filter_id": filter_id,
                    "message": f"이미 {existing_count}개 수집됨",
                    "saved": 0,
                    "enriched": 0,
                }

            # 검색

            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(
                        keyword=keyword, page=page, size=40
                    )
                    if not items:
                        break
                    all_items.extend(items)
                    await asyncio.sleep(_site_intervals.get("SSG", 1.0))
                except Exception:
                    break

            if not all_items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            # 중복 필터
            candidate_ids = [
                str(item.get("siteProductId", item.get("goodsNo", "")))
                for item in all_items
            ]
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
                        new_cost = (
                            _raw_cost
                            if (_raw_cost is not None and _raw_cost > 0)
                            else (detail.get("salePrice") or 0)
                        )
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = (
                        [c.strip() for c in raw_cat.split(">") if c.strip()]
                        if raw_cat
                        else []
                    )
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
                        detail,
                        item_id,
                        filter_id,
                        "SSG",
                        new_cost,
                        _sale_price,
                        _original_price,
                        raw_cat,
                        cat_parts,
                        raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch()
                except Exception as e:
                    logger.warning(f"[SSG 수집 실패] {item_id}: {e}")
                await asyncio.sleep(_site_intervals.get("SSG", 1.0))

            await _flush_batch()
            await svc.update_filter(
                filter_id, {"last_collected_at": datetime.now(timezone.utc)}
            )

            return {
                "type": "search",
                "keyword": keyword,
                "filter_id": filter_id,
                "total_found": len(all_items),
                "saved": saved,
                "enriched": saved,
                "skipped_sold_out": skipped_sold_out,
            }

        else:
            # 단일 상품 URL
            match = re.search(r"itemId=(\d+)", url) or re.search(r"/item/(\d+)", url)
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

            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

            existing_stmt = select(CPModel).where(
                CPModel.source_site == "SSG",
                CPModel.site_product_id == item_id,
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
                collected = await svc.update_collected_product(
                    existing_row.id, product_data
                )
                return {
                    "type": "single",
                    "saved": 1,
                    "updated": True,
                    "product": collected,
                }
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
            search_filter = await svc.create_filter(
                {
                    "source_site": "LOTTEON",
                    "name": keyword,
                    "keyword": url,
                    "requested_count": 100,
                }
            )
            filter_id = search_filter.id

            client = LotteonSourcingClient()

            # 기존 수집 수 확인
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

            existing_count = await svc.product_repo.count_async(
                filters={"search_filter_id": filter_id}
            )
            remaining = max(0, 100 - existing_count)
            if remaining <= 0:
                return {
                    "type": "search",
                    "keyword": keyword,
                    "filter_id": filter_id,
                    "message": f"이미 {existing_count}개 수집됨",
                    "saved": 0,
                    "enriched": 0,
                }

            # 검색

            all_items = []
            max_pages = max(1, (remaining // 40) + 1)
            for page in range(1, min(max_pages + 1, 11)):
                try:
                    items = await client.search_products(
                        keyword=keyword, page=page, size=40
                    )
                    if not items:
                        break
                    all_items.extend(items)
                    await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))
                except Exception:
                    break

            if not all_items:
                raise HTTPException(502, f"'{keyword}' 검색 결과가 없습니다")

            # 중복 필터
            candidate_ids = [
                str(item.get("siteProductId", item.get("goodsNo", "")))
                for item in all_items
            ]
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
                        new_cost = (
                            _raw_cost
                            if (_raw_cost is not None and _raw_cost > 0)
                            else (detail.get("salePrice") or 0)
                        )
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = (
                        [c.strip() for c in raw_cat.split(">") if c.strip()]
                        if raw_cat
                        else []
                    )
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
                        detail,
                        item_id,
                        filter_id,
                        "LOTTEON",
                        new_cost,
                        _sale_price,
                        _original_price,
                        raw_cat,
                        cat_parts,
                        raw_detail_html,
                    )
                    _batch_buf.append(svc.prepare_product_data(product_data))
                    saved += 1
                    if len(_batch_buf) >= _BATCH_SIZE:
                        await _flush_batch()
                except Exception as e:
                    logger.warning(f"[LOTTEON 수집 실패] {item_id}: {e}")
                await asyncio.sleep(_site_intervals.get("LOTTEON", 0.5))

            await _flush_batch()
            await svc.update_filter(
                filter_id, {"last_collected_at": datetime.now(timezone.utc)}
            )

            return {
                "type": "search",
                "keyword": keyword,
                "filter_id": filter_id,
                "total_found": len(all_items),
                "saved": saved,
                "enriched": saved,
                "skipped_sold_out": skipped_sold_out,
            }

        else:
            # 단일 상품 URL
            match = re.search(r"/product/(LO\d+)", url) or re.search(
                r"/product/(\d+)", url
            )
            if not match:
                raise HTTPException(
                    400, "롯데ON 상품 URL에서 상품번호를 찾을 수 없습니다"
                )
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

            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as CPModel,
            )

            existing_stmt = select(CPModel).where(
                CPModel.source_site == "LOTTEON",
                CPModel.site_product_id == item_id,
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
                collected = await svc.update_collected_product(
                    existing_row.id, product_data
                )
                return {
                    "type": "single",
                    "saved": 1,
                    "updated": True,
                    "product": collected,
                }
            else:
                collected = await svc.create_collected_product(product_data)
                return {"type": "single", "saved": 1, "product": collected}

    raise HTTPException(400, f"'{site}' 사이트 수집은 아직 지원하지 않습니다")


# ═══════════════════════════════════════
# 브랜드 소싱 — 카테고리 스캔 + 그룹 일괄 생성
# ═══════════════════════════════════════
# 구 brand-scan 엔드포인트는 하단 "카테고리 스캔" 섹션의
# 통합 brand-scan 엔드포인트로 대체됨 (MUSINSA + LOTTEON 지원)


# 구 brand-create-groups 엔드포인트는 하단 통합 엔드포인트로 대체됨 (MUSINSA + LOTTEON 지원)


class BrandRefreshRequest(BaseModel):
    brand: str
    brand_name: str = ""
    gf: str = "A"
    options: dict = {}


@router.post("/brand-refresh")
async def brand_refresh(
    req: BrandRefreshRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """브랜드 추가수집 — 신규 카테고리 그룹 생성 + 기존 그룹 요청수 갱신."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    from backend.api.v1.routers.samba.collector_common import _get_services
    from urllib.parse import urlencode, urlparse, parse_qs

    svc = _get_services(session)
    client = MusinsaClient()

    # 1) 카테고리 스캔
    try:
        categories = await client.scan_brand_categories(
            brand=req.brand,
            gf=req.gf,
            keyword=req.brand_name or req.brand,
        )
    except Exception as e:
        raise HTTPException(500, f"카테고리 스캔 실패: {e}")

    # 2) 기존 그룹 조회 — brand + category 코드로 매칭
    all_filters = await svc.list_filters()
    existing_cat_codes: dict[str, Any] = {}  # categoryCode → filter
    for f in all_filters:
        if f.source_site != "MUSINSA":
            continue
        try:
            parsed = urlparse(f.keyword or "")
            qs = parse_qs(parsed.query)
            f_brand = qs.get("brand", [""])[0]
            f_cat = qs.get("category", [""])[0]
            if f_brand == req.brand and f_cat:
                existing_cat_codes[f_cat] = f
        except Exception:
            continue

    new_groups = 0
    updated_groups = 0

    for cat in categories:
        cat_code = cat.get("categoryCode", "")
        count = cat.get("count", 0)
        path = cat.get("path", "")

        if cat_code in existing_cat_codes:
            # 기존 그룹 — 요청수를 현재 카테고리 상품수로 갱신
            f = existing_cat_codes[cat_code]
            if count > (f.requested_count or 0):
                await svc.update_filter(f.id, {"requested_count": count})
                updated_groups += 1
        else:
            # 신규 카테고리 — 그룹 생성
            cat_name = path.replace(" > ", "_").replace("/", "_")
            group_name = f"MUSINSA_{req.brand_name or req.brand}_{cat_name}"
            params = {
                "keyword": req.brand_name or req.brand,
                "brand": req.brand,
                "category": cat_code,
                "gf": req.gf,
            }
            if req.options.get("excludePreorder"):
                params["excludePreorder"] = "1"
            if req.options.get("excludeBoutique"):
                params["excludeBoutique"] = "1"
            if req.options.get("maxDiscount"):
                params["maxDiscount"] = "1"
            keyword_url = f"https://www.musinsa.com/search/goods?{urlencode(params)}"
            try:
                await svc.create_filter(
                    {
                        "source_site": "MUSINSA",
                        "keyword": keyword_url,
                        "name": group_name,
                        "requested_count": count,
                    }
                )
                new_groups += 1
            except Exception as e:
                logger.warning(f"[추가수집] 그룹 생성 실패 {group_name}: {e}")

    total_cats = len(categories)
    logger.info(
        f"[추가수집] {req.brand}: 스캔 {total_cats}개, 신규 {new_groups}개, 갱신 {updated_groups}개"
    )
    return {
        "scanned": total_cats,
        "new_groups": new_groups,
        "updated_groups": updated_groups,
        "message": f"스캔 {total_cats}개 카테고리 / 신규 그룹 {new_groups}개 생성 / 기존 {updated_groups}개 요청수 갱신",
    }


@router.post("/collect-filter/{filter_id}", status_code=200)
async def collect_by_filter(
    filter_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """검색그룹 기반 수집 — Job 큐에 등록하여 백그라운드 실행."""
    from backend.domain.samba.job.repository import SambaJobRepository
    from backend.domain.samba.job.service import SambaJobService

    svc = _get_services(session)
    search_filter = await svc.filter_repo.get_async(filter_id)
    if not search_filter:
        raise HTTPException(404, "필터를 찾을 수 없습니다")

    job_svc = SambaJobService(SambaJobRepository(session))
    job = await job_svc.create_job(
        {
            "job_type": "collect",
            "payload": {
                "filter_id": filter_id,
                "source_site": search_filter.source_site,
            },
        }
    )
    await session.commit()
    return {"job_id": job.id, "status": job.status, "filter_id": filter_id}


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
        cookie = (
            cookie_setting.value
            if cookie_setting and hasattr(cookie_setting, "value")
            else ""
        )

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

    elif body.source_site == "LOTTEON":
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        data = await client.search_products(
            keyword=body.keyword, page=body.page, size=body.size
        )
        # 브랜드 필터링: 키워드와 브랜드명이 일치하는 상품만 반환
        # (롯데ON은 URL에 브랜드 파라미터가 없어 다른 브랜드 상품이 섞임)
        keyword_lower = body.keyword.strip().lower()
        filtered = [
            p for p in data if keyword_lower in (p.get("brand", "") or "").lower()
        ]
        return {"success": True, "data": filtered if filtered else data}

    raise HTTPException(
        400, f"'{body.source_site}' 키워드 검색은 아직 지원하지 않습니다"
    )


@router.post("/enrich/{product_id}")
async def enrich_product(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """수집 상품의 상세 정보를 소싱사이트 API에서 보강 (카테고리, 옵션, 상세이미지 등)."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    svc = _get_services(session)
    product = await svc.get_collected_product(product_id)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다")

    if product.source_site == "MUSINSA" and product.site_product_id:
        from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie

        cookie = await get_musinsa_cookie(session)

        client = MusinsaClient(cookie=cookie)
        try:
            detail = await client.get_goods_detail(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"무신사 상세 조회 실패: {str(e)}")

        if not detail or not detail.get("name"):
            raise HTTPException(502, "무신사 상세 조회 실패: 데이터 없음")
        # 긴 상세이미지 분할 (추가이미지 보충분)
        orig_cnt = detail.get("originalImageCount", len(detail.get("images", [])))
        if orig_cnt < len(detail.get("images", [])):
            from backend.domain.samba.image.service import split_long_images

            detail["images"] = await split_long_images(
                detail["images"], orig_cnt, session
            )

        # get_goods_detail은 { category: "키즈 > ...", category1: "키즈", ... } 형태로 반환
        from datetime import datetime, timezone

        # 가격 0 허용: None이 아닌 경우에만 업데이트, 0도 유효한 값으로 처리
        api_sale = detail.get("salePrice")
        api_original = detail.get("originalPrice")
        new_sale_price = api_sale if api_sale is not None else product.sale_price
        new_original_price = (
            api_original if api_original is not None else product.original_price
        )

        new_sale_status = detail.get("saleStatus", "in_stock")
        # 최대혜택가: best_benefit_price → cost 컬럼에 저장 (0은 None으로 처리)
        _raw_cost = detail.get("bestBenefitPrice")
        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else None
        # 가격/재고만 업데이트 (카테고리, 브랜드, 상세HTML 등은 변경하지 않음)
        updates = {
            "original_price": new_original_price,
            "sale_price": new_sale_price,
            "cost": new_cost,
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
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
        }

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
        cat_parts = (
            [c.strip() for c in cat_str.split(">") if c.strip()] if cat_str else []
        )

        fast_prices = [
            o.get("kreamFastPrice", 0) for o in opts if o.get("kreamFastPrice", 0) > 0
        ]
        general_prices = [
            o.get("kreamGeneralPrice", 0)
            for o in opts
            if o.get("kreamGeneralPrice", 0) > 0
        ]
        sale_p = (
            min(fast_prices)
            if fast_prices
            else (pd.get("salePrice") or product.sale_price)
        )
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
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
        }

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
        for field in (
            "style_code",
            "sex",
            "manufacturer",
            "origin",
            "material",
            "care_instructions",
            "quality_guarantee",
            "color",
            "video_url",
            "detail_html",
            "images",
            "options",
        ):
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
            "options": detail.get("options", []),
        }
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        updated = await svc.update_collected_product(product_id, updates)
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
        }

    if product.source_site == "FashionPlus" and product.site_product_id:
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient
        from datetime import datetime, timezone

        client = FashionPlusClient()
        try:
            detail = await client.get_detail(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"패션플러스 상세 조회 실패: {str(e)}")

        new_sale = detail.get("sale_price") or product.sale_price
        new_orig = detail.get("original_price") or product.original_price
        shipping_fee = detail.get("shipping_fee", 0) or 0
        new_cost = new_sale + shipping_fee
        new_images = detail.get("images") or []

        new_options = detail.get("options") or []
        updates: dict[str, Any] = {
            "sale_price": new_sale,
            "original_price": new_orig,
            "cost": new_cost,
            "sourcing_shipping_fee": shipping_fee,
        }
        if new_options:
            updates["options"] = new_options

        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sale_price": new_sale,
            "original_price": new_orig,
            "cost": new_cost,
            "options": detail.get("options", []),
        }
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        updated = await svc.update_collected_product(product_id, updates)
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
        }

    # 플러그인 기반 소싱처 (FashionPlus, Nike, Adidas 등)
    from backend.domain.samba.plugins import SOURCING_PLUGINS

    _src = product.source_site or ""
    plugin = SOURCING_PLUGINS.get(_src) or SOURCING_PLUGINS.get(_src.upper())
    if plugin and product.site_product_id:
        try:
            from datetime import datetime, timezone

            result = await plugin.refresh(product)
            updates: dict[str, Any] = {}
            if result.new_sale_price is not None:
                updates["sale_price"] = result.new_sale_price
            if result.new_original_price is not None:
                updates["original_price"] = result.new_original_price
            if result.new_cost is not None:
                updates["cost"] = result.new_cost
            if result.new_sale_status:
                updates["sale_status"] = result.new_sale_status
            if result.new_options is not None:
                updates["options"] = result.new_options
            if result.error:
                return {"success": False, "message": result.error}
            if not updates:
                return {"success": True, "message": "변동 없음", "product": product}
            # 가격이력 스냅샷
            snapshot = {
                "date": datetime.now(timezone.utc).isoformat(),
                "sale_price": updates.get("sale_price", product.sale_price),
                "original_price": updates.get("original_price", product.original_price),
                "cost": updates.get("cost", product.cost),
            }
            history = list(product.price_history or [])
            history.insert(0, snapshot)
            updates["price_history"] = _trim_history(history)
            updated = await svc.update_collected_product(product_id, updates)
            return {
                "success": True,
                "enriched_fields": list(updates.keys()),
                "product": updated,
            }
        except Exception as e:
            raise HTTPException(502, f"{product.source_site} 갱신 실패: {e}")

    raise HTTPException(
        400, f"'{product.source_site}' 상세 보강은 아직 지원하지 않습니다"
    )


@router.post("/enrich-all")
async def enrich_all_products(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """카테고리가 비어있는 모든 MUSINSA 수집 상품의 상세 정보를 일괄 보강."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient
    import asyncio

    svc = _get_services(session)
    all_products = await svc.list_collected_products(skip=0, limit=1000)

    # 카테고리 없는 MUSINSA 상품만
    targets = [
        p
        for p in all_products
        if p.source_site == "MUSINSA" and p.site_product_id and not p.category1
    ]

    if not targets:
        return {"enriched": 0, "message": "보강할 상품이 없습니다"}

    # 쿠키 로드
    from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie

    cookie = await get_musinsa_cookie(session)

    client = MusinsaClient(cookie=cookie)
    enriched = 0

    for product in targets:
        try:
            detail = await client.get_goods_detail(product.site_product_id)
            if not detail or not detail.get("name"):
                continue
            # 긴 상세이미지 분할 (추가이미지 보충분)
            orig_cnt = detail.get("originalImageCount", len(detail.get("images", [])))
            if orig_cnt < len(detail.get("images", [])):
                from backend.domain.samba.image.service import split_long_images

                detail["images"] = await split_long_images(
                    detail["images"], orig_cnt, session
                )

            new_sale_status = detail.get("saleStatus", "in_stock")
            api_sale = detail.get("salePrice")
            api_original = detail.get("originalPrice")
            new_sale_price = api_sale if api_sale is not None else product.sale_price
            new_original_price = (
                api_original if api_original is not None else product.original_price
            )
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


# ── 카테고리 스캔 ──────────────────────────────────────────────────────────────


class BrandScanRequest(BaseModel):
    brand: str = ""
    gf: str = "A"
    keyword: str = ""
    source_site: str = "MUSINSA"
    selected_brands: list[str] = []


class BrandDiscoverRequest(BaseModel):
    keyword: str = ""
    source_site: str = "LOTTEON"


@router.post("/brand-discover")
async def brand_discover(body: BrandDiscoverRequest):
    """키워드로 소싱처에서 발견된 브랜드 목록 반환 (사용자 선택용).

    프론트에서 이 결과로 체크박스 목록을 표시하고, 사용자가 선택한
    브랜드를 `/brand-scan`의 `selected_brands`로 전달한다.
    """
    if not body.keyword:
        raise HTTPException(400, "keyword가 필요합니다")

    if body.source_site == "LOTTEON":
        from backend.domain.samba.plugins.sourcing.lotteon import LotteonSourcingPlugin

        plugin = LotteonSourcingPlugin()
        return await plugin.discover_brands(body.keyword)

    raise HTTPException(400, f"브랜드 탐색 미지원 소싱처: {body.source_site}")


@router.get("/gsshop-scan-progress")
async def gsshop_scan_progress():
    """GS샵 카테고리 스캔 진행 상황 폴링."""
    from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient

    return GsShopSourcingClient.scan_progress or {"stage": "idle"}


@router.post("/brand-scan")
async def brand_scan(
    body: BrandScanRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """키워드/브랜드로 소싱처 카테고리 분포를 스캔하여 검색그룹 생성에 활용.

    지원 소싱처: MUSINSA, LOTTEON, GSSHOP
    """
    keyword = body.keyword or body.brand
    if not keyword:
        raise HTTPException(400, "keyword 또는 brand가 필요합니다")

    if body.source_site == "GSSHOP":
        from backend.domain.samba.plugins.sourcing.gsshop import GsShopSourcingPlugin

        plugin = GsShopSourcingPlugin()
        return await plugin.scan_categories(keyword)

    if body.source_site == "LOTTEON":
        from backend.domain.samba.plugins.sourcing.lotteon import LotteonSourcingPlugin

        plugin = LotteonSourcingPlugin()
        # selected_brands가 없으면 keyword 자체를 단일 브랜드로 사용 (하위 호환)
        selected = body.selected_brands or [keyword]
        return await plugin.scan_categories(keyword, selected_brands=selected)

    if body.source_site == "MUSINSA":
        # 무신사 쿠키 로드
        from backend.domain.samba.forbidden.model import SambaSettings
        from sqlmodel import select as sql_select

        try:
            row = (
                await session.execute(
                    sql_select(SambaSettings).where(
                        SambaSettings.key == "musinsa_cookie"
                    )
                )
            ).scalar_one_or_none()
            cookie = (row.value if row and row.value else "") or ""
        except Exception:
            cookie = ""
        if not cookie:
            raise HTTPException(
                400,
                "무신사 쿠키가 없습니다. 확장앱에서 무신사 로그인 후 다시 시도하세요.",
            )
        return await _scan_musinsa_categories(keyword, body.brand, body.gf, cookie)

    if body.source_site in ("ABCmart", "GrandStage"):
        from backend.domain.samba.plugins.sourcing.abcmart import AbcMartPlugin

        plugin = AbcMartPlugin()
        return await plugin.scan_categories(keyword)

    if body.source_site == "Nike":
        from backend.domain.samba.plugins.sourcing.nike import NikePlugin

        plugin = NikePlugin()
        return await plugin.scan_categories(keyword)

    raise HTTPException(400, f"카테고리 스캔 미지원 소싱처: {body.source_site}")


async def _scan_musinsa_categories(
    keyword: str, brand: str = "", gf: str = "A", cookie: str = ""
) -> dict:
    """무신사 카테고리 스캔 — 검색 결과 상위 20개 상품 상세 조회 후 카테고리 분포 집계."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    client = MusinsaClient(cookie=cookie)
    search_result = await client.search_products(keyword, size=20, brand=brand, gf=gf)
    products = search_result.get("data", [])
    if not products:
        return {"categories": [], "total": 0, "groupCount": 0}

    # 동시성 3개로 상세 조회
    sem = asyncio.Semaphore(3)
    cat_counter: dict[str, int] = {}

    async def _fetch(p: dict) -> None:
        async with sem:
            spid = p.get("siteProductId") or p.get("site_product_id") or ""
            if not spid:
                return
            try:
                detail = await client.get_goods_detail(spid)
                c1 = detail.get("category1", "")
                c2 = detail.get("category2", "")
                c3 = detail.get("category3", "")
                if not c1:
                    return
                parts = [c for c in [c1, c2, c3] if c]
                path = " > ".join(parts)
                # category code는 무신사 categoryCode 필드
                code = detail.get("categoryCode", c3 or c2 or c1)
                key = f"{code}||{path}||{c1}||{c2}||{c3}"
                cat_counter[key] = cat_counter.get(key, 0) + 1
            except Exception:
                pass

    await asyncio.gather(*[_fetch(p) for p in products], return_exceptions=True)

    categories = []
    for key, count in sorted(cat_counter.items(), key=lambda x: -x[1]):
        code, path, c1, c2, c3 = key.split("||")
        categories.append(
            {
                "categoryCode": code,
                "path": path,
                "count": count,
                "category1": c1,
                "category2": c2,
                "category3": c3,
            }
        )

    return {
        "categories": categories,
        "total": sum(c["count"] for c in categories),
        "groupCount": len(categories),
    }


# ── 브랜드 그룹 생성 ──────────────────────────────────────────────────────────


class BrandCreateGroupsRequest(BaseModel):
    brand: str = ""
    brand_name: str = ""
    gf: str = "A"
    categories: list[dict] = []
    requested_count_per_group: int = 0
    applied_policy_id: Optional[str] = None
    options: dict = {}
    source_site: str = "MUSINSA"
    selected_brands: list[str] = []


@router.post("/brand-create-groups")
async def brand_create_groups(
    body: BrandCreateGroupsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """카테고리 스캔 결과에서 선택한 카테고리별 검색그룹 생성.

    지원 소싱처: MUSINSA, LOTTEON
    """
    if not body.categories:
        raise HTTPException(400, "categories가 비어있습니다")

    svc = _get_services(session)
    created_groups = []

    for cat in body.categories:
        code = cat.get("categoryCode", "")
        path = cat.get("path", "")
        count = cat.get("count", 0)

        # 그룹명: "{SITE}_{브랜드}_{카테고리}"
        # Nike: source_site와 브랜드가 동일하므로 브랜드 라벨 생략
        label = body.brand_name or body.brand or "브랜드"
        segments = path.split(" > ") if path else [code]
        # Nike: 카테고리 경로에서 "Nike" 제거 (source_site로 충분)
        if body.source_site == "Nike":
            segments = [s for s in segments if s != "Nike"]
        path_tail = "_".join(segments) if segments else code
        if body.source_site == "Nike":
            group_name = f"{body.source_site}_{path_tail}"
        else:
            group_name = f"{body.source_site}_{label}_{path_tail}"

        # 수집 요청 수: 0 이하이면 스캔 카운트(실제 상품수) 사용
        req_count = body.requested_count_per_group
        if req_count <= 0:
            req_count = max(count, 1)

        # 소싱처별 keyword 및 category_filter 결정
        if body.source_site == "MUSINSA":
            parts = [
                f"keyword={body.brand_name or body.brand}",
                "keywordType=keyword",
                f"gf={body.gf}",
            ]
            if body.brand:
                parts.append(f"brand={body.brand}")
            if code:
                parts.append(f"category={code}")
            keyword = "https://www.musinsa.com/search/goods?" + "&".join(parts)
            category_filter = code or None
        elif body.source_site in ("ABCmart", "GrandStage"):
            from urllib.parse import quote as _quote

            _label = body.brand_name or body.brand or keyword or ""
            keyword = (
                f"https://abcmart.a-rt.com/display/search-word/result"
                f"?searchWord={_quote(_label)}"
            )
            category_filter = code or None
        elif body.source_site == "Nike":
            from urllib.parse import quote as _quote_nike

            _label = body.brand_name or body.brand or keyword or ""
            keyword = f"https://www.nike.com/kr/w?q={_quote_nike(_label)}"
            category_filter = code or None
        elif body.source_site == "GSShop":
            import base64 as _b64
            from urllib.parse import quote as _quote_gs

            _label = body.brand_name or body.brand or ""
            _eh = _b64.b64encode(
                '{"part":"DEPT","selected":"opt-part"}'.encode()
            ).decode()
            keyword = (
                f"https://www.gsshop.com/shop/search/main.gs"
                f"?tq={_quote_gs(_label)}&eh={_quote_gs(_eh)}"
            )
            category_filter = code or None
        else:  # LOTTEON
            from urllib.parse import quote as _quote_lt

            _brand_label = body.brand_name or body.brand or ""
            # 롯데백화점(mallId=2) 검색 URL로 저장 (가품 방지 목적)
            if body.selected_brands:
                _brands_q = _quote_lt(",".join(body.selected_brands))
                keyword = (
                    f"https://www.lotteon.com/csearch/search/search"
                    f"?render=search&platform=pc&q={_quote_lt(_brand_label)}&mallId=2&brands={_brands_q}"
                )
            else:
                keyword = (
                    f"https://www.lotteon.com/csearch/search/search"
                    f"?render=search&platform=pc&q={_quote_lt(_brand_label)}&mallId=2"
                )
            # 합산된 BC코드들을 콤마로 연결 (같은 path의 여러 BC코드)
            bc_codes = cat.get("bc_codes") or ([code] if code else [])
            category_filter = ",".join(bc_codes) if bc_codes else None

        filter_data: dict = {
            "source_site": body.source_site,
            "name": group_name,
            "keyword": keyword,
            "requested_count": req_count,
            "category_filter": category_filter,
        }
        if body.applied_policy_id:
            filter_data["applied_policy_id"] = body.applied_policy_id

        try:
            sf = await svc.create_filter(filter_data)
            created_groups.append(
                {
                    "id": str(sf.id),
                    "name": group_name,
                    "count": req_count,
                    "path": path,
                }
            )
        except Exception as e:
            # 중복 그룹은 건너뜀
            import logging

            logging.getLogger(__name__).warning(f"그룹 생성 스킵: {group_name} — {e}")

    return {
        "created": len(created_groups),
        "groups": created_groups,
    }
