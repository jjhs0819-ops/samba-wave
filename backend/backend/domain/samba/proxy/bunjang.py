"""번개장터 소싱 클라이언트 - 상품 검색/상세 조회.

사이트: https://m.bunjang.co.kr
검색: api.bunjang.co.kr 검색 API가 브라우저 서명 헤더(X-BUN-AUTH-TOKEN/X-BUN-CONTEXT)를
     요구해 서버 직접호출 불가 — 확장앱 큐 방식(검색 페이지 DOM 스크래핑)으로 동작.
상세: 서명 헤더 불필요 — api.bunjang.co.kr 직접 호출 (판매자 신뢰도 포함).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from urllib.parse import quote

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
    "Referer": "https://m.bunjang.co.kr/",
}

SEARCH_API = "https://api.bunjang.co.kr/api/search/v8/pw/product/specs/keyword"
DETAIL_API = "https://api.bunjang.co.kr/api/pms/v1/products/{pid}/detail/web"
SEARCH_PAGE_BASE = "https://m.bunjang.co.kr/keywords/{keyword}"


class BunjangClient:
    """번개장터 소싱 클라이언트.

    검색은 확장앱 큐 방식으로 동작한다(브라우저가 검색 페이지를 열어 DOM 스크래핑).
    """

    # ── 확장앱 큐 (클래스 레벨, 서버 재시작 시 초기화) ──
    search_queue: list[dict[str, Any]] = []
    search_resolvers: dict[str, "asyncio.Future[Any]"] = {}

    async def search(
        self,
        keyword: str,
        brand_id: str = "",
        min_price: int = 0,
        max_price: int = 0,
        condition: str = "",
        exclude_ad: bool = True,
        dom_count: int = 30,
    ) -> list[dict[str, Any]]:
        """키워드 검색 (확장앱 큐 방식, 최대 90초 대기) — 광고상품(ad=true)은 기본 제외."""
        qparams: dict[str, str] = {}
        if brand_id:
            qparams["brandId"] = f'["{brand_id}"]'
        if min_price:
            qparams["minPrice"] = f'["{min_price}"]'
        if max_price:
            qparams["maxPrice"] = f'["{max_price}"]'
        if condition:
            qparams["condition"] = f'["{condition}"]'
        qs = "&".join(f"{k}={quote(v)}" for k, v in qparams.items())
        search_url = SEARCH_PAGE_BASE.format(keyword=quote(keyword))
        if qs:
            search_url += f"?{qs}"

        request_id = str(uuid.uuid4())
        BunjangClient.search_queue.append(
            {
                "requestId": request_id,
                "keyword": keyword,
                "url": search_url,
                "count": dom_count,
            }
        )
        logger.info(f'[번개장터] 검색 큐 등록 (확장앱): "{keyword}" ({request_id})')

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()
        BunjangClient.search_resolvers[request_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=90.0)
        except asyncio.TimeoutError:
            BunjangClient.search_resolvers.pop(request_id, None)
            raise Exception(
                "번개장터 검색 타임아웃 (90초). "
                "웨일 브라우저가 열려있고 확장앱이 활성화되어 있는지 확인해주세요."
            )

        items = result if isinstance(result, list) else []
        if exclude_ad:
            items = [it for it in items if not it.get("ad")]

        products = [self._map_search_item(it) for it in items]
        logger.info(f"[번개장터] 검색 '{keyword}' → {len(products)}건 (광고 제외)")
        return products

    async def get_detail(self, pid: str) -> dict[str, Any]:
        """상품 상세 조회 — 판매자 신뢰도(salesCount/reviewRating) 포함."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(DETAIL_API.format(pid=pid), headers=HEADERS)
            if resp.status_code == 404:
                return {"error": "상품을 찾을 수 없습니다."}
            resp.raise_for_status()
            data = resp.json()
        return self._map_detail(data.get("data", {}))

    @staticmethod
    def _map_search_item(item: dict[str, Any]) -> dict[str, Any]:
        pid = str(item.get("pid", ""))
        img_tpl = item.get("productImage", "")
        thumbnail = img_tpl.replace("{res}", "600") if img_tpl else ""
        return {
            "site_product_id": pid,
            "name": item.get("name", ""),
            "sale_price": item.get("price", 0),
            "original_price": item.get("price", 0),
            "images": [thumbnail] if thumbnail else [],
            "source_site": "BUNJANG",
            "source_url": f"https://m.bunjang.co.kr/products/{pid}",
            "is_sold_out": item.get("status") != "SELLING",
            "options": [],
            "_seller_uid": (item.get("shop") or {}).get("uid"),
        }

    @staticmethod
    def _map_detail(product_data: dict[str, Any]) -> dict[str, Any]:
        p = product_data.get("product", {})
        shop = product_data.get("shop", {})
        pid = str(p.get("pid", ""))
        img_tpl = p.get("imageUrl", "")
        thumbnail = (
            img_tpl.replace("{cnt}", "1").replace("{res}", "600") if img_tpl else ""
        )
        categories = p.get("categories", []) or []
        cat_names = [c.get("name", "") for c in categories if c.get("name")]
        brand_name = (p.get("brand") or {}).get("name", "")

        return {
            "site_product_id": pid,
            "name": p.get("name", ""),
            "sale_price": p.get("price", 0),
            "original_price": p.get("originPrice", p.get("price", 0)),
            "images": [thumbnail] if thumbnail else [],
            "brand": brand_name,
            "manufacturer": brand_name,
            "source_site": "BUNJANG",
            "source_url": f"https://m.bunjang.co.kr/products/{pid}",
            "category": " > ".join(cat_names),
            "category1": cat_names[0] if len(cat_names) > 0 else "",
            "category2": cat_names[1] if len(cat_names) > 1 else "",
            "options": [],
            "detail_html": f"<p>{p.get('description', '')}</p>",
            "is_sold_out": p.get("saleStatus") != "SELLING",
            # 판매자 신뢰도 — 수집 필터링용 (DB 저장 필드 아님)
            "_seller_uid": shop.get("uid"),
            "_seller_name": shop.get("name", ""),
            "_seller_sales_count": shop.get("salesCount", 0),
            "_seller_review_rating": shop.get("reviewRating", 0),
        }
