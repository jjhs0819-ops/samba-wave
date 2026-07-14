"""번개장터 소싱처 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)

# 판매글이 아니라 "매입/구매 요청" 글 — 검색어는 일치하지만 실제 재고가 아님.
# 2026-07-13 사고: 매입글의 임의 희망가를 원가로 오인식 → 원가 없는 상품을 실제
# 시세보다 훨씬 낮게 이베이 등록 → 판매 후 손해 확정. 검색 결과에서 원천 차단.
_WTB_KEYWORDS = (
    "매입",
    "구매",
    "삽니다",
    "구합니다",
    "구해",
    "원합니다",
    "찾습니다",
    "사려고",
    "구매요청",
    "사요",
    "사겠",
)


def _is_wtb_post(name: str) -> bool:
    return any(k in (name or "") for k in _WTB_KEYWORDS)


# 복수장 묶음(Lot) 상품 — 이베이 카테고리 183455(CCG Mixed Card Lots)가 조건값을
# 전부 거부하다 카탈로그매칭(25604)까지 실패하는 등 API 등록 안정성이 낮음(2026-07-14
# ACE SPEC 카드 3장 묶음 등록 실패로 확인). 싱글카드(183454)만 자동화 대상 유지.
_LOT_KEYWORDS = ("일괄", "묶음", "세트", "lot", "Lot", "LOT")


def _is_lot_set(name: str) -> bool:
    return any(k in (name or "") for k in _LOT_KEYWORDS)


class BunjangPlugin(SourcingPlugin):
    """번개장터 소싱처 플러그인.

    concurrency=3, request_interval=0.3: 공개 API 과호출 방지
    filters: brand_id, min_price, max_price, condition,
             min_seller_sales(거래내역 최소건수), min_seller_rating(평점 최소값), limit
    """

    site_name = "BUNJANG"
    concurrency = 3
    request_interval = 0.3

    async def search(self, keyword: str, **filters) -> list[dict]:
        """번개장터 키워드 검색 — 판매자 신뢰도 필터 지원."""
        from backend.domain.samba.proxy.bunjang import BunjangClient

        min_sales = filters.get("min_seller_sales")
        min_rating = filters.get("min_seller_rating")
        limit = int(filters.get("limit", 0) or 0)
        # 신뢰도 필터가 있으면 탈락분을 감안해 DOM 스크래핑 목표치를 넉넉히 잡음
        dom_count = max(limit * 4, 30) if (min_sales or min_rating) and limit else 30

        client = BunjangClient()
        items = await self.safe_call(
            client.search(
                keyword,
                brand_id=str(filters.get("brand_id", "")),
                min_price=int(filters.get("min_price", 0) or 0),
                max_price=int(filters.get("max_price", 0) or 0),
                condition=str(filters.get("condition", "")),
                dom_count=dom_count,
            )
        )
        _before = len(items)
        items = [it for it in items if not _is_wtb_post(it.get("name", ""))]
        if _before != len(items):
            logger.info(
                f"[번개장터] 매입/구매글 {_before - len(items)}건 제외 (검색결과 {_before}→{len(items)})"
            )
        _before_lot = len(items)
        items = [it for it in items if not _is_lot_set(it.get("name", ""))]
        if _before_lot != len(items):
            logger.info(
                f"[번개장터] LOT/일괄 세트 {_before_lot - len(items)}건 제외 (검색결과 {_before_lot}→{len(items)})"
            )

        if not min_sales and not min_rating:
            return items[:limit] if limit else items

        passed: list[dict] = []
        for it in items:
            detail = await self.safe_call(client.get_detail(it["site_product_id"]))
            if detail.get("error"):
                continue
            sales = detail.get("_seller_sales_count", 0)
            rating = detail.get("_seller_review_rating", 0)
            if min_sales and sales < min_sales:
                continue
            if min_rating and rating < min_rating:
                continue
            passed.append({**it, **detail})
            if limit and len(passed) >= limit:
                break
        return passed

    async def get_detail(self, site_product_id: str) -> dict:
        """번개장터 상품 상세 조회."""
        from backend.domain.samba.proxy.bunjang import BunjangClient

        client = BunjangClient()
        return await self.safe_call(client.get_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/판매상태 갱신."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.bunjang import BunjangClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "")

        if not site_product_id:
            return RefreshResult(product_id=product_id, error="site_product_id 없음")

        try:
            client = BunjangClient()
            fresh = await client.get_detail(site_product_id)
        except Exception as e:
            logger.warning(f"[번개장터] 갱신 실패 {site_product_id}: {e}")
            return RefreshResult(product_id=product_id, error=str(e))

        if not fresh or fresh.get("error"):
            return RefreshResult(
                product_id=product_id, error=fresh.get("error", "상세 조회 실패")
            )

        new_sale_price = fresh.get("sale_price")
        old_sale_price = getattr(product, "sale_price", None)
        price_changed = new_sale_price is not None and new_sale_price != old_sale_price

        # 번개장터는 C2C 단일재고 — 판매완료되면 그 개체는 영구 품절(재입고 없음)
        new_sale_status = "sold_out" if fresh.get("is_sold_out") else "in_stock"
        old_sale_status = getattr(product, "sale_status", "in_stock")
        stock_changed = new_sale_status != old_sale_status

        return RefreshResult(
            product_id=product_id,
            new_sale_price=new_sale_price,
            new_original_price=fresh.get("original_price"),
            new_sale_status=new_sale_status,
            changed=price_changed,
            stock_changed=stock_changed,
        )
