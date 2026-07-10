"""패션플러스 소싱처 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class FashionPlusPlugin(SourcingPlugin):
    """패션플러스 소싱처 플러그인.

    concurrency=3: 동시 3개 요청
    request_interval=0.5: 요청 간 500ms 딜레이
    """

    site_name = "FASHIONPLUS"
    concurrency = 3
    request_interval = 0.5

    async def discover_brands(self, keyword: str) -> dict:
        """패션플러스 브랜드 탐색."""
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        client = FashionPlusClient()
        return await self.safe_call(client.discover_brands(keyword))

    async def scan_categories(
        self, keyword: str, selected_brands: list[str] | None = None
    ) -> dict:
        """패션플러스 카테고리 스캔."""
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        client = FashionPlusClient()
        return await self.safe_call(
            client.scan_categories(keyword, selected_brands=selected_brands)
        )

    async def search(self, keyword: str, **filters) -> list[dict]:
        """패션플러스 키워드 검색."""
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        max_count = int(filters.get("max_count", 100))
        client = FashionPlusClient()
        result = await self.safe_call(client.search(keyword, max_count=max_count))
        return result.get("products", [])

    async def get_detail(self, site_product_id: str) -> dict:
        """패션플러스 상품 상세 조회."""
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        client = FashionPlusClient()
        return await self.safe_call(client.get_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — FashionPlusClient로 재조회 후 변경분 반환."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "")

        if not site_product_id:
            return RefreshResult(product_id=product_id, error="site_product_id 없음")

        try:
            client = FashionPlusClient()
            fresh = await client.get_detail(site_product_id)
        except Exception as e:
            logger.warning(f"[FashionPlus] 갱신 실패 {site_product_id}: {e}")
            return RefreshResult(product_id=product_id, error=str(e))

        if not fresh or not fresh.get("name"):
            return RefreshResult(product_id=product_id, error="상세 조회 실패")

        new_sale_price = fresh.get("sale_price")
        new_original_price = fresh.get("original_price")
        # 배송비 포함 원가 — sale_price 추출 실패 시 cost=None (배송비만 박는 폴백 금지)
        shipping_fee = fresh.get("shipping_fee", 3000)
        if new_sale_price is None or new_sale_price <= 0:
            new_cost = None
            _price_uncertain = True
            logger.warning(
                f"[FashionPlus][가격불확실] sale_price 추출 실패: {site_product_id} "
                f"→ cost 갱신 및 전송 보류"
            )
        else:
            new_cost = new_sale_price + shipping_fee
            _price_uncertain = False

        old_sale_price = getattr(product, "sale_price", None)
        old_cost = getattr(product, "cost", None)

        price_changed = (
            new_sale_price is not None
            and new_sale_price != old_sale_price
            or new_cost != old_cost
        )

        # 옵션 재고 갱신 — 패션플러스는 품절 사이즈를 옵션 API 응답에서 "제거"한다.
        # 따라서 (a) isSoldout HTML 플래그, (b) 빈 옵션 = 완전품절, (c) 사라진 사이즈를
        # stock=0 으로 복원 — 세 가지로 옵션제거 방식 품절을 감지한다 (#499 와 동일 로직,
        # 실제 오토튠이 쓰는 경로는 이 플러그인이므로 여기에 적용).
        new_options = fresh.get("options")
        opts_fetched = bool(fresh.get("_options_fetched"))
        html_sold_out = bool(fresh.get("is_sold_out"))

        # 사이즈별 품절 복원: old 옵션 중 new 에 없는 사이즈를 stock=0 으로 되살린다.
        # (재입고되면 API 가 그 옵션을 다시 반환 → 복원 안 함, 자가치유)
        old_options = getattr(product, "options", None) or []
        if opts_fetched and new_options and old_options:
            _new_keys = {
                (o.get("name") or "").strip()
                for o in new_options
                if isinstance(o, dict)
            }
            for _oo in old_options:
                if not isinstance(_oo, dict):
                    continue
                _nm = (_oo.get("name") or "").strip()
                if _nm and _nm not in _new_keys:
                    _merged = dict(_oo)
                    _merged["stock"] = 0
                    _merged["isSoldOut"] = True
                    new_options.append(_merged)

        stock_changed = False
        is_sold_out = False
        _soldout_via_html = False
        if html_sold_out:
            is_sold_out = True
            _soldout_via_html = True
        elif opts_fetched and not new_options:
            # 옵션 fetch 성공 + 옵션 0개 = 완전품절 (fetch 실패와 구분)
            is_sold_out = True
        elif new_options:
            is_sold_out = all(
                (o.get("isSoldOut", False) or (o.get("stock", 0) or 0) == 0)
                for o in new_options
            )

        # ── 품절 오탐 방어(재확인) ──
        # 옵션 API 가 일시적으로 빈/불완전 응답을 주면, 재고가 있는 상품이 '완전품절'로
        # 오판된다. 오토튠은 품절을 확정으로 보고 상품+마켓 리스팅을 영구 삭제하므로,
        # 한 번의 일시적 오탐이 살아있는 상품을 지워버리고 유령 주문을 유발한다(실사고).
        # HTML 의 명시적 품절 플래그(isSoldout)가 아닌 '옵션 기반' 품절 판정만,
        # 옵션을 1회 더 재조회해서 재고가 확인되면 in_stock 으로 정정한다. (자가치유)
        if is_sold_out and not _soldout_via_html:
            recheck = None
            try:
                recheck = await client.fetch_options(site_product_id)
            except Exception as _rc_e:
                # 차단(RateLimit)은 상위 재시도에 위임 — 오판 삭제 방지
                if type(_rc_e).__name__ == "RateLimitError":
                    raise
                logger.warning(
                    f"[FashionPlus] 품절 재확인 실패(기존 품절 유지): "
                    f"{site_product_id} - {_rc_e}"
                )
            if recheck:
                _instock = [
                    o
                    for o in recheck
                    if isinstance(o, dict)
                    and not (o.get("isSoldOut", False) or (o.get("stock", 0) or 0) == 0)
                ]
                if _instock:
                    logger.warning(
                        f"[FashionPlus] 품절 재확인=재고있음({len(_instock)}옵션) → "
                        f"품절 취소(오탐 방어): {site_product_id}"
                    )
                    new_options = recheck
                    is_sold_out = False

        new_sale_status = "sold_out" if is_sold_out else "in_stock"
        if new_sale_status != getattr(product, "sale_status", "in_stock"):
            stock_changed = True

        # 품절 확정이면 가격불확실이어도 sold_out 을 반영한다.
        # (패플은 품절 시 상세 가격이 0 → price_uncertain=True 가 되는데, 이때 옛 in_stock
        #  으로 덮어버리면 품절이 영원히 미반영된다. 품절은 확실하므로 uncertain 해제.)
        if is_sold_out:
            return RefreshResult(
                product_id=product_id,
                new_sale_price=None,
                new_original_price=None,
                new_cost=None,
                new_sale_status="sold_out",
                new_options=new_options,
                changed=False,
                stock_changed=True,
                price_uncertain=False,
            )

        # 가격불확실(품절 아님) — sale_price/cost/options 갱신 보류.
        # 옵션 stock 만 보고 in_stock 박으면, 이전 좀비 cost(예: 3000) 가 유지된 채
        # 마켓에 가짜 가격(8400 등)으로 노출되는 회귀.
        if _price_uncertain:
            return RefreshResult(
                product_id=product_id,
                new_sale_price=None,
                new_original_price=None,
                new_cost=None,
                new_sale_status=getattr(product, "sale_status", "in_stock"),
                new_options=None,
                changed=False,
                stock_changed=False,
                price_uncertain=True,
            )

        return RefreshResult(
            product_id=product_id,
            new_sale_price=new_sale_price,
            new_original_price=new_original_price,
            new_cost=new_cost,
            new_sale_status=new_sale_status,
            new_options=new_options,
            changed=price_changed,
            stock_changed=stock_changed,
            price_uncertain=_price_uncertain,
        )
