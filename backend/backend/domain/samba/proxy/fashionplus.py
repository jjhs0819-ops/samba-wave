"""패션플러스 소싱 클라이언트 - 상품 검색/상세 조회.

사이트: https://www.fashionplus.co.kr
실제 동작 확인된 API: /search/goods/fetch (JSON 응답)
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.utils.logger import logger

HEADERS = {
  "User-Agent": (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
  ),
  "Accept": "application/json",
  "Accept-Language": "ko-KR,ko;q=0.9",
  "Referer": "https://www.fashionplus.co.kr/",
}


class FashionPlusClient:
  """패션플러스 소싱 클라이언트."""

  SEARCH_API = "https://www.fashionplus.co.kr/search/goods/fetch"
  DETAIL_URL = "https://www.fashionplus.co.kr/goods/detail"

  async def search(self, keyword: str, page: int = 1) -> dict[str, Any]:
    """상품 검색 — /search/goods/fetch JSON API."""
    params = {"searchWord": keyword, "page": str(page)}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
      resp = await client.get(self.SEARCH_API, params=params, headers=HEADERS)
      resp.raise_for_status()
      data = resp.json()

      paginator = data.get("goodsPaginator", {})
      items = paginator.get("items", [])
      total = paginator.get("totalCount", len(items))

      products = [self._map_item(item) for item in items]
      logger.info(f"[패션플러스] 검색 '{keyword}' → {len(products)}건 (전체 {total})")
      return {"products": products, "total": total}

  async def get_detail(self, product_id: str) -> dict[str, Any]:
    """상품 상세 조회 — 검색 API로 상세 데이터 포함."""
    # 패션플러스는 상세 페이지가 SPA이므로 검색 API에서 가져온 데이터 활용
    # 또는 상품 ID로 직접 페이지 접근 후 JSON-LD 파싱
    url = f"{self.DETAIL_URL}/{product_id}"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
      resp = await client.get(url, headers={**HEADERS, "Accept": "text/html"})
      resp.raise_for_status()
      return self._parse_detail_html(resp.text, product_id)

  @staticmethod
  def _map_item(item: dict[str, Any]) -> dict[str, Any]:
    """API 응답 아이템 → 표준 형식 변환."""
    brand_info = item.get("brand") or {}
    brand_name = ""
    if isinstance(brand_info, dict):
      brand_name = brand_info.get("name", "")
    elif isinstance(brand_info, str):
      brand_name = brand_info

    thumbnail = item.get("thumbnailUrl", "")
    images = [thumbnail] if thumbnail else []

    return {
      "site_product_id": str(item.get("id") or item.get("no", "")),
      "name": item.get("name", ""),
      "original_price": int(item.get("consumerPrice", 0)),
      "sale_price": int(item.get("salePrice") or item.get("displayPrice", 0)),
      "images": images,
      "brand": brand_name,
      "source_site": "FashionPlus",
      "is_sold_out": item.get("isSoldout", False),
    }

  @staticmethod
  def _parse_detail_html(html: str, product_id: str) -> dict[str, Any]:
    """상세 페이지 HTML에서 JSON-LD/메타태그 파싱."""
    import json
    import re

    # JSON-LD 추출
    json_m = re.search(
      r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
      html, re.DOTALL,
    )
    if json_m:
      try:
        data = json.loads(json_m.group(1))
        if isinstance(data, list):
          data = next((d for d in data if d.get("@type") == "Product"), data[0] if data else {})
        if data.get("@type") == "Product":
          offers = data.get("offers", {})
          price = 0
          if isinstance(offers, dict):
            price = int(offers.get("price", 0))
          elif isinstance(offers, list) and offers:
            price = int(offers[0].get("price", 0))

          img = data.get("image", "")
          if isinstance(img, list):
            img = img[0] if img else ""

          brand_info = data.get("brand", {})
          brand = brand_info.get("name", "") if isinstance(brand_info, dict) else str(brand_info)

          return {
            "site_product_id": product_id,
            "name": data.get("name", ""),
            "original_price": price,
            "sale_price": price,
            "images": [img] if img else [],
            "brand": brand,
            "options": [],
            "source_site": "FashionPlus",
            "category": "", "category1": "", "category2": "", "category3": "",
            "detail_html": "",
          }
      except (json.JSONDecodeError, ValueError):
        pass

    # og:title 등 메타태그 fallback
    name_m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    price_m = re.search(r'<meta[^>]+property="product:price:amount"[^>]+content="(\d+)"', html)
    img_m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)

    return {
      "site_product_id": product_id,
      "name": name_m.group(1) if name_m else f"패션플러스 {product_id}",
      "original_price": int(price_m.group(1)) if price_m else 0,
      "sale_price": int(price_m.group(1)) if price_m else 0,
      "images": [img_m.group(1)] if img_m else [],
      "brand": "",
      "options": [],
      "source_site": "FashionPlus",
      "category": "", "category1": "", "category2": "", "category3": "",
      "detail_html": "",
    }
