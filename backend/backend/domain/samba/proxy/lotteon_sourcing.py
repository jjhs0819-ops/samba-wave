"""롯데ON 소싱용 웹 스크래핑 클라이언트 - httpx + pbf API 기반.

주의: proxy/lotteon.py는 판매처(마켓) 등록용 Open API 클라이언트이므로,
소싱(상품 수집)용은 이 파일에서 별도로 관리한다.

롯데ON 사이트 정보:
  - 검색: https://www.lotteon.com/search/search/search.ecn?render=search&platform=pc&q={keyword}
  - 상세: https://www.lotteon.com/p/product/{LO+10자리}
  - 이미지 CDN: contents.lotteon.com
  - JSON-LD(schema.org Product) 마크업 지원 → 우선 파싱
  - __NEXT_DATA__ script 태그에도 상품 데이터 포함 가능
  - 상품번호: LO 접두사 + 10자리 숫자
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from backend.utils.logger import logger


# ── 롯데ON 쿠키 캐시 (확장앱→서버 동기화 후 benefits API에 사용) ──
_lotteon_cookie_cache: str = ""


def set_lotteon_cookie(cookie: str) -> None:
    """확장앱에서 수신한 롯데ON 쿠키를 모듈 캐시에 설정."""
    global _lotteon_cookie_cache
    _lotteon_cookie_cache = cookie


class RateLimitError(Exception):
    """롯데ON 차단 감지 (429/403)."""

    def __init__(self, status: int, retry_after: int = 0):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"HTTP {status} (retry_after={retry_after})")


class LotteonSourcingClient:
    """롯데ON 소싱용 웹 스크래핑 클라이언트 (검색, 상세).

    롯데ON 상품 페이지를 HTML 파싱하여 상품 검색/상세 정보를 추출한다.
    JSON-LD(schema.org Product) 마크업을 우선 파싱하고,
    없으면 __NEXT_DATA__ 또는 메타 태그에서 폴백한다.
    """

    BASE = "https://www.lotteon.com"
    SEARCH_URL = "https://www.lotteon.com/search/search/search.ecn"
    PRODUCT_URL = "https://www.lotteon.com/p/product"
    IMAGE_CDN = "contents.lotteon.com"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.lotteon.com/",
    }

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(20.0, connect=10.0)

    # ------------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------------

    async def search_products(
        self,
        keyword: str,
        page: int = 1,
        size: int = 40,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """롯데ON 상품 검색.

        검색 페이지 HTML을 파싱하여 상품 목록을 추출한다.

        Args:
          keyword: 검색 키워드
          page: 페이지 번호 (1부터)
          size: 페이지당 결과 수
          **filters: 추가 필터

        Returns:
          표준 상품 dict 리스트

        Raises:
          RateLimitError: 429/403 응답 시
        """
        search_url = (
            f"{self.SEARCH_URL}?render=search&platform=pc"
            f"&q={quote(keyword)}&page={page}&size={min(size, 60)}"
        )
        logger.info(f'[LOTTEON] 검색 시작: "{keyword}" (page={page})')

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(search_url, headers=self.HEADERS)

                # 차단 감지
                if resp.status_code in (429, 403):
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning(f"[LOTTEON] 차단 감지 HTTP {resp.status_code}")
                    raise RateLimitError(resp.status_code, retry_after)

                if resp.status_code != 200:
                    logger.warning(f"[LOTTEON] 검색 페이지 HTTP {resp.status_code}")
                    return []

            html = resp.text
            products = self._parse_search_html(html, keyword)
            logger.info(f'[LOTTEON] 검색 완료: "{keyword}" -> {len(products)}개')
            return products

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[LOTTEON] 검색 타임아웃: {keyword}")
            return []
        except Exception as e:
            logger.error(f"[LOTTEON] 검색 실패: {keyword} — {e}")
            return []

    def _parse_search_html(self, html: str, keyword: str) -> list[dict[str, Any]]:
        """검색 결과 HTML에서 상품 정보 추출.

        롯데ON 검색 페이지는 __NEXT_DATA__ 또는 상품 카드 구조로 제공된다.
        """
        products: list[dict[str, Any]] = []
        seen: set[str] = set()
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        # 방법 1: __NEXT_DATA__ JSON에서 추출 시도
        next_data_products = self._parse_search_next_data(html, now_iso)
        if next_data_products:
            return next_data_products

        # 방법 2: JSON-LD에서 검색 결과 추출 시도
        json_ld_products = self._parse_search_json_ld(html, now_iso)
        if json_ld_products:
            return json_ld_products

        # 방법 3: HTML 상품 카드 블록에서 추출 (폴백)
        # 롯데ON 상품 링크 패턴: /p/product/LO + 10자리 숫자
        product_link_pattern = re.compile(
            r"/p/product/(LO\d{10})",
            re.IGNORECASE,
        )

        # 상품 블록 단위 분리
        block_pattern = re.compile(
            r'<li[^>]*class="[^"]*product[^"]*"[^>]*>(.*?)</li>',
            re.DOTALL | re.IGNORECASE,
        )

        blocks = block_pattern.findall(html)
        if not blocks:
            # 블록을 못 찾으면 전체 HTML에서 상품 링크 추출
            blocks = [html]

        for block in blocks:
            id_matches = product_link_pattern.findall(block)
            for product_no in id_matches:
                if product_no in seen:
                    continue
                seen.add(product_no)

                # 상품명 추출
                name = self._extract_text(
                    block, r'class="[^"]*product[_-]?name[^"]*"[^>]*>([^<]+)'
                )
                if not name:
                    name = self._extract_text(
                        block, r'class="[^"]*item[_-]?name[^"]*"[^>]*>([^<]+)'
                    )
                if not name:
                    name = self._extract_text(block, r'title="([^"]+)"')

                # 가격 추출
                sale_price = self._extract_price(
                    block, r'class="[^"]*sale[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)'
                )
                if sale_price == 0:
                    sale_price = self._extract_price(
                        block, r'class="[^"]*price[^"]*"[^>]*>.*?(\d[\d,]+)'
                    )
                original_price = self._extract_price(
                    block, r'class="[^"]*origin[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)'
                )
                if original_price == 0:
                    original_price = sale_price

                # 이미지 추출
                thumbnail = self._extract_text(
                    block, r'<img[^>]+(?:src|data-src)="([^"]+)"'
                )
                thumbnail = self._normalize_image(thumbnail)

                # 품절 여부
                is_sold_out = bool(
                    re.search(r"(?:품절|soldout|sold_out)", block, re.IGNORECASE)
                )

                # 브랜드 추출
                brand = self._extract_text(
                    block, r'class="[^"]*brand[_-]?name[^"]*"[^>]*>([^<]+)'
                )

                if name and sale_price > 0:
                    products.append(
                        {
                            "siteProductId": product_no,
                            "name": name.strip(),
                            "brand": brand.strip() if brand else "",
                            "originalPrice": original_price,
                            "salePrice": sale_price,
                            "thumbnailImageUrl": thumbnail,
                            "isSoldOut": is_sold_out,
                            "sourceSite": "LOTTEON",
                            "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
                            "collectedAt": now_iso,
                        }
                    )

        return products

    def _parse_search_next_data(self, html: str, now_iso: str) -> list[dict[str, Any]]:
        """__NEXT_DATA__ JSON에서 검색 결과 상품 데이터 추출."""
        next_data_match = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not next_data_match:
            return []

        try:
            next_data = json.loads(next_data_match.group(1))
            page_props = next_data.get("props", {}).get("pageProps", {})

            # 검색 결과에서 상품 리스트 탐색
            items: list[dict[str, Any]] = []
            # 가능한 경로 탐색
            for key_path in [
                ("searchResult", "products"),
                ("initialState", "products"),
                ("data", "products"),
                ("products",),
            ]:
                obj = page_props
                for key in key_path:
                    obj = obj.get(key, {}) if isinstance(obj, dict) else {}
                if isinstance(obj, list):
                    items = obj
                    break

            products: list[dict[str, Any]] = []
            for item in items:
                product_no = str(
                    item.get("productNo", "")
                    or item.get("spdNo", "")
                    or item.get("id", "")
                )
                if not product_no:
                    continue

                name = item.get("productName", "") or item.get("spdNm", "") or ""
                sale_price = self._safe_int(
                    item.get("salePrice", 0)
                    or item.get("sellPrc", 0)
                    or item.get("price", 0)
                )
                original_price = (
                    self._safe_int(
                        item.get("originalPrice", 0) or item.get("norPrc", 0)
                    )
                    or sale_price
                )
                thumbnail = self._normalize_image(
                    item.get("imageUrl", "")
                    or item.get("mainImgUrl", "")
                    or item.get("image", "")
                )
                brand = item.get("brandName", "") or item.get("brandNm", "") or ""
                is_sold_out = (
                    item.get("soldOut", False) or item.get("soldOutYn", "N") == "Y"
                )

                if name and sale_price > 0:
                    products.append(
                        {
                            "siteProductId": product_no,
                            "name": name.strip(),
                            "brand": brand.strip(),
                            "originalPrice": original_price,
                            "salePrice": sale_price,
                            "thumbnailImageUrl": thumbnail,
                            "isSoldOut": bool(is_sold_out),
                            "sourceSite": "LOTTEON",
                            "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
                            "collectedAt": now_iso,
                        }
                    )

            return products

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[LOTTEON] __NEXT_DATA__ 검색 파싱 실패: {e}")
            return []

    def _parse_search_json_ld(self, html: str, now_iso: str) -> list[dict[str, Any]]:
        """JSON-LD(schema.org) 마크업에서 검색 결과 추출."""
        products: list[dict[str, Any]] = []

        json_ld_pattern = re.compile(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            re.DOTALL,
        )
        for m in json_ld_pattern.finditer(html):
            try:
                ld_data = json.loads(m.group(1))
                # ItemList 또는 Product 배열 처리
                items: list[dict[str, Any]] = []
                if isinstance(ld_data, list):
                    items = ld_data
                elif isinstance(ld_data, dict):
                    if ld_data.get("@type") == "ItemList":
                        items = ld_data.get("itemListElement", [])
                    elif ld_data.get("@type") == "Product":
                        items = [ld_data]

                for item in items:
                    # ItemList 요소인 경우 item 키에 Product가 있을 수 있음
                    product = item.get("item", item) if isinstance(item, dict) else item
                    if not isinstance(product, dict):
                        continue

                    name = product.get("name", "")
                    if not name:
                        continue

                    # URL에서 상품번호 추출
                    url = product.get("url", "")
                    product_no = ""
                    no_match = re.search(r"(LO\d{10})", url)
                    if no_match:
                        product_no = no_match.group(1)
                    if not product_no:
                        product_no = str(product.get("sku", ""))
                    if not product_no:
                        continue

                    # 가격 추출
                    offers = product.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    sale_price = self._safe_int(offers.get("price", 0))
                    thumbnail = self._normalize_image(
                        product.get("image", [""])[0]
                        if isinstance(product.get("image"), list)
                        else product.get("image", "")
                    )
                    brand_obj = product.get("brand", {})
                    brand = (
                        brand_obj.get("name", "")
                        if isinstance(brand_obj, dict)
                        else str(brand_obj)
                    )

                    if sale_price > 0:
                        products.append(
                            {
                                "siteProductId": product_no,
                                "name": name.strip(),
                                "brand": brand.strip() if brand else "",
                                "originalPrice": sale_price,
                                "salePrice": sale_price,
                                "thumbnailImageUrl": thumbnail,
                                "isSoldOut": False,
                                "sourceSite": "LOTTEON",
                                "sourceUrl": url or f"{self.PRODUCT_URL}/{product_no}",
                                "collectedAt": now_iso,
                            }
                        )

            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return products

    # ------------------------------------------------------------------
    # 상세 조회
    # ------------------------------------------------------------------

    async def get_product_detail(
        self, product_no: str, refresh_only: bool = False
    ) -> dict[str, Any]:
        """롯데ON 상품 상세 정보 조회.

        상품 페이지 HTML에서 JSON-LD(schema.org Product)를 우선 파싱하고,
        없으면 __NEXT_DATA__ 또는 메타 태그에서 폴백한다.

        Args:
          product_no: 롯데ON 상품 번호 (LO + 10자리 숫자)
          refresh_only: True이면 가격/재고만 빠르게 갱신

        Returns:
          표준 상품 상세 dict

        Raises:
          RateLimitError: 429/403 응답 시
        """
        url = f"{self.PRODUCT_URL}/{product_no}"
        logger.info(f"[LOTTEON] 상세 조회: {product_no}")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=self.HEADERS)

                # 차단 감지
                if resp.status_code in (429, 403):
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning(
                        f"[LOTTEON] 차단 감지 HTTP {resp.status_code}: {product_no}"
                    )
                    raise RateLimitError(resp.status_code, retry_after)

                if resp.status_code != 200:
                    logger.warning(
                        f"[LOTTEON] 상세 페이지 HTTP {resp.status_code}: {product_no}"
                    )
                    return {}

            html = resp.text
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

            # 방법 1: JSON-LD(schema.org Product) 우선 파싱
            detail = self._parse_json_ld_detail(html, product_no, now_iso, timestamp)
            if detail:
                # JSON-LD에 없는 정보는 HTML에서 보완
                self._enrich_from_html(detail, html)
                return detail

            # 방법 2: __NEXT_DATA__에서 파싱
            detail = self._parse_next_data_detail(html, product_no, now_iso, timestamp)
            if detail:
                return detail

            # 방법 3: 메타 태그 + HTML 폴백
            return self._parse_meta_detail(html, product_no, now_iso, timestamp)

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[LOTTEON] 상세 조회 타임아웃: {product_no}")
            return {}
        except Exception as e:
            logger.error(f"[LOTTEON] 상세 조회 실패: {product_no} — {e}")
            return {}

    # ------------------------------------------------------------------
    # JSON-LD 파싱 (상세)
    # ------------------------------------------------------------------

    def _parse_json_ld_detail(
        self,
        html: str,
        product_no: str,
        now_iso: str,
        timestamp: int,
    ) -> Optional[dict[str, Any]]:
        """JSON-LD(schema.org Product) 마크업에서 상품 상세 데이터 추출."""
        json_ld_pattern = re.compile(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            re.DOTALL,
        )

        for m in json_ld_pattern.finditer(html):
            try:
                ld_data = json.loads(m.group(1))
                # 배열인 경우 Product 타입 찾기
                if isinstance(ld_data, list):
                    for item in ld_data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            ld_data = item
                            break
                    else:
                        continue

                if not isinstance(ld_data, dict):
                    continue
                if ld_data.get("@type") != "Product":
                    continue

                name = ld_data.get("name", "")
                if not name:
                    continue

                # 가격 정보
                offers = ld_data.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}

                sale_price = self._safe_int(offers.get("price", 0))
                original_price = (
                    self._safe_int(offers.get("highPrice", 0)) or sale_price
                )

                # 재고 상태
                availability = offers.get("availability", "")
                is_out_of_stock = (
                    "OutOfStock" in availability if availability else False
                )

                # 이미지
                raw_images = ld_data.get("image", [])
                if isinstance(raw_images, str):
                    raw_images = [raw_images]
                images = [
                    self._normalize_image(img)
                    for img in raw_images
                    if self._normalize_image(img)
                ][:9]

                # 브랜드
                brand_obj = ld_data.get("brand", {})
                brand = (
                    brand_obj.get("name", "")
                    if isinstance(brand_obj, dict)
                    else str(brand_obj)
                )

                # 카테고리 (JSON-LD에는 보통 없음 → HTML에서 보완)
                category_levels = self._parse_category(html)
                category_str = " > ".join(category_levels) if category_levels else ""

                # 옵션 (JSON-LD에는 보통 없음 → HTML에서 보완)
                options = self._parse_options(html)

                # 상세 이미지
                detail_images = self._parse_detail_images(html)

                # 배송 정보
                free_shipping = bool(
                    re.search(
                        r"(?:무료배송|무료 배송|배송비\s*무료)", html, re.IGNORECASE
                    )
                )
                same_day_delivery = bool(
                    re.search(
                        r"(?:당일배송|새벽배송|바로배송|오늘배송)", html, re.IGNORECASE
                    )
                )

                # 품절 재확인 (HTML 기반)
                if not is_out_of_stock:
                    is_out_of_stock = self._check_sold_out(html, options)

                sale_status = "sold_out" if is_out_of_stock else "in_stock"

                return {
                    "id": f"col_lotteon_{product_no}_{timestamp}",
                    "sourceSite": "LOTTEON",
                    "siteProductId": str(product_no),
                    "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
                    "name": name.strip(),
                    "brand": brand.strip() if brand else "",
                    "category": category_str,
                    "category1": category_levels[0] if len(category_levels) > 0 else "",
                    "category2": category_levels[1] if len(category_levels) > 1 else "",
                    "category3": category_levels[2] if len(category_levels) > 2 else "",
                    "category4": category_levels[3] if len(category_levels) > 3 else "",
                    "images": images[:9],
                    "detailImages": detail_images,
                    "options": options,
                    "originalPrice": original_price,
                    "salePrice": sale_price,
                    "bestBenefitPrice": self._parse_best_benefit_price(html)
                    or sale_price,
                    "saleStatus": sale_status,
                    "isOutOfStock": is_out_of_stock,
                    "freeShipping": free_shipping,
                    "sameDayDelivery": same_day_delivery,
                    "collectedAt": now_iso,
                    "updatedAt": now_iso,
                }

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.debug(f"[LOTTEON] JSON-LD 파싱 스킵: {e}")
                continue

        return None

    # ------------------------------------------------------------------
    # __NEXT_DATA__ 파싱 (상세)
    # ------------------------------------------------------------------

    def _parse_next_data_detail(
        self,
        html: str,
        product_no: str,
        now_iso: str,
        timestamp: int,
    ) -> Optional[dict[str, Any]]:
        """__NEXT_DATA__ JSON에서 상품 상세 데이터 추출."""
        next_data_match = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not next_data_match:
            return None

        try:
            next_data = json.loads(next_data_match.group(1))
            page_props = next_data.get("props", {}).get("pageProps", {})

            # 상품 데이터 경로 탐색
            product: dict[str, Any] = {}
            for key_path in [
                ("product",),
                ("productDetail",),
                ("initialState", "product"),
                ("data", "product"),
            ]:
                obj = page_props
                for key in key_path:
                    obj = obj.get(key, {}) if isinstance(obj, dict) else {}
                if isinstance(obj, dict) and obj:
                    product = obj
                    break

            if not product:
                return None

            name = (
                product.get("productName", "")
                or product.get("spdNm", "")
                or product.get("name", "")
            )
            if not name:
                return None

            # 가격 정보
            sale_price = self._safe_int(
                product.get("salePrice", 0)
                or product.get("sellPrc", 0)
                or product.get("price", 0)
            )
            original_price = (
                self._safe_int(
                    product.get("originalPrice", 0) or product.get("norPrc", 0)
                )
                or sale_price
            )
            best_benefit_price = (
                self._safe_int(
                    product.get("bestBenefitPrice", 0) or product.get("bestPrice", 0)
                )
                or sale_price
            )

            # 브랜드
            brand = product.get("brandName", "") or product.get("brandNm", "") or ""

            # 이미지
            images: list[str] = []
            main_image = product.get("mainImageUrl", "") or product.get(
                "mainImgUrl", ""
            )
            if main_image:
                images.append(self._normalize_image(main_image))
            for img in (
                product.get("addImageUrls", []) or product.get("addImgUrls", []) or []
            ):
                img_url = self._normalize_image(
                    img if isinstance(img, str) else img.get("url", "")
                )
                if img_url and img_url not in images:
                    images.append(img_url)

            # 카테고리
            category_levels: list[str] = []
            for key in [
                "category1Name",
                "category2Name",
                "category3Name",
                "category4Name",
            ]:
                val = product.get(key, "") or product.get(key.replace("Name", "Nm"), "")
                if val:
                    category_levels.append(val)
            if not category_levels:
                category_levels = self._parse_category(html)
            category_str = " > ".join(category_levels) if category_levels else ""

            # 옵션
            options: list[dict[str, Any]] = []
            raw_options = (
                product.get("options", []) or product.get("optionList", []) or []
            )
            for opt in raw_options:
                opt_name = (
                    opt.get("optionName", "")
                    or opt.get("optNm", "")
                    or opt.get("name", "")
                ).strip()
                if not opt_name:
                    continue

                opt_price = self._safe_int(
                    opt.get("price", 0) or opt.get("sellPrc", 0) or opt.get("addPrc", 0)
                )
                opt_stock = self._safe_int(
                    opt.get("stockQty", 0) or opt.get("stock", 0)
                )
                is_sold_out = (
                    opt.get("soldOut", False)
                    or opt.get("soldOutYn", "N") == "Y"
                    or opt_stock == 0
                )
                options.append(
                    {
                        "name": opt_name,
                        "price": opt_price,
                        "stock": opt_stock,
                        "isSoldOut": bool(is_sold_out),
                    }
                )

            # 옵션이 __NEXT_DATA__에 없으면 HTML에서 추출
            if not options:
                options = self._parse_options(html)

            # 상세 이미지
            detail_images = self._parse_detail_images(html)

            # 품절 여부
            is_out_of_stock = (
                product.get("soldOut", False)
                or product.get("soldOutYn", "N") == "Y"
                or self._check_sold_out(html, options)
            )

            # 배송 정보
            free_shipping = bool(
                product.get("freeDelivery", False)
                or product.get("freeShipping", False)
                or re.search(
                    r"(?:무료배송|무료 배송|배송비\s*무료)", html, re.IGNORECASE
                )
            )
            same_day_delivery = bool(
                product.get("sameDayDelivery", False)
                or re.search(
                    r"(?:당일배송|새벽배송|바로배송|오늘배송)", html, re.IGNORECASE
                )
            )

            sale_status = "sold_out" if is_out_of_stock else "in_stock"

            return {
                "id": f"col_lotteon_{product_no}_{timestamp}",
                "sourceSite": "LOTTEON",
                "siteProductId": str(product_no),
                "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
                "name": name.strip(),
                "brand": brand.strip(),
                "category": category_str,
                "category1": category_levels[0] if len(category_levels) > 0 else "",
                "category2": category_levels[1] if len(category_levels) > 1 else "",
                "category3": category_levels[2] if len(category_levels) > 2 else "",
                "category4": category_levels[3] if len(category_levels) > 3 else "",
                "images": images[:9],
                "detailImages": detail_images,
                "options": options,
                "originalPrice": original_price,
                "salePrice": sale_price,
                "bestBenefitPrice": best_benefit_price,
                "saleStatus": sale_status,
                "isOutOfStock": bool(is_out_of_stock),
                "freeShipping": free_shipping,
                "sameDayDelivery": same_day_delivery,
                "collectedAt": now_iso,
                "updatedAt": now_iso,
            }

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[LOTTEON] __NEXT_DATA__ 상세 파싱 실패: {e}")
            return None

    # ------------------------------------------------------------------
    # 메타 태그 폴백 (상세)
    # ------------------------------------------------------------------

    def _parse_meta_detail(
        self,
        html: str,
        product_no: str,
        now_iso: str,
        timestamp: int,
    ) -> dict[str, Any]:
        """메타 태그 + HTML에서 상품 상세 정보 추출 (최종 폴백)."""
        name = self._extract_meta(html, "og:title") or ""
        thumbnail = self._normalize_image(self._extract_meta(html, "og:image") or "")

        # 가격 추출
        sale_price = self._parse_sale_price(html)
        original_price = self._parse_original_price(html)
        if original_price == 0:
            original_price = sale_price
        best_benefit_price = self._parse_best_benefit_price(html) or sale_price

        # 브랜드
        brand = self._parse_brand(html)

        # 카테고리
        category_levels = self._parse_category(html)
        category_str = " > ".join(category_levels) if category_levels else ""

        # 이미지
        images = self._parse_product_images(html, thumbnail)

        # 상세 이미지
        detail_images = self._parse_detail_images(html)

        # 옵션
        options = self._parse_options(html)

        # 품절 여부
        is_out_of_stock = self._check_sold_out(html, options)

        # 배송 정보
        free_shipping = bool(
            re.search(r"(?:무료배송|무료 배송|배송비\s*무료)", html, re.IGNORECASE)
        )
        same_day_delivery = bool(
            re.search(r"(?:당일배송|새벽배송|바로배송|오늘배송)", html, re.IGNORECASE)
        )

        sale_status = "sold_out" if is_out_of_stock else "in_stock"

        return {
            "id": f"col_lotteon_{product_no}_{timestamp}",
            "sourceSite": "LOTTEON",
            "siteProductId": str(product_no),
            "sourceUrl": f"{self.PRODUCT_URL}/{product_no}",
            "name": name.strip(),
            "brand": brand,
            "category": category_str,
            "category1": category_levels[0] if len(category_levels) > 0 else "",
            "category2": category_levels[1] if len(category_levels) > 1 else "",
            "category3": category_levels[2] if len(category_levels) > 2 else "",
            "category4": category_levels[3] if len(category_levels) > 3 else "",
            "images": images[:9],
            "detailImages": detail_images,
            "options": options,
            "originalPrice": original_price,
            "salePrice": sale_price,
            "bestBenefitPrice": best_benefit_price,
            "saleStatus": sale_status,
            "isOutOfStock": is_out_of_stock,
            "freeShipping": free_shipping,
            "sameDayDelivery": same_day_delivery,
            "collectedAt": now_iso,
            "updatedAt": now_iso,
        }

    # ------------------------------------------------------------------
    # HTML 보완 (JSON-LD 결과에 누락된 정보 채우기)
    # ------------------------------------------------------------------

    def _enrich_from_html(self, detail: dict[str, Any], html: str) -> None:
        """JSON-LD 파싱 결과에 누락된 정보를 HTML에서 보완."""
        # 최대혜택가가 판매가와 동일하면 HTML에서 재탐색
        if detail.get("bestBenefitPrice", 0) == detail.get("salePrice", 0):
            benefit = self._parse_best_benefit_price(html)
            if benefit and benefit < detail["salePrice"]:
                detail["bestBenefitPrice"] = benefit

        # 이미지가 부족하면 HTML에서 추가 수집
        if len(detail.get("images", [])) < 3:
            thumbnail = detail["images"][0] if detail.get("images") else ""
            html_images = self._parse_product_images(html, thumbnail)
            for img in html_images:
                if img not in detail["images"]:
                    detail["images"].append(img)
                    if len(detail["images"]) >= 9:
                        break

    # ------------------------------------------------------------------
    # 가격 파싱 헬퍼
    # ------------------------------------------------------------------

    def _parse_sale_price(self, html: str) -> int:
        """판매가 추출.

        메타 태그 → HTML 가격 영역 순서로 탐색.
        """
        # 메타 태그 우선
        price_meta = self._extract_meta(html, "product:price:amount")
        if price_meta:
            price = self._safe_int(re.sub(r"[^\d]", "", price_meta))
            if price > 0:
                return price

        # 롯데ON 판매가 영역
        for pattern in [
            r'class="[^"]*sale[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*sell[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*final[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*product[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    def _parse_original_price(self, html: str) -> int:
        """정상가(원래 가격) 추출."""
        for pattern in [
            r'class="[^"]*origin[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*original[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*old[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*normal[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    def _parse_best_benefit_price(self, html: str) -> int:
        """최대혜택가 추출 (쿠폰+적립금 포함)."""
        for pattern in [
            r'class="[^"]*best[_-]?benefit[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*coupon[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r"(?:최대혜택가|쿠폰적용가|최저가)[^<]*?(\d[\d,]+)",
            r'class="[^"]*benefit[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    # ------------------------------------------------------------------
    # 정보 파싱 헬퍼
    # ------------------------------------------------------------------

    def _parse_brand(self, html: str) -> str:
        """브랜드명 추출."""
        for pattern in [
            r'class="[^"]*brand[_-]?name[^"]*"[^>]*>([^<]+)',
            r'class="[^"]*brand[_-]?area[^"]*"[^>]*>\s*<a[^>]*>([^<]+)',
            r'class="[^"]*product[_-]?brand[^"]*"[^>]*>([^<]+)',
        ]:
            brand = self._extract_text(html, pattern)
            if brand:
                return brand.strip()

        return ""

    def _parse_category(self, html: str) -> list[str]:
        """카테고리 경로 추출 (깊이별 리스트).

        롯데ON 상품 페이지의 브레드크럼 또는 카테고리 네비게이션에서 추출.
        """
        categories: list[str] = []

        # 브레드크럼 영역에서 추출
        breadcrumb_pattern = re.compile(
            r'class="[^"]*breadcrumb[^"]*"[^>]*>(.*?)</(?:ul|ol|div|nav)',
            re.DOTALL | re.IGNORECASE,
        )
        breadcrumb = breadcrumb_pattern.search(html)
        if breadcrumb:
            link_texts = re.findall(
                r"<a[^>]*>([^<]+)</a>",
                breadcrumb.group(1),
            )
            for text in link_texts:
                text = text.strip()
                if text and text not in ("홈", "HOME", "롯데ON", "전체"):
                    categories.append(text)

        # 브레드크럼이 없으면 카테고리 메타 태그
        if not categories:
            cat_meta = self._extract_meta(html, "product:category")
            if cat_meta:
                categories = [c.strip() for c in cat_meta.split(">") if c.strip()]

        # 카테고리 네비게이션 영역에서 추출
        if not categories:
            cat_pattern = re.compile(
                r'class="[^"]*cate[_-]?path[^"]*"[^>]*>(.*?)</(?:div|ul)',
                re.DOTALL | re.IGNORECASE,
            )
            cat_match = cat_pattern.search(html)
            if cat_match:
                cat_texts = re.findall(r">([^<]+)<", cat_match.group(1))
                categories = [
                    t.strip()
                    for t in cat_texts
                    if t.strip() and t.strip() not in ("홈", ">", "/", "롯데ON")
                ]

        return categories[:4]

    def _parse_product_images(self, html: str, thumbnail: str) -> list[str]:
        """상품 이미지 목록 추출 (대표 이미지 포함, 최대 9장)."""
        images: list[str] = []
        if thumbnail:
            images.append(thumbnail)

        # 롯데ON 이미지 갤러리 영역
        gallery_pattern = re.compile(
            r'class="[^"]*(?:product[_-]?gallery|thumb[_-]?list|image[_-]?slide)[^"]*"[^>]*>(.*?)</(?:div|ul)',
            re.DOTALL | re.IGNORECASE,
        )
        gallery = gallery_pattern.search(html)
        target = gallery.group(1) if gallery else html

        # contents.lotteon.com CDN 이미지 패턴
        img_pattern = re.compile(
            r'(?:src|data-src|data-lazy)=["\']([^"\']*(?:contents\.lotteon\.com|lotteon\.com/p/img)[^"\']+)["\']',
            re.IGNORECASE,
        )
        for m in img_pattern.finditer(target):
            img_url = self._normalize_image(m.group(1))
            if img_url and img_url not in images:
                images.append(img_url)
                if len(images) >= 9:
                    break

        # CDN 이미지 부족 시 일반 이미지도 수집
        if len(images) < 3:
            general_img_pattern = re.compile(
                r'class="[^"]*product[_-]?img[^"]*"[^>]*>.*?<img[^>]+src="([^"]+)"',
                re.DOTALL | re.IGNORECASE,
            )
            for m in general_img_pattern.finditer(html):
                img_url = self._normalize_image(m.group(1))
                if img_url and img_url not in images:
                    images.append(img_url)
                    if len(images) >= 9:
                        break

        return images[:9]

    def _parse_detail_images(self, html: str) -> list[str]:
        """상세 설명 영역에서 이미지 URL 추출."""
        images: list[str] = []

        # 롯데ON 상세 설명 영역
        detail_area = re.search(
            r'(?:id="[^"]*detail[_-]?cont[^"]*"|class="[^"]*detail[_-]?content[^"]*"|class="[^"]*product[_-]?detail[^"]*")[^>]*>(.*)',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if detail_area:
            img_pattern = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
            for m in img_pattern.finditer(detail_area.group(1)):
                img_url = self._normalize_image(m.group(1))
                if img_url and img_url not in images:
                    images.append(img_url)

        return images

    def _parse_options(self, html: str) -> list[dict[str, Any]]:
        """옵션 정보 추출.

        롯데ON 옵션은 JSON 데이터 또는 셀렉트박스로 제공된다.
        """
        options: list[dict[str, Any]] = []

        # 방법 1: 옵션 JSON 데이터에서 추출
        option_json_pattern = re.compile(
            r"(?:optionData|optionList|itemOptList)\s*[=:]\s*(\[.*?\]);",
            re.DOTALL,
        )
        json_match = option_json_pattern.search(html)
        if json_match:
            try:
                option_list = json.loads(json_match.group(1))
                for opt in option_list:
                    opt_name = (
                        opt.get("optNm", "")
                        or opt.get("optionName", "")
                        or opt.get("name", "")
                    ).strip()
                    if not opt_name:
                        continue

                    opt_price = self._safe_int(
                        opt.get("sellPrc", 0)
                        or opt.get("addPrc", 0)
                        or opt.get("price", 0)
                    )
                    opt_stock = self._safe_int(
                        opt.get("stockQty", 0) or opt.get("stock", 0)
                    )
                    is_sold_out = (
                        opt.get("soldOutYn", "N") == "Y"
                        or opt.get("soldOut", False)
                        or opt.get("isSoldOut", False)
                        or opt_stock == 0
                    )

                    options.append(
                        {
                            "name": opt_name,
                            "price": opt_price,
                            "stock": opt_stock,
                            "isSoldOut": bool(is_sold_out),
                        }
                    )
                return options
            except (json.JSONDecodeError, TypeError):
                pass

        # 방법 2: 셀렉트박스에서 옵션 추출
        option_area = re.search(
            r'class="[^"]*option[_-]?select[^"]*"[^>]*>(.*?)</select>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if option_area:
            option_pattern = re.compile(
                r'<option[^>]+value="([^"]*)"[^>]*>([^<]+)</option>',
                re.IGNORECASE,
            )
            matches = option_pattern.findall(option_area.group(1))
            for value, text in matches:
                text = text.strip()
                # 플레이스홀더 제외
                if not value or "선택" in text:
                    continue

                # 품절 여부
                is_sold_out = "품절" in text

                # 가격 정보 추출 (옵션명에 포함된 경우)
                price_in_option = 0
                price_match = re.search(r"\(([+-]?\d[\d,]*)\)", text)
                if price_match:
                    price_in_option = self._safe_int(
                        re.sub(r"[^\d\-]", "", price_match.group(1))
                    )

                options.append(
                    {
                        "name": text,
                        "price": price_in_option,
                        "stock": 0 if is_sold_out else 1,
                        "isSoldOut": is_sold_out,
                    }
                )

        return options

    def _check_sold_out(self, html: str, options: list[dict[str, Any]]) -> bool:
        """품절 여부 판단.

        1. HTML에 품절 표시가 있는 경우
        2. 모든 옵션이 품절인 경우
        """
        # HTML 내 품절 마커
        if re.search(
            r'class="[^"]*sold[_-]?out[^"]*"',
            html,
            re.IGNORECASE,
        ):
            return True

        # 명시적 품절 텍스트 (구매 버튼 영역)
        button_area = re.search(
            r'class="[^"]*(?:buy[_-]?btn|purchase[_-]?btn|cart[_-]?btn)[^"]*"[^>]*>(.*?)</div>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if button_area and re.search(
            r"(?:품절|일시품절|SOLD\s*OUT)",
            button_area.group(1),
            re.IGNORECASE,
        ):
            return True

        # 옵션이 있고 모두 품절인 경우
        if options and all(opt.get("isSoldOut", False) for opt in options):
            return True

        return False

    # ------------------------------------------------------------------
    # 공통 헬퍼
    # ------------------------------------------------------------------

    def _normalize_image(self, url: str) -> str:
        """이미지 URL 정규화 (프로토콜 보정)."""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return f"https:{url}"
        if not url.startswith("http"):
            return ""
        return url

    @staticmethod
    def _extract_meta(html: str, prop: str) -> Optional[str]:
        """og/product 메타 태그에서 content 추출."""
        pattern = (
            rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"'
        )
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1)
        # content가 먼저 오는 경우
        pattern2 = (
            rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"'
        )
        m2 = re.search(pattern2, html, re.IGNORECASE)
        return m2.group(1) if m2 else None

    @staticmethod
    def _extract_text(html: str, pattern: str) -> str:
        """정규식으로 텍스트 추출."""
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_price(html: str, pattern: str) -> int:
        """정규식으로 가격(숫자) 추출."""
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(1))
            return int(digits) if digits else 0
        return 0

    @staticmethod
    def _safe_int(value: Any) -> int:
        """안전한 정수 변환."""
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            digits = re.sub(r"[^\d]", "", value)
            return int(digits) if digits else 0
        return 0

    # ── pbf API 클라이언트 (커넥션 풀 재사용) ─────────────────────

    PBF_BASE = "https://pbf.lotteon.com"

    _pbf_shared_client: Optional[httpx.AsyncClient] = None

    async def _get_pbf_client(self) -> httpx.AsyncClient:
        """pbf refresh용 공유 클라이언트 (커넥션 풀 재사용으로 TCP 핸드셰이크 절감)."""
        if self._pbf_shared_client is None or self._pbf_shared_client.is_closed:
            LotteonSourcingClient._pbf_shared_client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._pbf_shared_client

    async def fetch_pbf_standalone(self, sitm_no: str) -> Optional[dict[str, Any]]:
        """pbf.lotteon.com API — 공유 클라이언트로 커넥션 풀 재사용."""
        client = await self._get_pbf_client()
        return await self._fetch_pbf_detail(sitm_no, client)

    async def fetch_qapi_price(self, spd_no: str) -> Optional[dict[str, Any]]:
        """qapi 검색으로 프로모션 최종가 조회 — productId 매칭.

        Returns:
          {"original": 81750, "final": 65400} 또는 None
        """
        try:
            url = (
                f"{self.BASE}/csearch/search/search?render=qapi&platform=pc"
                f"&collection_id=201&q={spd_no}&mallId=2&u2=0&u3=5"
            )
            qapi_headers = {**self.HEADERS, "Accept": "application/json, */*"}
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=qapi_headers)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                items = data.get("itemList", [])
                for item in items:
                    pid = item.get("productId", "")
                    if pid == spd_no:
                        price_map: dict[str, int] = {}
                        for p in item.get("priceInfo", []):
                            price_map[p.get("type", "")] = p.get("num", 0)
                        return {
                            "original": price_map.get("original", 0),
                            "final": price_map.get("final", 0),
                        }
        except Exception as e:
            logger.debug(f"[LOTTEON] qapi 가격 조회 실패: {spd_no} — {e}")
        return None

    async def fetch_option_stock(
        self,
        pbf_data: dict[str, Any],
        spd_no: str = "",
        sitm_no: str = "",
    ) -> Optional[list[dict[str, Any]]]:
        """option/mapping API로 옵션별 실재고 조회.

        Returns:
          [{"name": "250", "stock": 6, "isSoldOut": False}, ...] 또는 None
        """
        basic = pbf_data.get("basicInfo") or {}
        spd_no = spd_no or str(basic.get("spdNo", "") or "").strip()
        sitm_no = sitm_no or str(basic.get("sitmNo", "") or "").strip()
        tr_no = str(basic.get("trNo", "") or "").strip()
        tr_grp_cd = str(basic.get("trGrpCd", "") or "").strip()
        lrtr_no = str(basic.get("lrtrNo", "") or "").strip()
        pd_no = str(basic.get("pdNo", "") or spd_no).strip()
        if not spd_no or not sitm_no:
            return None

        url = (
            f"{self.PBF_BASE}/product/v2/detail/option/mapping"
            f"/{spd_no}/{sitm_no}"
            f"?trNo={tr_no}&trGrpCd={tr_grp_cd}"
            f"&lrtrNo={lrtr_no}&pdNo={pd_no}"
        )
        try:
            client = await self._get_pbf_client()
            resp = await client.get(
                url,
                headers={
                    **self.HEADERS,
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://www.lotteon.com",
                },
            )
            if resp.status_code != 200:
                return None
            body = resp.json()
            if str(body.get("returnCode")) != "200":
                return None

            data = body.get("data") or {}
            opt_info = data.get("optionInfo") or {}
            opt_list = opt_info.get("optionList") or []
            mapping = opt_info.get("optionMappingInfo") or {}
            if not opt_list or not mapping:
                return None

            options: list[dict[str, Any]] = []
            price_info = pbf_data.get("priceInfo") or {}
            sl_prc = self._safe_int(price_info.get("slPrc", 0))

            for group in opt_list:
                for opt in group.get("options", []):
                    label = opt.get("label", "").strip()
                    value = str(opt.get("value", ""))
                    disabled = bool(opt.get("disabled", False))
                    m = mapping.get(value, {})
                    stk_qty = int(m.get("stkQty", 0) or 0)
                    is_sold_out = disabled or stk_qty == 0
                    options.append(
                        {
                            "name": label,
                            "price": sl_prc,
                            "stock": 0 if is_sold_out else stk_qty,
                            "isSoldOut": is_sold_out,
                        }
                    )

            if options:
                logger.info(
                    f"[LOTTEON] option/mapping 재고: {spd_no} → "
                    f"{len(options)}개 옵션 "
                    f"(재고: {[o['stock'] for o in options]})"
                )
            return options if options else None
        except Exception as e:
            logger.debug(f"[LOTTEON] option/mapping 실패: {spd_no} — {e}")
        return None

    async def fetch_benefit_price(
        self,
        pbf_data: dict[str, Any],
        spd_no: str = "",
        sitm_no: str = "",
    ) -> Optional[int]:
        """favorBox/benefits API로 최대혜택가(totAmt) 조회.

        Returns:
          최대혜택가(int) 또는 None (실패 시)
        """
        basic = pbf_data.get("basicInfo") or {}
        price = pbf_data.get("priceInfo") or {}
        spd_no = spd_no or str(basic.get("spdNo", "") or "").strip()
        sitm_no = sitm_no or str(basic.get("sitmNo", "") or "").strip()
        sl_prc = self._safe_int(price.get("slPrc", 0))
        if not spd_no or not sitm_no or sl_prc <= 0:
            logger.info(
                f"[LOTTEON] benefits API 스킵: spd={spd_no}, sitm={sitm_no}, slPrc={sl_prc}"
            )
            return None

        body = {
            "spdNo": spd_no,
            "sitmNo": sitm_no,
            "slPrc": sl_prc,
            "slQty": 1,
            "trGrpCd": str(basic.get("trGrpCd", "") or "SR"),
            "trNo": str(basic.get("trNo", "") or ""),
            "lrtrNo": str(basic.get("lrtrNo", "") or ""),
            "brdNo": str(basic.get("brdNo", "") or ""),
            "scatNo": str(basic.get("scatNo", "") or ""),
            "strCd": str(basic.get("strCd", "") or ""),
            # 채널 정보 — 롯데ON 파트너 채널 고정값 (pbf basicInfo에 미포함)
            "chCsfCd": str(basic.get("chCsfCd", "") or "PA"),
            "chDtlNo": str(basic.get("chDtlNo", "") or "1025188"),
            "chNo": str(basic.get("chNo", "") or "100994"),
            "chTypCd": str(basic.get("chTypCd", "") or "PA07"),
            "ctrtTypCd": str(basic.get("ctrtTypCd", "") or "A"),
            "afflPdMrgnRt": basic.get("afflPdMrgnRt"),
            "afflPdLwstMrgnRt": basic.get("afflPdLwstMrgnRt"),
            "sfcoPdMrgnRt": self._safe_int(basic.get("sfcoPdMrgnRt", 0)),
            "sfcoPdLwstMrgnRt": self._safe_int(basic.get("sfcoPdLwstMrgnRt", 0)),
            "pcsLwstMrgnRt": self._safe_int(basic.get("pcsLwstMrgnRt", 0)),
            "dmstOvsDvDvsCd": str(basic.get("dmstOvsDvDvsCd", "") or "DMST"),
            "dvPdTypCd": str(basic.get("dvPdTypCd", "") or "GNRL"),
            "dvCst": self._safe_int(basic.get("dvCst", 0)),
            "dvCstStdQty": self._safe_int(basic.get("dvCstStdQty", 0)),
            "stkMgtYn": str(basic.get("stkMgtYn", "") or "Y"),
            "thdyPdYn": str(basic.get("thdyPdYn", "") or "N"),
            "fprdDvPdYn": str(basic.get("fprdDvPdYn", "") or "N"),
            "mallNo": str(basic.get("mallNo", "") or "1"),
            "cartDvsCd": "01",
            "infwMdiaCd": "PC",
            "screenType": "PRODUCT",
            "maxPurQty": self._safe_int(basic.get("maxPurQty", 0)) or 999999,
            "aplyBestPrcChk": "Y",
            "aplyStdDttm": datetime.now().strftime("%Y%m%d%H%M%S"),
            "pyMnsExcpLst": [],
            "discountApplyProductList": [],
        }

        url = f"{self.PBF_BASE}/product/v2/extlmsa/promotion/favorBox/benefits"
        _cookie_len = (
            len(_lotteon_cookie_cache.split(";")) if _lotteon_cookie_cache else 0
        )
        logger.info(
            f"[LOTTEON] benefits API 호출: {spd_no}, "
            f"쿠키={'있음(' + str(_cookie_len) + '개)' if _lotteon_cookie_cache else '없음'}, "
            f"slPrc={sl_prc:,}"
        )
        try:
            client = await self._get_pbf_client()
            _benefit_headers = {
                **self.HEADERS,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://www.lotteon.com",
            }
            if _lotteon_cookie_cache:
                _benefit_headers["Cookie"] = _lotteon_cookie_cache
            resp = await client.post(
                url,
                json=body,
                headers=_benefit_headers,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"[LOTTEON] benefits API HTTP {resp.status_code}: {resp.text[:200]}"
                )
                return None
            result = resp.json()
            if str(result.get("returnCode")) != "200":
                logger.warning(
                    f"[LOTTEON] benefits API 실패: {result.get('message', '')[:100]}"
                )
                return None
            data = result.get("data") or {}
            tot_amt = data.get("totAmt")
            if tot_amt is not None and float(tot_amt) > 0:
                benefit = int(float(tot_amt))
                logger.info(
                    f"[LOTTEON] benefits API 혜택가: {spd_no} → {benefit:,}"
                    f" (정가={sl_prc:,}, 할인={int(float(data.get('totDcAmt', 0))):,})"
                )
                return benefit
        except Exception as e:
            logger.debug(f"[LOTTEON] benefits API 실패: {spd_no} — {e}")
        return None

    async def _fetch_pbf_detail(
        self, sitm_no: str, client: httpx.AsyncClient
    ) -> Optional[dict[str, Any]]:
        """pbf.lotteon.com API로 옵션/재고/이미지 데이터 조회."""
        url = f"{self.PBF_BASE}/product/v2/detail/search/base/sitm/{sitm_no}"
        pbf_headers = {
            **self.HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.lotteon.com",
        }
        try:
            resp = await client.get(url, headers=pbf_headers)
            if resp.status_code != 200:
                return None
            body = resp.json()
            if body.get("returnCode") != "200" and body.get("returnCode") != 200:
                return None
            return body.get("data")
        except Exception as e:
            logger.debug(f"[LOTTEON] pbf API 실패: {sitm_no} — {e}")
            return None

    async def _fetch_pbf_pd_detail(
        self, pd_no: str, client: httpx.AsyncClient
    ) -> Optional[dict[str, Any]]:
        """pbf /base/pd/ API — artlInfo(고시정보), dispCategoryInfo 포함."""
        url = (
            f"{self.PBF_BASE}/product/v2/detail/search/base/pd"
            f"/{pd_no}?isNotContainOptMapping=true"
        )
        pbf_headers = {
            **self.HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.lotteon.com",
        }
        try:
            resp = await client.get(url, headers=pbf_headers)
            if resp.status_code != 200:
                return None
            body = resp.json()
            if body.get("returnCode") != "200" and body.get("returnCode") != 200:
                return None
            return body.get("data")
        except Exception as e:
            logger.debug(f"[LOTTEON] pbf pd API 실패: {pd_no} — {e}")
            return None
