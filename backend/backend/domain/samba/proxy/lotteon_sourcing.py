"""롯데ON 소싱용 웹 스크래핑 클라이언트 - httpx 기반.

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


# 롯데ON BC 카테고리 코드 → 카테고리명 하드코딩 딕셔너리 (팀장 매핑 보조용)
_LOTTEON_SCAT_NAMES: dict[str, str] = {
    # 패션의류
    "BC11010100": "패션의류 > 남성의류 > 티셔츠",
    "BC11010200": "패션의류 > 남성의류 > 셔츠/남방",
    "BC11010300": "패션의류 > 남성의류 > 바지",
    "BC11010400": "패션의류 > 남성의류 > 청바지",
    "BC11010500": "패션의류 > 남성의류 > 아우터",
    "BC11010600": "패션의류 > 남성의류 > 점퍼",
    "BC11010700": "패션의류 > 남성의류 > 패딩",
    "BC11010800": "패션의류 > 남성의류 > 니트/스웨터",
    "BC11010900": "패션의류 > 남성의류 > 후드티셔츠",
    "BC11011000": "패션의류 > 남성의류 > 맨투맨",
    "BC11011100": "패션의류 > 남성의류 > 트레이닝복",
    "BC11020100": "패션의류 > 여성의류 > 티셔츠",
    "BC11020200": "패션의류 > 여성의류 > 블라우스",
    "BC11020300": "패션의류 > 여성의류 > 원피스",
    "BC11020400": "패션의류 > 여성의류 > 스커트",
    "BC11020500": "패션의류 > 여성의류 > 바지",
    "BC11020600": "패션의류 > 여성의류 > 아우터",
    # 패션잡화
    "BC12010100": "패션잡화 > 남성신발 > 스니커즈",
    "BC12010200": "패션잡화 > 남성신발 > 구두",
    "BC12010300": "패션잡화 > 남성신발 > 샌들/슬리퍼",
    "BC12010400": "패션잡화 > 남성신발 > 부츠",
    "BC12010500": "패션잡화 > 남성신발 > 운동화",
    "BC12020100": "패션잡화 > 여성신발 > 스니커즈",
    "BC12020200": "패션잡화 > 여성신발 > 구두/힐",
    "BC12030100": "패션잡화 > 가방 > 백팩",
    "BC12030200": "패션잡화 > 가방 > 숄더백",
    "BC12030300": "패션잡화 > 가방 > 크로스백",
    "BC12030400": "패션잡화 > 가방 > 토트백",
    "BC12040100": "패션잡화 > 모자 > 캡모자",
    "BC12040200": "패션잡화 > 모자 > 비니",
    # 스포츠
    "BC41030100": "스포츠/레저 > 스포츠신발 > 런닝화",
    "BC41030200": "스포츠/레저 > 스포츠신발 > 운동화",
    "BC41010100": "스포츠/레저 > 스포츠의류 > 상의",
    "BC41010200": "스포츠/레저 > 스포츠의류 > 하의",
    "BC13140700": "스포츠/레저 > 스포츠신발 > 런닝화",
    # 스포츠신발 — 남성 (롯데ON 실제 브레드크럼 확인)
    "BC41030400": "스포츠/레저 > 신발 > 남성스포츠신발 > 운동화",
    "BC41030800": "스포츠/레저 > 신발 > 남성스포츠신발 > 스니커즈",
    # 스포츠신발 — 여성 (롯데ON 실제 브레드크럼 확인)
    "BC41090500": "스포츠/레저 > 신발 > 여성스포츠신발 > 스니커즈",
    "BC41090900": "스포츠/레저 > 신발 > 여성스포츠신발 > 운동화",
}


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
    SEARCH_URL = "https://www.lotteon.com/csearch/search/search"
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
        display_category_id: str = "",
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
        # URL이 keyword로 전달된 경우 q= 파라미터 추출 (collect_by_filter 호환)
        if keyword.startswith("http") and "lotteon.com" in keyword:
            from urllib.parse import urlparse as _up, parse_qs as _pq

            _qs = _pq(_up(keyword).query)
            keyword = _qs.get("q", [keyword])[0]

        search_url = (
            f"{self.SEARCH_URL}?render=search&platform=pc"
            f"&q={quote(keyword)}&page={page}&size={min(size, 60)}&mallId=2"
        )
        # 카테고리 필터 (displayCategoryId)
        if display_category_id:
            search_url += f"&dpCtgrNo={quote(display_category_id)}"
        logger.info(
            f'[LOTTEON] 검색 시작: "{keyword}" (page={page}, cat={display_category_id or "전체"})'
        )

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

        롯데ON 검색 페이지는 econJs.SearchApp.create() JS 객체 안에 상품 데이터가 있다.
        """
        products: list[dict[str, Any]] = []
        seen: set[str] = set()
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        # 방법 0: econJs.SearchApp.create() JS 객체에서 추출 (롯데ON 실제 구조)
        econjs_products = self._parse_search_econjs(html, now_iso)
        if econjs_products:
            return econjs_products

        # 방법 1: __NEXT_DATA__ JSON에서 추출 시도
        next_data_products = self._parse_search_next_data(html, now_iso)
        if next_data_products:
            return next_data_products

        # 방법 2: JSON-LD에서 검색 결과 추출 시도
        json_ld_products = self._parse_search_json_ld(html, now_iso)
        if json_ld_products:
            return json_ld_products

        # 방법 3: HTML 상품 카드 블록에서 추출 (폴백)
        # 롯데ON 상품 링크 패턴: /p/product/{prefix}{숫자} (PD/LI/LO/LE 모두 허용)
        product_link_pattern = re.compile(
            r"/p/product/([A-Z]{2}\d{8,12})",
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

    def _parse_search_econjs(self, html: str, now_iso: str) -> list[dict[str, Any]]:
        """econJs.SearchApp.create() JS 객체에서 검색 결과 상품 데이터 추출.

        롯데ON 검색 페이지의 실제 상품 데이터는 아래 형태의 JS 코드 안에 있다:
          econJs.SearchApp.create('.srchResultWrap', { ... products: [...] ... })
        값 사이에 줄바꿈이 포함되어 있으므로 re.DOTALL 으로 처리한다.
        """
        products: list[dict[str, Any]] = []
        seen: set[str] = set()

        # econJs.SearchApp.create 호출 전체 추출
        # 두 번째 인자(객체 리터럴) 시작 중괄호부터 끝까지 추출
        econjs_match = re.search(
            r"econJs\.SearchApp\.create\s*\([^,]+,\s*(\{)",
            html,
            re.DOTALL,
        )
        if not econjs_match:
            return []

        # 중괄호 깊이 추적으로 전체 JSON 객체 추출
        start_pos = econjs_match.start(1)
        depth = 0
        end_pos = start_pos
        for i in range(start_pos, len(html)):
            ch = html[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        raw_obj = html[start_pos:end_pos]
        if not raw_obj:
            return []

        # JS 객체를 JSON 파싱 가능하게 전처리
        # 1) 줄바꿈/탭 → 공백
        raw_obj = re.sub(r"[\r\n\t]+", " ", raw_obj)
        # 2) 후행 콤마 제거 (JSON 비표준)
        raw_obj = re.sub(r",\s*([}\]])", r"\1", raw_obj)
        # 3) 따옴표 없는 키 → 따옴표 있는 키로 변환 (단순 식별자만)
        raw_obj = re.sub(r"(?<=[{,\s])([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'"\1":', raw_obj)

        try:
            obj = json.loads(raw_obj)
        except (json.JSONDecodeError, ValueError):
            # JSON 파싱 실패 시 상품 ID + 기본 필드만 정규식으로 추출
            logger.debug("[LOTTEON] econJs JSON 파싱 실패 → 정규식 폴백")
            return self._parse_search_econjs_regex(html, now_iso)

        # 상품 리스트 탐색 (가능한 키 목록)
        items: list[Any] = []
        for key in ("products", "productList", "itemList", "items", "list"):
            val = obj.get(key)
            if isinstance(val, list):
                items = val
                break
        # 중첩 구조 탐색 (data.products 등)
        if not items:
            for sub_key in ("data", "result", "searchResult"):
                sub = obj.get(sub_key)
                if isinstance(sub, dict):
                    for key in ("products", "productList", "itemList", "items", "list"):
                        val = sub.get(key)
                        if isinstance(val, list):
                            items = val
                            break
                if items:
                    break

        if not items:
            logger.debug("[LOTTEON] econJs 객체에서 상품 리스트 키 없음")
            return self._parse_search_econjs_regex(html, now_iso)

        for item in items:
            if not isinstance(item, dict):
                continue

            # sitmNo는 별도로 보존 (LE1220156946_1321122096 형태)
            sitm_no = str(item.get("sitmNo", "") or "").strip()

            spd_no = str(
                item.get("spdNo", "")
                or item.get("sitmNo", "")
                or item.get("productNo", "")
                or ""
            ).strip()
            if not spd_no or spd_no in seen:
                continue
            seen.add(spd_no)

            name = str(
                item.get("spdNm", "")
                or item.get("productName", "")
                or item.get("name", "")
                or ""
            ).strip()
            if not name:
                continue

            # 할인가(discountPrice) 우선, 없으면 price
            sale_price = self._safe_int(
                item.get("discountPrice", 0)
                or item.get("sellPrc", 0)
                or item.get("price", 0)
            )
            original_price = (
                self._safe_int(item.get("price", 0) or item.get("norPrc", 0))
                or sale_price
            )

            thumbnail = self._normalize_image(
                str(
                    item.get("image", "")
                    or item.get("imageUrl", "")
                    or item.get("mainImgUrl", "")
                    or ""
                )
            )

            # 품절 여부
            is_sold_out = bool(
                item.get("soldOut", False)
                or item.get("soldOutYn", "N") == "Y"
                or re.search(r"soldout|sold_out|품절", str(item), re.IGNORECASE)
            )

            brand = str(
                item.get("brandNm", "") or item.get("brandName", "") or ""
            ).strip()

            products.append(
                {
                    "siteProductId": spd_no,
                    "sitmNo": sitm_no,
                    "name": name,
                    "brand": brand,
                    "originalPrice": original_price,
                    "salePrice": sale_price if sale_price > 0 else original_price,
                    "thumbnailImageUrl": thumbnail,
                    "isSoldOut": is_sold_out,
                    "sourceSite": "LOTTEON",
                    "sourceUrl": f"{self.PRODUCT_URL}/{spd_no}",
                    "collectedAt": now_iso,
                }
            )

        logger.info(f"[LOTTEON] econJs JSON 파싱 → {len(products)}개")
        return products

    def _parse_search_econjs_regex(
        self, html: str, now_iso: str
    ) -> list[dict[str, Any]]:
        """econJs JSON 파싱 실패 시 정규식으로 spdNo/spdNm/price/image 개별 추출.

        값 사이에 줄바꿈이 있을 수 있으므로 re.DOTALL 사용.
        """
        products: list[dict[str, Any]] = []
        seen: set[str] = set()

        # spdNo 전체 목록 추출 (PD/LI/LO/LE 모두 포함)
        spd_no_pattern = re.compile(
            r'"spdNo"\s*:\s*"([A-Z]{2}\d{6,12})"',
            re.DOTALL,
        )

        # 각 상품 블록 단위로 파싱 (spdNo 앞뒤 500자 슬라이싱)
        for m in spd_no_pattern.finditer(html):
            spd_no = m.group(1)
            if spd_no in seen:
                continue
            seen.add(spd_no)

            # 해당 상품 블록 (전후 500자)
            block_start = max(0, m.start() - 50)
            block_end = min(len(html), m.end() + 600)
            block = html[block_start:block_end]

            name_m = re.search(r'"spdNm"\s*:\s*"([^"]+)"', block, re.DOTALL)
            name = name_m.group(1).strip() if name_m else ""
            if not name:
                continue

            price_m = re.search(r'"price"\s*:\s*(\d+)', block, re.DOTALL)
            disc_m = re.search(r'"discountPrice"\s*:\s*(\d+)', block, re.DOTALL)
            original_price = int(price_m.group(1)) if price_m else 0
            sale_price = int(disc_m.group(1)) if disc_m else original_price

            img_m = re.search(r'"image"\s*:\s*"([^"]+)"', block, re.DOTALL)
            thumbnail = self._normalize_image(img_m.group(1) if img_m else "")

            # sitmNo 추출 (LE1220156946_1321122096 형태)
            sitm_m = re.search(r'"sitmNo"\s*:\s*"([^"]+)"', block, re.DOTALL)
            sitm_no = sitm_m.group(1) if sitm_m else ""

            is_sold_out = bool(
                re.search(r"soldout|sold_out|품절", block, re.IGNORECASE)
            )

            products.append(
                {
                    "siteProductId": spd_no,
                    "sitmNo": sitm_no,
                    "name": name,
                    "brand": "",
                    "originalPrice": original_price,
                    "salePrice": sale_price if sale_price > 0 else original_price,
                    "thumbnailImageUrl": thumbnail,
                    "isSoldOut": is_sold_out,
                    "sourceSite": "LOTTEON",
                    "sourceUrl": f"{self.PRODUCT_URL}/{spd_no}",
                    "collectedAt": now_iso,
                }
            )

        logger.info(f"[LOTTEON] econJs 정규식 폴백 → {len(products)}개")
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

                    # URL에서 상품번호 추출 (PD/LI/LO/LE 등 모든 prefix 허용)
                    url = product.get("url", "")
                    product_no = ""
                    no_match = re.search(
                        r"/p/product/([A-Z]{2}\d{6,12})", url, re.IGNORECASE
                    )
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

    PBF_BASE = "https://pbf.lotteon.com"

    async def get_product_detail(
        self, product_no: str, refresh_only: bool = False
    ) -> dict[str, Any]:
        """롯데ON 상품 상세 정보 조회.

        1단계: 상품 페이지 HTML → JSON-LD로 기본 정보 파싱
        2단계: HTML에서 sitmNo 추출 → pbf.lotteon.com API로 옵션/재고/이미지 보완

        Args:
          product_no: 롯데ON 상품 번호 (LO/PD/LI/LE prefix)
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
                detail = self._parse_json_ld_detail(
                    html, product_no, now_iso, timestamp
                )
                if detail:
                    self._enrich_from_html(detail, html)
                else:
                    # 방법 2: __NEXT_DATA__에서 파싱
                    detail = self._parse_next_data_detail(
                        html, product_no, now_iso, timestamp
                    )
                    if not detail:
                        # 방법 3: 메타 태그 + HTML 폴백
                        detail = self._parse_meta_detail(
                            html, product_no, now_iso, timestamp
                        )

                if not detail:
                    return {}

                # 2단계: pbf API로 옵션/재고/이미지 보완
                sitm_no = self._extract_sitmno_from_html(html)
                if sitm_no:
                    pbf_data = await self._fetch_pbf_detail(sitm_no, client)
                    if pbf_data:
                        self._enrich_from_pbf(detail, pbf_data)
                        logger.info(
                            f"[LOTTEON] pbf 보완 완료: {product_no} (sitmNo={sitm_no})"
                        )
                    else:
                        logger.debug(f"[LOTTEON] pbf 데이터 없음: {sitm_no}")
                else:
                    logger.debug(f"[LOTTEON] sitmNo 추출 실패: {product_no}")

                return detail

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[LOTTEON] 상세 조회 타임아웃: {product_no}")
            return {}
        except Exception as e:
            logger.error(f"[LOTTEON] 상세 조회 실패: {product_no} — {e}")
            return {}

    async def search(
        self, keyword: str, max_count: int = 100, **kwargs: Any
    ) -> dict[str, Any]:
        """worker.py 직접 API 패턴 호환 래퍼 — search_products() 결과를 snake_case 표준 포맷으로 반환.

        _parse_search_econjs가 camelCase 키(siteProductId, salePrice 등)를 반환하므로
        worker.py가 기대하는 snake_case 키(site_product_id, sale_price 등)로 변환한다.
        """
        category_filter = kwargs.pop("category_filter", "")
        raw = await self.search_products(
            keyword, size=min(max_count, 60), display_category_id=category_filter
        )
        products = []
        for item in raw:
            # camelCase → snake_case 정규화
            site_product_id = (
                item.get("site_product_id")
                or item.get("siteProductId")
                or item.get("spdNo")
                or ""
            )
            if not site_product_id:
                continue
            thumbnail = (
                item.get("thumbnailImageUrl") or item.get("thumbnail_image_url") or ""
            )
            products.append(
                {
                    "site_product_id": site_product_id,
                    "name": item.get("name", ""),
                    "brand": item.get("brand", ""),
                    "sale_price": item.get("sale_price") or item.get("salePrice") or 0,
                    "original_price": item.get("original_price")
                    or item.get("originalPrice")
                    or 0,
                    "images": [thumbnail] if thumbnail else [],
                    "source_url": item.get("source_url")
                    or item.get("sourceUrl")
                    or f"{self.PRODUCT_URL}/{site_product_id}",
                    "free_shipping": item.get("free_shipping", False),
                    "options": item.get("options", []),
                }
            )
        return {"products": products, "total": len(products)}

    async def get_detail(self, product_id: str) -> dict[str, Any]:
        """worker.py get_detail 패턴 호환 래퍼 — get_product_detail() 결과 반환."""
        return await self.get_product_detail(product_id)

    async def scan_categories(self, keyword: str, **_kwargs: Any) -> dict[str, Any]:
        """롯데ON 카테고리 스캔 — 검색 HTML의 displayCategoryFilter에서 전체 카테고리 트리 추출.

        무신사의 필터 API와 동일한 원리: 검색 1회 요청으로 카테고리 트리 + 상품 수를 한번에 가져온다.
        econJs.SearchApp.create() 안의 displayCategoryFilter 객체를 파싱한다.

        Returns:
            {
                "categories": [{"categoryCode", "path", "count", "category1", "category2", "category3", "category4"}],
                "total": int,
                "groupCount": int,
            }
        """
        search_url = (
            f"{self.SEARCH_URL}?render=search&platform=pc"
            f"&q={quote(keyword)}&page=1&size=1&mallId=2"
        )
        logger.info(f'[LOTTEON] 카테고리 스캔 시작: "{keyword}"')

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(search_url, headers=self.HEADERS)
                if resp.status_code != 200:
                    logger.warning(f"[LOTTEON] 카테고리 스캔 HTTP {resp.status_code}")
                    return {"categories": [], "total": 0, "groupCount": 0}
                html = resp.text
        except Exception as e:
            logger.error(f"[LOTTEON] 카테고리 스캔 요청 실패: {e}")
            return {"categories": [], "total": 0, "groupCount": 0}

        categories = self._parse_display_category_filter(html)

        total = sum(c["count"] for c in categories)
        logger.info(
            f"[LOTTEON] 카테고리 스캔 완료: keyword={keyword!r}, "
            f"카테고리={len(categories)}개, 총 상품={total}개"
        )

        return {
            "categories": categories,
            "total": total,
            "groupCount": len(categories),
        }

    def _parse_display_category_filter(self, html: str) -> list[dict[str, Any]]:
        """검색 HTML의 displayCategoryFilter에서 카테고리 트리를 평탄화하여 반환.

        leaf 카테고리(최하위)만 반환하되, 상위 경로를 category1~4에 포함한다.
        """
        # displayCategoryFilter의 items 배열 위치 찾기
        m = re.search(
            r"displayCategoryFilter:\s*\{[^}]*?items:\s*(\[)",
            html,
            re.DOTALL,
        )
        if not m:
            logger.debug("[LOTTEON] displayCategoryFilter not found")
            return []

        # 대괄호 깊이 추적으로 items 배열 전체 추출
        start = m.start(1)
        depth = 0
        end = start
        for i in range(start, min(start + 200000, len(html))):
            ch = html[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        raw = html[start:end]
        # 후행 콤마 제거 (JSON 비표준)
        raw = re.sub(r",\s*([}\]])", r"\1", raw)

        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"[LOTTEON] displayCategoryFilter JSON 파싱 실패: {e}")
            return []

        # 트리 → 평탄 리스트 (depth 3 기준 집계 — 중분류 단위로 묶기)
        # depth 3 노드: 하위 leaf 카운트를 합산하여 하나의 카테고리로 반환
        # depth 3이 leaf이면 그대로 반환
        results: list[dict[str, Any]] = []

        def _sum_count(node: dict) -> int:
            """노드와 모든 하위 노드의 count 합산."""
            total = int(node.get("count", 0) or 0)
            for child in node.get("children", []):
                total += _sum_count(child)
            return total

        def _flatten(nodes: list, path_parts: list[str], current_depth: int) -> None:
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                name = str(node.get("displayCategoryName", "") or "").strip()
                cat_id = str(node.get("displayCategoryId", "") or "").strip()
                children = node.get("children", [])
                current_path = path_parts + [name] if name else path_parts

                # depth 3 이상이면 여기서 집계 (하위를 합산)
                if current_depth >= 3 or not children:
                    count = (
                        _sum_count(node) if children else int(node.get("count", 0) or 0)
                    )
                    if not cat_id or count <= 0:
                        continue
                    path_str = " > ".join(current_path)
                    results.append(
                        {
                            "categoryCode": cat_id,
                            "path": path_str,
                            "count": count,
                            "category1": current_path[0]
                            if len(current_path) > 0
                            else "",
                            "category2": current_path[1]
                            if len(current_path) > 1
                            else "",
                            "category3": current_path[2]
                            if len(current_path) > 2
                            else "",
                        }
                    )
                else:
                    _flatten(children, current_path, current_depth + 1)

        _flatten(items, [], 1)

        # 상품 수 내림차순 정렬
        results.sort(key=lambda x: x["count"], reverse=True)
        return results

    def _extract_sitmno_from_html(self, html: str) -> str:
        """HTML에서 sitmNo 추출 (HTML 엔티티 디코딩 후 파싱)."""
        import html as html_module

        decoded = html_module.unescape(html)
        m = re.search(r'"sitmNo"\s*:\s*"([A-Z]{2}[0-9]+_[0-9]+)"', decoded)
        return m.group(1) if m else ""

    async def search_popular(
        self,
        limit: int = 50,
        keyword: str = "패션",
    ) -> list[dict[str, Any]]:
        """롯데ON 인기상품 검색 (AI 소싱기 연동용).

        인기순 정렬(sortType=BEST)로 검색하여 인기상품 목록을 반환한다.
        """
        search_url = (
            f"{self.SEARCH_URL}?render=search&platform=pc"
            f"&q={quote(keyword)}&size={min(limit, 60)}&mallId=2&sortType=BEST"
        )
        logger.info(f"[LOTTEON] 인기상품 검색 시작: keyword={keyword}, limit={limit}")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(search_url, headers=self.HEADERS)

                if resp.status_code in (429, 403):
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning(
                        f"[LOTTEON] 인기상품 검색 차단 HTTP {resp.status_code}"
                    )
                    raise RateLimitError(resp.status_code, retry_after)

                if resp.status_code != 200:
                    logger.warning(f"[LOTTEON] 인기상품 검색 HTTP {resp.status_code}")
                    return []

            products = self._parse_search_html(resp.text, keyword)
            logger.info(f"[LOTTEON] 인기상품 검색 완료: {len(products)}개")
            return products
        except RateLimitError:
            raise
        except Exception as e:
            logger.error(f"[LOTTEON] 인기상품 검색 실패: {keyword} — {e}")
            return []

    async def fetch_pbf_standalone(self, sitm_no: str) -> Optional[dict[str, Any]]:
        """pbf.lotteon.com API 독립 호출 (새 HTTP 세션 생성) — refresh 빠른경로용."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._fetch_pbf_detail(sitm_no, client)

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

    def _enrich_from_pbf(self, detail: dict[str, Any], pbf: dict[str, Any]) -> None:
        """pbf API 데이터로 detail dict 보완 (옵션/재고/이미지/가격/카테고리)."""
        # ── 가격 보완 ──────────────────────────────────────────────
        price_info = pbf.get("priceInfo") or {}
        sl_prc = self._safe_int(price_info.get("slPrc", 0))
        if sl_prc > 0:
            detail["salePrice"] = sl_prc

        # ── 최대혜택가 계산 (판매가 - 즉시할인 - 추가할인) ─────────
        immd_dc = self._safe_int(price_info.get("immdDcAplyTotAmt", 0))
        adtn_dc = self._safe_int(price_info.get("adtnDcAplyTotAmt", 0))
        base_prc = sl_prc or detail.get("salePrice", 0)
        if base_prc > 0:
            best_benefit = base_prc - immd_dc - adtn_dc
            if best_benefit > 0 and best_benefit < base_prc:
                detail["bestBenefitPrice"] = best_benefit
            else:
                detail["bestBenefitPrice"] = base_prc

        # ── 카테고리 코드 저장 및 이름 변환 ──────────────────────────
        basic = pbf.get("basicInfo") or {}
        logger.debug(f"[LOTTEON] pbf basicInfo keys: {list(basic.keys())}")
        scat_no = str(basic.get("scatNo", "") or "").strip()
        if scat_no:
            # 팀장 카테고리 룰 매핑용으로 scatNo 보존
            detail["_lotteonScatNo"] = scat_no
            # 하드코딩 딕셔너리에서 카테고리명 조회
            cat_name = _LOTTEON_SCAT_NAMES.get(scat_no, "")
            if cat_name and not detail.get("category"):
                detail["category"] = cat_name
                parts = cat_name.split(" > ")
                for i, part in enumerate(parts[:4], 1):
                    detail[f"category{i}"] = part

        # ── 스펙 필드 (basicInfo 다중 후보 키) ─────────────────────
        _SPEC_CANDIDATES: dict[str, list[str]] = {
            "manufacturer": ["mfrNm", "mfr", "manufacturerNm", "manufacturerName"],
            "origin": ["orgNm", "origin", "originNm", "madeIn", "madeInNm"],
            "sex": ["sexTpCd", "genderType", "sex"],
            "season": ["seasnCd", "season"],
            "color": ["colorNm", "colorName", "color"],
            "material": ["materialNm", "material"],
            "style_code": ["styleNo", "modelNo", "styleCode"],
            "care_instructions": ["careInstructions"],
        }
        for field, candidates in _SPEC_CANDIDATES.items():
            if not detail.get(field):
                for cand in candidates:
                    val = str(basic.get(cand, "") or "").strip()
                    if val:
                        if field == "sex":
                            val = self._normalize_sex(val)
                        detail[field] = val
                        break

        # ── 재고 ──────────────────────────────────────────────────
        stck = pbf.get("stckInfo") or {}
        stk_qty = stck.get("stkQty")
        is_out = stk_qty is not None and stk_qty == 0
        if stk_qty is not None:
            detail["isOutOfStock"] = is_out
            detail["isSoldOut"] = is_out
            detail["saleStatus"] = "sold_out" if is_out else "in_stock"

        # ── 옵션 ──────────────────────────────────────────────────
        opt_info = pbf.get("optionInfo") or {}
        option_groups = opt_info.get("optionList") or []
        options: list[dict[str, Any]] = []

        if option_groups:
            # 단일 옵션 그룹 (사이즈/색상)
            primary_group = option_groups[0]
            for opt in primary_group.get("options", []):
                label = opt.get("label", "").strip()
                if not label:
                    continue
                disabled = bool(opt.get("disabled", False))
                options.append(
                    {
                        "no": len(options),
                        "name": label,
                        "price": sl_prc or detail.get("salePrice", 0),
                        "stock": 0 if disabled else (stk_qty or 1),
                        "isSoldOut": disabled,
                    }
                )

            # 멀티 옵션 그룹 (색상 + 사이즈) — label 조합
            if len(option_groups) >= 2:
                options = []
                for g1_opt in option_groups[0].get("options", []):
                    for g2_opt in option_groups[1].get("options", []):
                        combined_disabled = g1_opt.get("disabled", False) or g2_opt.get(
                            "disabled", False
                        )
                        combined_label = f"{g1_opt.get('label', '')} / {g2_opt.get('label', '')}".strip(
                            " /"
                        )
                        options.append(
                            {
                                "no": len(options),
                                "name": combined_label,
                                "price": sl_prc or detail.get("salePrice", 0),
                                "stock": 0 if combined_disabled else (stk_qty or 1),
                                "isSoldOut": bool(combined_disabled),
                            }
                        )

        if options:
            detail["options"] = options

        # ── 이미지 보완 ────────────────────────────────────────────
        img_info = pbf.get("imgInfo") or {}
        img_list = img_info.get("imageList") or []
        pbf_images: list[str] = []
        for img in img_list:
            path = img.get("imgRteNm", "") + img.get("imgFileNm", "")
            if path:
                full_url = f"https://contents.lotteon.com/itemimage{path}"
                pbf_images.append(self._normalize_image(full_url))

        if pbf_images and not detail.get("images"):
            detail["images"] = pbf_images[:9]
        elif pbf_images and len(detail.get("images", [])) < 2:
            detail["images"] = pbf_images[:9]

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
                    "manufacturer": "",
                    "origin": "",
                    "sex": "",
                    "season": "",
                    "color": "",
                    "material": "",
                    "style_code": self._extract_style_code_from_name(name.strip()),
                    "care_instructions": "",
                    "quality_guarantee": "",
                    "shipping_fee": 0,
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

            # 스펙 필드 추출
            manufacturer = str(
                product.get("mfrNm", "")
                or product.get("manufacturerNm", "")
                or product.get("manufacturer", "")
                or ""
            ).strip()
            origin = str(
                product.get("orgNm", "")
                or product.get("originNm", "")
                or product.get("madeIn", "")
                or product.get("origin", "")
                or ""
            ).strip()
            sex_raw = str(
                product.get("sexTpCd", "")
                or product.get("genderType", "")
                or product.get("sex", "")
                or ""
            ).strip()
            sex = self._normalize_sex(sex_raw) if sex_raw else ""
            season = str(
                product.get("seasnCd", "") or product.get("season", "") or ""
            ).strip()
            color = str(
                product.get("colorNm", "")
                or product.get("colorName", "")
                or product.get("color", "")
                or ""
            ).strip()
            material = str(
                product.get("materialNm", "") or product.get("material", "") or ""
            ).strip()
            style_code = str(
                product.get("styleNo", "")
                or product.get("modelNo", "")
                or product.get("styleCode", "")
                or ""
            ).strip() or self._extract_style_code_from_name(name.strip())
            care_instructions = str(product.get("careInstructions", "") or "").strip()

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
                "manufacturer": manufacturer,
                "origin": origin,
                "sex": sex,
                "season": season,
                "color": color,
                "material": material,
                "style_code": style_code,
                "care_instructions": care_instructions,
                "quality_guarantee": "",
                "shipping_fee": 0,
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
            "manufacturer": "",
            "origin": "",
            "sex": "",
            "season": "",
            "color": "",
            "material": "",
            "style_code": self._extract_style_code_from_name(name.strip()),
            "care_instructions": "",
            "quality_guarantee": "",
            "shipping_fee": 0,
        }

    # ------------------------------------------------------------------
    # 스펙 헬퍼
    # ------------------------------------------------------------------

    def _parse_spec_table(self, html: str) -> dict[str, str]:
        """HTML th-td 쌍에서 스펙 테이블 파싱 (제조사/원산지/소재 등)."""
        KEY_MAP: dict[str, str] = {
            "제조사": "manufacturer",
            "수입사": "manufacturer",
            "제조자": "manufacturer",
            "제조자, 수입자": "manufacturer",
            "수입자": "manufacturer",
            "제조국": "origin",
            "원산지": "origin",
            "소재": "material",
            "재질": "material",
            "성별": "sex",
            "시즌": "season",
            "색상": "color",
            "컬러": "color",
            "품번": "style_code",
            "모델번호": "style_code",
            "취급주의": "care_instructions",
            "세탁": "care_instructions",
            "취급시 주의사항": "care_instructions",
        }
        GARBAGE = {
            "상세설명참조",
            "상세페이지참조",
            "상품상세참조",
            "상품상세 참조",
            "-",
            "없음",
            "해당없음",
            "n/a",
            "별도표기",
            "상세페이지 참조",
        }
        result: dict[str, str] = {}
        for th, td in re.findall(
            r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>",
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            key = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", th)).strip()
            val = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", td)).strip()
            if not key or not val:
                continue
            if val.lower() in GARBAGE:
                continue
            mapped = KEY_MAP.get(key)
            if mapped and mapped not in result:
                result[mapped] = val
        return result

    def _extract_style_code_from_name(self, name: str) -> str:
        """상품명에서 품번 추출 (나이키형/아디다스형 패턴)."""
        BLACKLIST = {"BC", "LO", "PD", "LE"}
        for pattern in [
            r"\b([A-Z]{2}\d{4}-\d{3})\b",
            r"\b([A-Z]{2,3}\d{4,5}[A-Z]?\d?)\b",
        ]:
            for m in re.finditer(pattern, name):
                code = m.group(1)
                if code[:2] not in BLACKLIST:
                    return code
        return ""

    def _normalize_sex(self, val: str) -> str:
        """성별 값 정규화."""
        v = val.strip().lower()
        if v in {"남녀공용", "공용", "unisex"}:
            return "남녀공용"
        if v in {"여성", "여자", "women", "woman"}:
            return "여성"
        if v in {"남성", "남자", "men", "man"}:
            return "남성"
        return val.strip()

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

        # 스펙 테이블 파싱 (이미 채워진 필드는 덮어쓰지 않음)
        spec = self._parse_spec_table(html)
        for field, val in spec.items():
            if not detail.get(field):
                if field == "sex":
                    val = self._normalize_sex(val)
                detail[field] = val

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
                            "no": len(options),
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
                        "no": len(options),
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
