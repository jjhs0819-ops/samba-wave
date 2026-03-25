"""도매몰 크롤러 — domeme(도매매), ownerclan(오너클랜) 상품 검색.

실제 HTML 구조는 사이트 변경 시 _parse_product_list 내부 선택자만 수정하면 된다.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from backend.utils.logger import logger


# 소싱처별 기본 설정
SOURCES: Dict[str, Dict[str, str]] = {
    "domeme": {
        "base_url": "https://www.domeme.com",
        "search_url": "https://www.domeme.com/search/list",
    },
    "ownerclan": {
        "base_url": "https://ownerclan.com",
        "search_url": "https://ownerclan.com/product/search",
    },
}

# 공통 User-Agent (일반 브라우저 흉내)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _safe_int(value: Optional[str], default: int = 0) -> int:
    """문자열에서 숫자만 추출해 int 변환. 실패 시 default 반환."""
    if value is None:
        return default
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else default


class WholesaleCrawler:
    """도매몰 상품 검색 크롤러.

    사용 예시::

        async with WholesaleCrawler() as crawler:
            products = await crawler.search_products("domeme", "후드티", page=1, size=50)
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )

    # ──────────────────────────────────────────────
    # 컨텍스트 매니저 지원
    # ──────────────────────────────────────────────

    async def __aenter__(self) -> "WholesaleCrawler":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """httpx 클라이언트 종료."""
        await self._client.aclose()

    # ──────────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────────

    async def search_products(
        self,
        source: str,
        keyword: str,
        page: int = 1,
        size: int = 50,
    ) -> List[Dict[str, Any]]:
        """소싱처별 상품 검색 라우팅.

        Args:
            source: "domeme" | "ownerclan"
            keyword: 검색어
            page: 페이지 번호 (1-based)
            size: 페이지당 결과 수

        Returns:
            상품 딕셔너리 리스트. 오류 시 빈 리스트.
        """
        if source not in SOURCES:
            logger.warning(f"[WholesaleCrawler] 지원하지 않는 소싱처: {source}")
            return []

        if source == "domeme":
            return await self._search_domeme(keyword, page, size)
        if source == "ownerclan":
            return await self._search_ownerclan(keyword, page, size)
        return []

    # ──────────────────────────────────────────────
    # 소싱처별 검색 구현
    # ──────────────────────────────────────────────

    async def _search_domeme(
        self,
        keyword: str,
        page: int,
        size: int,
    ) -> List[Dict[str, Any]]:
        """도매매 상품 검색.

        도매매는 GET 방식 검색 파라미터를 사용한다.
        실제 응답 구조 변경 시 _parse_product_list 내 선택자 수정 필요.
        """
        url = SOURCES["domeme"]["search_url"]
        params = {
            "keyword": keyword,
            "pageNum": page,
            "pageSize": size,
        }
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            return self._parse_product_list(resp.text, "domeme")
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"[WholesaleCrawler] 도매매 HTTP 오류: {e.response.status_code} — {keyword}"
            )
            return []
        except Exception as e:
            logger.warning(f"[WholesaleCrawler] 도매매 검색 실패: {e} — {keyword}")
            return []

    async def _search_ownerclan(
        self,
        keyword: str,
        page: int,
        size: int,
    ) -> List[Dict[str, Any]]:
        """오너클랜 상품 검색.

        오너클랜은 GET 방식 파라미터를 사용한다.
        실제 응답 구조 변경 시 _parse_product_list 내 선택자 수정 필요.
        """
        url = SOURCES["ownerclan"]["search_url"]
        params = {
            "keyword": keyword,
            "page": page,
            "limit": size,
        }
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            return self._parse_product_list(resp.text, "ownerclan")
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"[WholesaleCrawler] 오너클랜 HTTP 오류: {e.response.status_code} — {keyword}"
            )
            return []
        except Exception as e:
            logger.warning(f"[WholesaleCrawler] 오너클랜 검색 실패: {e} — {keyword}")
            return []

    # ──────────────────────────────────────────────
    # HTML 파싱
    # ──────────────────────────────────────────────

    def _parse_product_list(
        self,
        html: str,
        source: str,
    ) -> List[Dict[str, Any]]:
        """HTML 응답에서 상품 목록 파싱.

        각 소싱처별 HTML 구조에 맞게 CSS 선택자를 적용한다.
        선택자가 맞지 않으면 빈 리스트를 반환하며, 실제 사이트 구조
        확인 후 selector를 조정해야 한다.

        Returns:
            [{"product_id", "name", "price", "retail_price",
              "category", "image_url", "detail_url"}, ...]
        """
        soup = BeautifulSoup(html, "html.parser")
        products: List[Dict[str, Any]] = []

        if source == "domeme":
            # 도매매 상품 카드 선택자 (실제 구조 확인 후 조정 필요)
            items = soup.select("ul.goods_list li.goods_item")
            for item in items:
                try:
                    # 상품 ID — data 속성 또는 링크에서 추출
                    link_el = item.select_one("a.goods_link")
                    href = link_el["href"] if link_el else ""
                    product_id = re.search(r"/goods/(\d+)", str(href))
                    product_id = product_id.group(1) if product_id else str(href)

                    # 상품명
                    name_el = item.select_one(".goods_name")
                    name = name_el.get_text(strip=True) if name_el else ""

                    # 도매가
                    price_el = item.select_one(".goods_price .sale_price, .price_sale")
                    price = _safe_int(price_el.get_text() if price_el else "0")

                    # 소비자가
                    retail_el = item.select_one(".goods_price .normal_price, .price_normal")
                    retail_price = _safe_int(retail_el.get_text() if retail_el else "0")

                    # 카테고리
                    cat_el = item.select_one(".goods_cate, .category")
                    category = cat_el.get_text(strip=True) if cat_el else None

                    # 이미지
                    img_el = item.select_one("img.goods_img, .thumb img")
                    image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

                    # 상세 URL
                    base = SOURCES["domeme"]["base_url"]
                    detail_url = f"{base}{href}" if href and not str(href).startswith("http") else str(href)

                    if not name:
                        continue

                    products.append({
                        "product_id": str(product_id),
                        "name": name,
                        "price": price,
                        "retail_price": retail_price if retail_price else price,
                        "category": category,
                        "image_url": image_url,
                        "detail_url": detail_url,
                    })
                except Exception as e:
                    logger.debug(f"[WholesaleCrawler] 도매매 상품 파싱 스킵: {e}")
                    continue

        elif source == "ownerclan":
            # 오너클랜 상품 카드 선택자 (실제 구조 확인 후 조정 필요)
            items = soup.select(".product_list .product_item, ul.prdList li")
            for item in items:
                try:
                    # 상품 ID
                    link_el = item.select_one("a[href*='/product/']")
                    href = link_el["href"] if link_el else ""
                    product_id = re.search(r"/product/(?:detail/)?(\d+)", str(href))
                    product_id = product_id.group(1) if product_id else str(href)

                    # 상품명
                    name_el = item.select_one(".prd_name, .product_name, strong.name")
                    name = name_el.get_text(strip=True) if name_el else ""

                    # 도매가
                    price_el = item.select_one(".sale_price, .prd_price .price, .selling_price")
                    price = _safe_int(price_el.get_text() if price_el else "0")

                    # 소비자가
                    retail_el = item.select_one(".consumer_price, .origin_price, .prd_price del")
                    retail_price = _safe_int(retail_el.get_text() if retail_el else "0")

                    # 카테고리
                    cat_el = item.select_one(".category, .cate_name")
                    category = cat_el.get_text(strip=True) if cat_el else None

                    # 이미지
                    img_el = item.select_one("img.prd_img, .thumb_wrap img")
                    image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

                    # 상세 URL
                    base = SOURCES["ownerclan"]["base_url"]
                    detail_url = f"{base}{href}" if href and not str(href).startswith("http") else str(href)

                    if not name:
                        continue

                    products.append({
                        "product_id": str(product_id),
                        "name": name,
                        "price": price,
                        "retail_price": retail_price if retail_price else price,
                        "category": category,
                        "image_url": image_url,
                        "detail_url": detail_url,
                    })
                except Exception as e:
                    logger.debug(f"[WholesaleCrawler] 오너클랜 상품 파싱 스킵: {e}")
                    continue

        logger.info(f"[WholesaleCrawler] {source} 파싱 결과: {len(products)}건")
        return products
