"""SSG(신세계몰) 소싱용 웹 스크래핑 클라이언트 - httpx 기반.

주의: proxy/ssg.py는 판매처(마켓) 등록용 Open API 클라이언트이므로,
소싱(상품 수집)용은 이 파일에서 별도로 관리한다.

SSG 사이트 정보:
  - 검색: https://department.ssg.com/search.ssg?query={keyword}
  - 상세: https://department.ssg.com/item/itemView.ssg?itemId={13자리}
  - 이미지 CDN: sitem.ssgcdn.com
  - robots.txt 엄격 → 보수적 간격 필수 (2초+ 권장)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from backend.utils.logger import logger


class RateLimitError(Exception):
    """SSG 차단 감지 (429/403)."""

    def __init__(self, status: int, retry_after: int = 0):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"HTTP {status} (retry_after={retry_after})")


class SSGSourcingClient:
    """SSG 소싱용 웹 스크래핑 클라이언트 (검색, 상세).

    SSG 백화점몰(department.ssg.com) 상품 페이지를 HTML 파싱하여
    상품 검색/상세 정보를 추출한다.
    robots.txt가 엄격하므로 보수적 간격으로 요청해야 한다.
    """

    BASE = "https://department.ssg.com"
    SEARCH_URL = "https://department.ssg.com/search.ssg"
    ITEM_URL = "https://department.ssg.com/item/itemView.ssg"
    IMAGE_CDN = "sitem.ssgcdn.com"

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
        "Referer": "https://department.ssg.com/",
    }

    def __init__(self, cookie: str = "") -> None:
        """cookie가 있으면 로그인 상태로 최대혜택가 정밀 계산 가능."""
        self._timeout = httpx.Timeout(20.0, connect=10.0)
        self.cookie = cookie

    def _headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        """요청 헤더 생성. 쿠키가 있으면 포함."""
        h = {**self.HEADERS}
        if self.cookie:
            h["Cookie"] = self.cookie
        if extra:
            h.update(extra)
        return h

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
        """SSG 상품 검색.

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
            f"{self.SEARCH_URL}?query={quote(keyword)}"
            f"&page={page}&count={min(size, 60)}"
        )
        logger.info(f'[SSG] 검색 시작: "{keyword}" (page={page})')

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(search_url, headers=self._headers())

                # 차단 감지
                if resp.status_code in (429, 403):
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning(f"[SSG] 차단 감지 HTTP {resp.status_code}")
                    raise RateLimitError(resp.status_code, retry_after)

                if resp.status_code != 200:
                    logger.warning(f"[SSG] 검색 페이지 HTTP {resp.status_code}")
                    return []

            html = resp.text
            products = self._parse_search_html(html, keyword)
            logger.info(f'[SSG] 검색 완료: "{keyword}" -> {len(products)}개')
            return products

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[SSG] 검색 타임아웃: {keyword}")
            return []
        except Exception as e:
            logger.error(f"[SSG] 검색 실패: {keyword} — {e}")
            return []

    def _parse_search_html(self, html: str, keyword: str) -> list[dict[str, Any]]:
        """검색 결과 HTML에서 상품 정보 추출.

        SSG 검색 페이지는 상품 카드가 data-info 속성 또는
        <li class="cunit_t232"> 구조로 반복된다.
        """
        products: list[dict[str, Any]] = []
        seen: set[str] = set()

        # 방법 1: data-info JSON 블록에서 추출 (SSG 검색 결과에 포함)
        data_info_pattern = re.compile(
            r"data-info='(\{[^']+\})'",
            re.DOTALL,
        )
        for m in data_info_pattern.finditer(html):
            try:
                info = json.loads(m.group(1))
                item_id = str(info.get("itemId", "") or info.get("sitemId", ""))
                if not item_id or item_id in seen:
                    continue
                seen.add(item_id)

                products.append(
                    {
                        "siteProductId": item_id,
                        "goodsNo": item_id,
                        "name": info.get("itemNm", "").strip(),
                        "salePrice": self._safe_int(info.get("sellprc", 0)),
                        "originalPrice": self._safe_int(info.get("norprc", 0))
                        or self._safe_int(info.get("sellprc", 0)),
                        "image": self._normalize_image(info.get("imgUrl", "")),
                        "isSoldOut": info.get("soldOutYn", "N") == "Y",
                    }
                )
            except (json.JSONDecodeError, KeyError):
                continue

        # 방법 2: 상품 링크 + 블록 파싱 (data-info가 없는 경우 폴백)
        if not products:
            products = self._parse_search_blocks(html, seen)

        return products

    def _parse_search_blocks(self, html: str, seen: set[str]) -> list[dict[str, Any]]:
        """검색 결과 HTML 블록에서 상품 정보 추출 (폴백)."""
        products: list[dict[str, Any]] = []

        # 상품 링크 패턴: itemView.ssg?itemId=XXXXXXXXXXXXX
        item_pattern = re.compile(
            r"itemView\.ssg\?itemId=(\d{10,13})",
            re.IGNORECASE,
        )

        # 상품 블록 단위 분리 (li 태그 기반)
        block_pattern = re.compile(
            r'<li[^>]*class="[^"]*cunit[^"]*"[^>]*>(.*?)</li>',
            re.DOTALL | re.IGNORECASE,
        )

        blocks = block_pattern.findall(html)
        if not blocks:
            blocks = [html]

        for block in blocks:
            id_matches = item_pattern.findall(block)
            for item_id in id_matches:
                if item_id in seen:
                    continue
                seen.add(item_id)

                # 상품명 추출
                name = self._extract_text(
                    block, r'class="[^"]*title[^"]*"[^>]*>([^<]+)'
                )
                if not name:
                    name = self._extract_text(block, r'title="([^"]+)"')

                # 가격 추출
                sale_price = self._extract_price(
                    block, r'class="[^"]*ssg_price[^"]*"[^>]*>.*?(\d[\d,]+)'
                )
                if sale_price == 0:
                    sale_price = self._extract_price(
                        block, r'class="[^"]*price[^"]*"[^>]*>.*?(\d[\d,]+)'
                    )
                original_price = self._extract_price(
                    block, r'class="[^"]*old_price[^"]*"[^>]*>.*?(\d[\d,]+)'
                )
                if original_price == 0:
                    original_price = sale_price

                # 이미지 추출
                thumbnail = self._extract_text(block, r'<img[^>]+src="([^"]+)"')
                thumbnail = self._normalize_image(thumbnail)

                # 품절 여부
                is_sold_out = bool(
                    re.search(r"(?:품절|soldout|sold_out)", block, re.IGNORECASE)
                )

                if name and sale_price > 0:
                    products.append(
                        {
                            "siteProductId": item_id,
                            "goodsNo": item_id,
                            "name": name.strip(),
                            "salePrice": sale_price,
                            "originalPrice": original_price,
                            "image": thumbnail,
                            "isSoldOut": is_sold_out,
                        }
                    )

        return products

    # ------------------------------------------------------------------
    # 상세 조회
    # ------------------------------------------------------------------

    async def get_product_detail(
        self, item_id: str, refresh_only: bool = False
    ) -> dict[str, Any]:
        """SSG 상품 상세 정보 조회.

        상품 페이지 HTML에서 메타 태그, 스크립트 데이터, 옵션 영역을 파싱한다.

        Args:
          item_id: SSG 상품 ID (13자리 숫자)
          refresh_only: True이면 가격/재고만 빠르게 갱신

        Returns:
          표준 상품 상세 dict (무신사 프록시 반환 형식과 동일)

        Raises:
          RateLimitError: 429/403 응답 시
        """
        url = f"{self.ITEM_URL}?itemId={item_id}"
        logger.info(f"[SSG] 상세 조회: {item_id}")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=self._headers())

                # 차단 감지
                if resp.status_code in (429, 403):
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning(
                        f"[SSG] 차단 감지 HTTP {resp.status_code}: {item_id}"
                    )
                    raise RateLimitError(resp.status_code, retry_after)

                if resp.status_code != 200:
                    logger.warning(
                        f"[SSG] 상세 페이지 HTTP {resp.status_code}: {item_id}"
                    )
                    return {}

            html = resp.text
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

            # 메타 태그에서 기본 정보 추출
            name = self._extract_meta(html, "og:title") or ""
            thumbnail = self._normalize_image(
                self._extract_meta(html, "og:image") or ""
            )
            description = self._extract_meta(html, "og:description") or ""

            # 가격 추출
            sale_price = self._parse_sale_price(html)
            original_price = self._parse_original_price(html)
            if original_price == 0:
                original_price = sale_price
            best_benefit_price = self._parse_best_benefit_price(html) or sale_price

            # 브랜드 추출
            brand = self._parse_brand(html)

            # 카테고리 추출
            category_levels = self._parse_category(html)
            category_str = " > ".join(category_levels) if category_levels else ""

            # 이미지 목록 (대표 + 추가 이미지, 최대 9장)
            images = self._parse_product_images(html, thumbnail)

            # 상세 이미지 추출
            detail_images = self._parse_detail_images(html)

            # 옵션 추출
            options = self._parse_options(html)

            # 품절 여부
            is_out_of_stock = self._check_sold_out(html, options)

            # 배송 정보
            free_shipping = bool(
                re.search(r"(?:무료배송|무료 배송|배송비\s*무료)", html, re.IGNORECASE)
            )
            same_day_delivery = bool(
                re.search(r"(?:당일배송|쓱배송|새벽배송|쓱-배송)", html, re.IGNORECASE)
            )

            # 판매 상태 판별
            sale_status = "sold_out" if is_out_of_stock else "in_stock"

            return {
                "id": f"col_ssg_{item_id}_{timestamp}",
                "sourceSite": "SSG",
                "siteProductId": str(item_id),
                "sourceUrl": f"https://department.ssg.com/item/itemView.ssg?itemId={item_id}",
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

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[SSG] 상세 조회 타임아웃: {item_id}")
            return {}
        except Exception as e:
            logger.error(f"[SSG] 상세 조회 실패: {item_id} — {e}")
            return {}

    # ------------------------------------------------------------------
    # 가격 파싱 헬퍼
    # ------------------------------------------------------------------

    def _parse_sale_price(self, html: str) -> int:
        """판매가 추출.

        SSG는 여러 위치에 가격이 표시될 수 있으므로 우선순위로 탐색:
        1. product:price:amount 메타 태그
        2. 판매가 영역 (ssg_price, sale_price)
        3. 일반 가격 영역
        """
        # 메타 태그 우선
        price_meta = self._extract_meta(html, "product:price:amount")
        if price_meta:
            price = self._safe_int(re.sub(r"[^\d]", "", price_meta))
            if price > 0:
                return price

        # SSG 판매가 영역
        for pattern in [
            r'class="[^"]*ssg_price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*sale[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*cdtl_price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'id="[^"]*price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    def _parse_original_price(self, html: str) -> int:
        """정상가(원래 가격) 추출."""
        for pattern in [
            r'class="[^"]*old[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*org[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*original[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*cdtl_old_price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price

        return 0

    def _parse_best_benefit_price(self, html: str) -> int:
        """최대혜택가 추출 (쿠폰+적립금 포함).

        SSG는 쿠폰/카드할인/적립금 등 다양한 혜택이 있으며,
        로그인 상태에 따라 최대혜택가가 달라진다.
        """
        for pattern in [
            r'class="[^"]*best[_-]?benefit[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*coupon[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r"(?:최대혜택가|쿠폰적용가)[^<]*?(\d[\d,]+)",
            r'class="[^"]*cdtl_coupon_price[^"]*"[^>]*>.*?(\d[\d,]+)',
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
        # SSG 브랜드 영역
        for pattern in [
            r'class="[^"]*cdtl_brand[^"]*"[^>]*>([^<]+)',
            r'class="[^"]*brand[_-]?name[^"]*"[^>]*>([^<]+)',
            r'class="[^"]*brand[_-]?area[^"]*"[^>]*>\s*<a[^>]*>([^<]+)',
        ]:
            brand = self._extract_text(html, pattern)
            if brand:
                return brand.strip()

        # og:site_name에서 브랜드 힌트 추출 (일부 브랜드관)
        site_name = self._extract_meta(html, "og:site_name") or ""
        if site_name and site_name not in ("SSG.COM", "신세계몰", "이마트몰"):
            return site_name.strip()

        return ""

    def _parse_category(self, html: str) -> list[str]:
        """카테고리 경로 추출 (깊이별 리스트).

        SSG 상품 페이지의 브레드크럼 또는 카테고리 네비게이션에서 추출.
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
            # "홈" 같은 루트 항목 제외
            for text in link_texts:
                text = text.strip()
                if text and text not in ("홈", "HOME", "SSG.COM"):
                    categories.append(text)

        # 브레드크럼이 없으면 카테고리 메타 태그
        if not categories:
            cat_meta = self._extract_meta(html, "product:category")
            if cat_meta:
                categories = [c.strip() for c in cat_meta.split(">") if c.strip()]

        # product_category 속성에서 추출
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
                    if t.strip() and t.strip() not in ("홈", ">", "/")
                ]

        return categories[:4]

    def _parse_product_images(self, html: str, thumbnail: str) -> list[str]:
        """상품 이미지 목록 추출 (대표 이미지 포함, 최대 9장)."""
        images: list[str] = []
        if thumbnail:
            images.append(thumbnail)

        # SSG 상품 이미지 영역 (슬라이드/갤러리)
        gallery_pattern = re.compile(
            r'class="[^"]*cdtl_gallery[^"]*"[^>]*>(.*?)</(?:div|ul)',
            re.DOTALL | re.IGNORECASE,
        )
        gallery = gallery_pattern.search(html)
        target = gallery.group(1) if gallery else html

        # ssgcdn.com 이미지 패턴
        img_pattern = re.compile(
            r'(?:src|data-src|data-lazy)=["\']([^"\']*ssgcdn\.com[^"\']+)["\']',
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
                r'class="[^"]*cdtl[_-]?img[^"]*"[^>]*>.*?<img[^>]+src="([^"]+)"',
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

        # SSG 상세 설명 영역
        detail_area = re.search(
            r'(?:id="[^"]*cdtl_desc[^"]*"|class="[^"]*cdtl_desc[^"]*"|id="[^"]*detail[_-]?cont[^"]*")[^>]*>(.*)',
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

        SSG 옵션은 셀렉트박스 또는 JSON 데이터로 제공된다.
        """
        options: list[dict[str, Any]] = []

        # 방법 1: 옵션 JSON 데이터에서 추출
        option_json_pattern = re.compile(
            r"(?:optionData|itemOptList|optionList)\s*[=:]\s*(\[.*?\]);",
            re.DOTALL,
        )
        json_match = option_json_pattern.search(html)
        if json_match:
            try:
                option_list = json.loads(json_match.group(1))
                for opt in option_list:
                    opt_name = (
                        opt.get("optNm", "")
                        or opt.get("optionNm", "")
                        or opt.get("name", "")
                    ).strip()
                    if not opt_name:
                        continue

                    opt_price = self._safe_int(
                        opt.get("sellprc", 0)
                        or opt.get("addPrc", 0)
                        or opt.get("price", 0)
                    )
                    opt_stock = self._safe_int(
                        opt.get("stockQty", 0) or opt.get("stock", 0)
                    )
                    is_sold_out = (
                        opt.get("soldOutYn", "N") == "Y"
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

        # 명시적 품절 텍스트 (버튼 영역)
        button_area = re.search(
            r'class="[^"]*cdtl_btn[^"]*"[^>]*>(.*?)</div>',
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
