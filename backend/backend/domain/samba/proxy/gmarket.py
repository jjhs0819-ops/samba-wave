"""지마켓 웹 스크래핑 클라이언트 - httpx 기반.

지마켓은 React SPA로 렌더링되어 직접 크롤링이 어려운 구조.
HTML에 포함된 서버 사이드 데이터(__NEXT_DATA__ 등)와
검색 API를 활용하여 상품 정보를 추출한다.

주의: 지마켓은 차단 강도가 높으므로 보수적 간격(1초+)으로 요청.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from backend.utils.logger import logger


class GMarketClient:
    """지마켓 웹 스크래핑 클라이언트 (검색, 상세).

    지마켓은 SPA 기반이라 서버 렌더링 HTML에서 데이터를 추출하거나,
    내부 API 엔드포인트를 활용한다.
    """

    BASE = "https://www.gmarket.co.kr"
    ITEM_BASE = "https://item.gmarket.co.kr"
    # 지마켓 내부 검색 API (JSON 응답)
    SEARCH_API = "https://browse.gmarket.co.kr/search"

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
    }

    JSON_HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.gmarket.co.kr/",
        "Origin": "https://www.gmarket.co.kr",
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
        """지마켓 상품 검색.

        검색 페이지 HTML을 파싱하여 상품 목록을 추출한다.
        SPA 렌더링 전 서버에서 내려주는 초기 데이터를 활용.

        Args:
          keyword: 검색 키워드
          page: 페이지 번호 (1부터)
          size: 페이지당 결과 수 (최대 60)
          **filters: 추가 필터 (star_delivery 등)

        Returns:
          표준 상품 dict 리스트
        """
        search_url = (
            f"{self.BASE}/n/search?keyword={quote(keyword)}&p={page}&s={min(size, 60)}"
        )
        logger.info(f'[GMARKET] 검색 시작: "{keyword}" (page={page})')

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(search_url, headers=self.HEADERS)
                if resp.status_code != 200:
                    logger.warning(f"[GMARKET] 검색 페이지 HTTP {resp.status_code}")
                    return []

            html = resp.text
            products = self._parse_search_html(html, keyword)
            logger.info(f'[GMARKET] 검색 완료: "{keyword}" -> {len(products)}개')
            return products

        except httpx.TimeoutException:
            logger.error(f"[GMARKET] 검색 타임아웃: {keyword}")
            return []
        except Exception as e:
            logger.error(f"[GMARKET] 검색 실패: {keyword} — {e}")
            return []

    def _parse_search_html(self, html: str, keyword: str) -> list[dict[str, Any]]:
        """검색 결과 HTML에서 상품 정보 추출.

        지마켓 검색 페이지는 상품 카드가 data-montelena-* 속성 또는
        <div class="box__item-container"> 구조로 반복된다.
        """
        products: list[dict[str, Any]] = []
        seen: set[str] = set()
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        # 방법 1: 상품 ID + 링크 패턴으로 추출
        # 지마켓 상품 링크: /Item?goodscode=XXXXXXXX 또는 item.gmarket.co.kr/Item?goodscode=
        item_pattern = re.compile(
            r'(?:href=["\'](?:https?://item\.gmarket\.co\.kr)?/Item\?goodscode=(\d+)["\'])',
            re.IGNORECASE,
        )

        # 상품 블록 단위로 파싱
        # 지마켓 검색 결과는 <div class="box__item-container"> 또는 유사 구조
        block_pattern = re.compile(
            r'<div[^>]*class="[^"]*box__item[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
            re.DOTALL,
        )

        blocks = block_pattern.findall(html)

        # 블록이 없으면 전체 HTML에서 상품 링크 추출
        if not blocks:
            blocks = [html]

        for block in blocks:
            id_matches = item_pattern.findall(block)
            for goods_code in id_matches:
                if goods_code in seen:
                    continue
                seen.add(goods_code)

                # 상품명 추출
                name = self._extract_text(
                    block, r'class="[^"]*text__item[_-]?title[^"]*"[^>]*>([^<]+)'
                )
                if not name:
                    name = self._extract_text(block, r'title="([^"]+)"')

                # 가격 추출
                sale_price = self._extract_price(
                    block, r'class="[^"]*text__value[^"]*"[^>]*>([^<]+)'
                )
                original_price = self._extract_price(
                    block, r'class="[^"]*text__origin[^"]*"[^>]*>([^<]+)'
                )
                if original_price == 0:
                    original_price = sale_price

                # 이미지 추출
                thumbnail = self._extract_text(block, r'<img[^>]+src="([^"]+)"')
                if thumbnail and thumbnail.startswith("//"):
                    thumbnail = f"https:{thumbnail}"

                # 스타배송 여부
                is_star_delivery = bool(
                    re.search(
                        r"(?:스타배송|stardelivery|star-delivery)", block, re.IGNORECASE
                    )
                )

                # 브랜드 추출 (지마켓은 브랜드가 별도로 표시되지 않는 경우 많음)
                brand = self._extract_text(
                    block, r'class="[^"]*text__brand[^"]*"[^>]*>([^<]+)'
                )

                # 할인율 추출
                discount_rate = self._extract_price(
                    block, r'class="[^"]*text__rate[^"]*"[^>]*>(\d+)'
                )

                if name and sale_price > 0:
                    products.append(
                        {
                            "siteProductId": goods_code,
                            "name": name.strip(),
                            "brand": brand.strip() if brand else "",
                            "originalPrice": original_price,
                            "salePrice": sale_price,
                            "discountRate": discount_rate,
                            "thumbnailImageUrl": thumbnail or "",
                            "isSoldOut": False,
                            "isStarDelivery": is_star_delivery,
                            "sourceSite": "GMARKET",
                            "sourceUrl": f"{self.ITEM_BASE}/Item?goodscode={goods_code}",
                            "collectedAt": now_iso,
                        }
                    )

        return products

    # ------------------------------------------------------------------
    # 상세 조회
    # ------------------------------------------------------------------

    async def get_product_detail(self, goods_code: str) -> dict[str, Any]:
        """지마켓 상품 상세 정보 조회.

        상품 페이지 HTML에서 메타 태그, JSON-LD, 스크립트 데이터를 파싱.

        Args:
          goods_code: 지마켓 상품 코드

        Returns:
          표준 상품 상세 dict
        """
        url = f"{self.ITEM_BASE}/Item?goodscode={goods_code}"
        logger.info(f"[GMARKET] 상세 조회: {goods_code}")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=self.HEADERS)
                if resp.status_code != 200:
                    logger.warning(
                        f"[GMARKET] 상세 페이지 HTTP {resp.status_code}: {goods_code}"
                    )
                    return {}

            html = resp.text
            now_iso = datetime.now(tz=timezone.utc).isoformat()

            # og:title에서 상품명
            name = self._extract_meta(html, "og:title") or ""

            # og:image에서 대표 이미지
            thumbnail = self._extract_meta(html, "og:image") or ""
            if thumbnail and thumbnail.startswith("//"):
                thumbnail = f"https:{thumbnail}"

            # og:description에서 설명
            description = self._extract_meta(html, "og:description") or ""

            # 가격 추출 — 메타 태그 또는 HTML 내 가격 영역
            sale_price = 0
            original_price = 0

            # product:price:amount 메타 태그
            price_meta = self._extract_meta(html, "product:price:amount")
            if price_meta:
                sale_price = int(re.sub(r"[^\d]", "", price_meta) or "0")

            # HTML 내 가격 영역 파싱
            if sale_price == 0:
                sale_price = self._extract_price(
                    html, r'class="[^"]*price_real[^"]*"[^>]*>.*?(\d[\d,]+)'
                )
            original_price_match = self._extract_price(
                html, r'class="[^"]*price_original[^"]*"[^>]*>.*?(\d[\d,]+)'
            )
            if original_price_match > 0:
                original_price = original_price_match
            if original_price == 0:
                original_price = sale_price

            # 브랜드 추출
            brand = (
                self._extract_text(
                    html, r'class="[^"]*brand[_-]?name[^"]*"[^>]*>([^<]+)'
                )
                or ""
            )

            # 카테고리 추출
            category = self._extract_meta(html, "product:category") or ""

            # 품절 여부
            is_sold_out = bool(
                re.search(r"(?:품절|sold\s*out|일시품절)", html, re.IGNORECASE)
            )

            # 스타배송 여부
            is_star_delivery = bool(
                re.search(
                    r"(?:스타배송|stardelivery|star-delivery)", html, re.IGNORECASE
                )
            )

            # 옵션 추출 (셀렉트박스 or 옵션 영역)
            options = self._parse_options(html)

            # 상세 이미지 추출
            detail_images = self._parse_detail_images(html)

            # 이미지 목록 (대표 + 추가 이미지)
            images = [thumbnail] if thumbnail else []
            additional_images = re.findall(
                r'class="[^"]*thumb[^"]*"[^>]*>.*?<img[^>]+src="([^"]+)"',
                html,
                re.DOTALL,
            )
            for img in additional_images:
                img_url = img if img.startswith("http") else f"https:{img}"
                if img_url not in images:
                    images.append(img_url)

            # 고시정보 파싱 (상품정보제공고시 테이블)
            manufacturer = (
                self._extract_notify_value(html, "제조사")
                or self._extract_notify_value(html, "브랜드")
                or brand.strip()
                or ""
            )
            origin = self._extract_notify_value(html, "원산지") or ""
            material = (
                self._extract_notify_value(html, "소재")
                or self._extract_notify_value(html, "재질")
                or self._extract_notify_value(html, "혼용률")
                or ""
            )
            care_instructions = (
                self._extract_notify_value(html, "취급주의사항")
                or self._extract_notify_value(html, "세탁방법")
                or ""
            )

            return {
                "siteProductId": goods_code,
                "name": name.strip(),
                "brand": brand.strip(),
                "originalPrice": original_price,
                "salePrice": sale_price,
                "discountRate": (
                    round((1 - sale_price / original_price) * 100)
                    if original_price > sale_price > 0
                    else 0
                ),
                "thumbnailImageUrl": thumbnail,
                "images": images,
                "detailImages": detail_images,
                "description": description,
                "category": category,
                "options": options,
                "isSoldOut": is_sold_out,
                "isStarDelivery": is_star_delivery,
                "manufacturer": manufacturer,
                "origin": origin,
                "material": material,
                "careInstructions": care_instructions,
                "sourceSite": "GMARKET",
                "sourceUrl": url,
                "collectedAt": now_iso,
                "updatedAt": now_iso,
            }

        except httpx.TimeoutException:
            logger.error(f"[GMARKET] 상세 조회 타임아웃: {goods_code}")
            return {}
        except Exception as e:
            logger.error(f"[GMARKET] 상세 조회 실패: {goods_code} — {e}")
            return {}

    # ------------------------------------------------------------------
    # 내부 파싱 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_meta(html: str, prop: str) -> Optional[str]:
        """og/product 메타 태그에서 content 추출."""
        pattern = (
            rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"'
        )
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1)
        # 순서가 다른 경우 (content가 먼저)
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
    def _extract_notify_value(html: str, label: str) -> str:
        """상품정보제공고시 테이블에서 라벨에 해당하는 값 추출.

        지마켓 고시정보는 <th>라벨</th><td>값</td> 또는
        <td>라벨</td><td>값</td> 형태의 테이블로 제공됨.
        파싱 실패 시 빈 문자열 반환 (전송 차단 없음).
        """
        # th/td 라벨 → 다음 td 값 패턴
        pattern = (
            rf"(?:<th|<td)[^>]*>\s*{re.escape(label)}\s*</t[dh]>\s*"
            rf"(?:<td|<th)[^>]*>([^<]+)</t"
        )
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return ""

    @staticmethod
    def _parse_options(html: str) -> list[dict[str, Any]]:
        """옵션 셀렉트박스에서 옵션 목록 추출."""
        options: list[dict[str, Any]] = []
        # <option value="...">옵션명</option> 패턴
        option_pattern = re.compile(
            r'<option[^>]+value="([^"]*)"[^>]*>([^<]+)</option>',
            re.IGNORECASE,
        )
        # 옵션 영역 찾기
        option_area = re.search(
            r'class="[^"]*option[_-]?select[^"]*"[^>]*>(.*?)</select>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if option_area:
            matches = option_pattern.findall(option_area.group(1))
            for value, text in matches:
                text = text.strip()
                # "선택하세요" 같은 플레이스홀더 제외
                if not value or "선택" in text:
                    continue
                # 가격 정보가 옵션명에 포함된 경우 파싱
                price_in_option = 0
                price_match = re.search(r"\(([+-]?\d[\d,]*)\)", text)
                if price_match:
                    price_in_option = int(re.sub(r"[^\d-]", "", price_match.group(1)))

                options.append(
                    {
                        "name": text,
                        "value": value,
                        "priceAdjust": price_in_option,
                        "isSoldOut": "품절" in text,
                    }
                )
        return options

    @staticmethod
    def _parse_detail_images(html: str) -> list[str]:
        """상세 설명 영역에서 이미지 URL 추출.

        G마켓 상세영역은 lazy-load라 실제 URL이 data-src/data-lazy에 있을 수 있음.
        """
        images: list[str] = []
        # 상세 설명 영역
        detail_area = re.search(
            r'(?:id="detail_cont"|class="[^"]*detail[_-]?content[^"]*")[^>]*>(.*)',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        # src + data-src + data-lazy + data-original 전부 캡처 (lazy-load 대응)
        img_pattern = re.compile(
            r'<img[^>]+(?:src|data-src|data-lazy|data-original)=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        if detail_area:
            for m in img_pattern.finditer(detail_area.group(1)):
                img_url = m.group(1)
                if img_url.startswith("//"):
                    img_url = f"https:{img_url}"
                if img_url.startswith("http") and img_url not in images:
                    images.append(img_url)
        return images
