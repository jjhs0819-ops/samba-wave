"""Nike 소싱 클라이언트 - 상품 검색/상세 조회.

사이트: https://www.nike.com/kr
수집 방식: __NEXT_DATA__ SSR 데이터에서 상품 목록 추출.
Nike KR 검색 페이지는 SSR로 상품 데이터를 인라인 JSON에 포함.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from backend.utils.logger import logger

HEADERS = {
  "User-Agent": (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
  ),
  "Accept": "text/html",
  "Accept-Language": "ko-KR,ko;q=0.9",
}


class NikeClient:
  """Nike KR 소싱 클라이언트."""

  SEARCH_URL = "https://www.nike.com/kr/w"
  DETAIL_URL = "https://www.nike.com/kr/t"

  async def search(self, keyword: str, page: int = 1) -> dict[str, Any]:
    """상품 검색 — __NEXT_DATA__에서 productGroupings 추출."""
    params = {"q": keyword}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
      resp = await client.get(self.SEARCH_URL, params=params, headers=HEADERS)
      resp.raise_for_status()

      products = self._parse_next_data(resp.text)
      logger.info(f"[Nike] 검색 '{keyword}' → {len(products)}건")
      return {"products": products, "total": len(products)}

  async def get_detail(self, product_code: str) -> dict[str, Any]:
    """상품 상세 조회 — PDP 페이지의 __NEXT_DATA__에서 추출."""
    # Nike PDP URL은 슬러그 기반이므로 검색으로 찾아야 함
    result = await self.search(product_code)
    products = result.get("products", [])
    match = next(
      (p for p in products if p.get("site_product_id") == product_code),
      products[0] if products else None,
    )
    if match:
      return match
    return {"error": f"상품 {product_code}를 찾을 수 없습니다."}

  @staticmethod
  def _parse_next_data(html: str) -> list[dict[str, Any]]:
    """__NEXT_DATA__ JSON에서 상품 목록 추출."""
    nd_match = re.search(
      r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not nd_match:
      return []

    try:
      nd = json.loads(nd_match.group(1))
    except json.JSONDecodeError:
      return []

    wall = (
      nd.get("props", {})
      .get("pageProps", {})
      .get("initialState", {})
      .get("Wall", {})
    )
    groupings = wall.get("productGroupings", [])

    products = []
    for group in groupings:
      props = group.get("properties", {})
      group_products = group.get("products", [])

      for prod in group_products:
        copy = prod.get("copy", {})
        prices = prod.get("prices", {})
        images = prod.get("colorwayImages", {})

        title = copy.get("title", "") or props.get("title", "")
        subtitle = copy.get("subTitle", "") or props.get("subtitle", "")
        name = f"{title} {subtitle}".strip() if subtitle else title

        current_price = prices.get("currentPrice", 0)
        initial_price = prices.get("initialPrice", 0)

        img_url = images.get("portraitURL", "") or images.get("squarishURL", "")

        product_code = prod.get("productCode", "")
        pdp_url = prod.get("pdpUrl", {})
        url = pdp_url.get("url", "") if isinstance(pdp_url, dict) else ""

        product_type = prod.get("productType", "")
        # 카테고리 매핑
        cat_map = {
          "FOOTWEAR": "신발",
          "APPAREL": "의류",
          "ACCESSORIES": "액세서리",
          "EQUIPMENT": "장비",
        }
        category1 = cat_map.get(product_type, product_type)

        products.append({
          "site_product_id": product_code,
          "name": name or f"Nike {product_code}",
          "original_price": initial_price,
          "sale_price": current_price or initial_price,
          "images": [img_url] if img_url else [],
          "brand": "Nike",
          "source_site": "Nike",
          "category": f"Nike > {category1}" if category1 else "Nike",
          "category1": "Nike",
          "category2": category1,
          "category3": "",
          "options": [],
          "detail_html": "",
        })

    return products
