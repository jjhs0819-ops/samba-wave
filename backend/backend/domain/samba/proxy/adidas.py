"""Adidas 소싱 클라이언트 - 상품 검색/상세 조회.

사이트: https://www.adidas.co.kr
수집 방식: /api/search/taxonomy JSON API 직접 호출.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.utils.logger import logger

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.adidas.co.kr/",
    "sec-ch-ua": '"Chromium";v="131"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


class AdidasClient:
    """Adidas KR 소싱 클라이언트."""

    SEARCH_API = "https://www.adidas.co.kr/api/search/taxonomy"
    DETAIL_URL = "https://www.adidas.co.kr/api/products"

    async def search(self, keyword: str, page: int = 1) -> dict[str, Any]:
        """상품 검색 — /api/search/taxonomy JSON API."""
        params = {"query": keyword}
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # 세션 쿠키 획득 (봇 차단 우회)
            await client.get(
                "https://www.adidas.co.kr",
                headers={
                    **HEADERS,
                    "Accept": "text/html",
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                },
            )
            resp = await client.get(self.SEARCH_API, params=params, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()

            item_list = data.get("itemList", {})
            items = item_list.get("items", [])
            total = item_list.get("count", len(items))

            products = [self._map_item(item) for item in items]
            logger.info(f"[Adidas] 검색 '{keyword}' → {len(products)}건 (전체 {total})")
            return {"products": products, "total": total}

    async def get_detail(self, product_id: str) -> dict[str, Any]:
        """상품 상세 조회 — API 또는 검색 결과에서 추출."""
        # 먼저 검색으로 찾기
        result = await self.search(product_id)
        products = result.get("products", [])
        match = next(
            (p for p in products if p.get("site_product_id") == product_id),
            products[0] if products else None,
        )
        if match:
            return match
        return {"error": f"상품 {product_id}를 찾을 수 없습니다."}

    @staticmethod
    def _map_item(item: dict[str, Any]) -> dict[str, Any]:
        """API 응답 아이템 → 표준 형식."""
        # 이미지 처리
        image_info = item.get("image", {})
        img_url = ""
        if isinstance(image_info, dict):
            src = image_info.get("src", "")
            if src:
                # cloudinary URL은 이미 완전한 URL
                img_url = (
                    src if src.startswith("http") else f"https://assets.adidas.com{src}"
                )
        elif isinstance(image_info, str):
            img_url = image_info

        # 가격
        price = item.get("price", 0)
        sale_price = item.get("salePrice", 0) or price

        # 카테고리
        category = item.get("category", "")
        division = item.get("division", "")
        sport = item.get("sport", "")
        cat_parts = [c for c in ["Adidas", category, division, sport] if c]

        # 할인율
        sale_pct = item.get("salePercentage", 0)

        return {
            "site_product_id": item.get("productId", ""),
            "name": item.get("displayName", "") or item.get("subTitle", ""),
            "original_price": price,
            "sale_price": sale_price,
            "images": [img_url] if img_url else [],
            "brand": "Adidas",
            "source_site": "Adidas",
            "category": " > ".join(cat_parts),
            "category1": "Adidas",
            "category2": category,
            "category3": division,
            "options": [],
            "detail_html": "",
            "is_sold_out": not item.get("orderable", True),
        }
