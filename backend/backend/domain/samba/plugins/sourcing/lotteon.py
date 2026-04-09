"""롯데ON 소싱처 플러그인."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class LotteonSourcingPlugin(SourcingPlugin):
    """롯데ON 소싱처 플러그인.

    JSON-LD(schema.org Product) 마크업을 우선 파싱하여 정확도가 높다.
    bestBenefitPrice(최대혜택가)를 new_cost에 반영하여
    정책 적용 시 실질 매입가 기준으로 마진 계산이 가능하다.

    concurrency=2: 비교적 여유 있는 차단 정책
    request_interval=0.5: 요청 간 500ms 딜레이
    """

    site_name = "LOTTEON"
    concurrency = 2
    request_interval = 0.5

    async def search(self, keyword: str, **filters) -> list[dict]:
        """롯데ON 키워드 검색."""
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        page = filters.get("page", 1)
        size = filters.get("size", 40)
        return await self.safe_call(
            client.search_products(keyword, page=page, size=size, **filters)
        )

    async def get_detail(self, site_product_id: str) -> dict:
        """롯데ON 상품 상세 조회."""
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — pbf + benefits API로 빠른 갱신, 실패 시 HTML 폴백."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="롯데ON 상품 ID 없음",
            )

        try:
            client = LotteonSourcingClient()

            # ── 1단계: pbf API로 빠른 갱신 시도 ──
            pbf_client = await client._get_pbf_client()
            pbf_data = await client._fetch_pbf_pd_detail(site_product_id, pbf_client)

            if pbf_data:
                basic = pbf_data.get("basicInfo") or {}
                price_info = pbf_data.get("priceInfo") or {}
                sl_prc = client._safe_int(price_info.get("slPrc", 0))

                # benefits API로 혜택가 조회
                best_benefit_price = await client.fetch_benefit_price(
                    pbf_data, spd_no=site_product_id
                )

                # qapi로 프로모션가 조회
                qapi = await client.fetch_qapi_price(site_product_id)
                qapi_final = qapi.get("final", 0) if qapi else 0

                # 판매가 결정: 혜택가 > qapi > slPrc
                new_sale_price = sl_prc
                if qapi_final and 0 < qapi_final < sl_prc:
                    new_sale_price = qapi_final

                # 옵션별 재고 조회
                new_options = None
                opt_stock = await client.fetch_option_stock(
                    pbf_data, spd_no=site_product_id
                )
                if opt_stock:
                    new_options = opt_stock

                # 품절 판정
                stck_info = pbf_data.get("stckInfo") or {}
                stk_qty = client._safe_int(stck_info.get("stkQty", 0))
                is_sold_out = stk_qty == 0
                if new_options:
                    is_sold_out = all(o.get("isSoldOut") for o in new_options)

                logger.info(
                    f"[LOTTEON] pbf+benefits 갱신: {site_product_id} "
                    f"정가={sl_prc:,} 판매가={new_sale_price:,} "
                    f"혜택가={best_benefit_price or 0:,} "
                    f"qapi={qapi_final:,} 품절={is_sold_out}"
                )

                return RefreshResult(
                    product_id=product_id,
                    new_sale_price=float(new_sale_price) if new_sale_price else None,
                    new_original_price=float(sl_prc) if sl_prc else None,
                    new_cost=float(best_benefit_price) if best_benefit_price else None,
                    new_sale_status="sold_out" if is_sold_out else "in_stock",
                    new_options=new_options,
                    changed=True,
                )

            # ── 2단계: pbf 실패 시 HTML 폴백 ──
            logger.info(f"[LOTTEON] pbf 실패 → HTML 폴백: {site_product_id}")
            detail = await self.safe_call(client.get_product_detail(site_product_id))

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"롯데ON 상세 조회 실패: {site_product_id}",
                )

            new_sale_price = detail.get("salePrice", 0)
            new_original_price = detail.get("originalPrice", 0)
            is_sold_out = detail.get("isOutOfStock", False) or detail.get(
                "isSoldOut", False
            )
            best_benefit_price = detail.get("bestBenefitPrice", 0)

            new_options = None
            raw_options = detail.get("options", [])
            if raw_options:
                new_options = [
                    {
                        "name": opt.get("name", ""),
                        "price": opt.get("price", 0),
                        "stock": 0 if opt.get("isSoldOut") else opt.get("stock", 1),
                        "isSoldOut": opt.get("isSoldOut", False),
                    }
                    for opt in raw_options
                ]

            return RefreshResult(
                product_id=product_id,
                new_sale_price=float(new_sale_price) if new_sale_price else None,
                new_original_price=float(new_original_price)
                if new_original_price
                else None,
                new_cost=float(best_benefit_price) if best_benefit_price else None,
                new_sale_status="sold_out" if is_sold_out else "in_stock",
                new_options=new_options,
                new_images=detail.get("images"),
                new_detail_images=detail.get("detailImages"),
                new_free_shipping=detail.get("freeShipping"),
                new_same_day_delivery=detail.get("sameDayDelivery"),
                changed=True,
            )

        except Exception as e:
            logger.error(f"[LOTTEON] 갱신 실패: {site_product_id} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"롯데ON 갱신 실패: {e}",
            )
