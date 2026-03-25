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
    """가격/재고 갱신 — 상세 페이지 재조회로 최신 데이터 추출."""
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
      detail = await self.safe_call(
        client.get_product_detail(site_product_id)
      )

      if not detail:
        return RefreshResult(
          product_id=product_id,
          error=f"롯데ON 상세 조회 실패: {site_product_id}",
        )

      new_sale_price = detail.get("salePrice", 0)
      new_original_price = detail.get("originalPrice", 0)
      is_sold_out = detail.get("isOutOfStock", False) or detail.get("isSoldOut", False)

      # bestBenefitPrice → new_cost (실질 매입가)
      best_benefit_price = detail.get("bestBenefitPrice", 0)

      # 옵션 데이터 변환
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
        new_original_price=float(new_original_price) if new_original_price else None,
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
