"""REXMONDE(www.rexmonde.com, 구 OK몰) 소싱 API 클라이언트.

OK몰은 공식 API를 제공하지 않으므로 SSR HTML을 BeautifulSoup으로 파싱한다.
사이트 마크업은 OK몰 시절 그대로(div.item_box, data-ProductNo 등) — 도메인만 변경됨.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

logger = logging.getLogger(__name__)


class RexmondeClient:
    """렉스몬드 HTTP 클라이언트 + HTML 파서."""

    BASE = "https://www.rexmonde.com"
    SEARCH_PATH = "/products/list"
    DETAIL_PATH = "/products/view"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.rexmonde.com/",
    }

    TIMEOUT = httpx.Timeout(30.0, connect=10.0)

    def __init__(self) -> None:
        # 인스턴스 단위 카테고리 코드 → 이름 캐시
        self._category_name_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------------

    async def search_products(
        self,
        keyword: str,
        page: int = 1,
        size: int = 80,
        cate: str = "",
        brand: str = "",
        **kwargs: Any,
    ) -> list[dict]:
        """검색·카테고리 페이지 HTML 파싱.

        파라미터 우선순위 (rexmonde 사이트 동작):
        - brand 명시 → `brand=` 정확 필터 (해당 브랜드만 반환)
        - keyword가 5자리 숫자 (cate 미지정) → 카테고리 코드 검색 (하위호환)
        - keyword 명시 → `keyword=` 느슨 매칭 (카테고리 추천 포함, 다른 브랜드 섞임)
        cate가 함께 있으면 카테고리 정확 필터를 추가로 적용.
        page=N 파라미터로 페이지네이션. size는 SSR 고정값이라 무시.

        한계 1: 사이트가 검색 결과 영역과 추천 상품 영역을 동일 컨테이너
        (#ProductListArea div.item_box)에 노출하므로, 무의미한 keyword=도
        80개 카드를 반환할 수 있다. 0건 판별은 호출자 책임.
        브랜드 정확 매칭이 필요하면 `brand=`를 사용한다.

        한계 2: 렉스몬드 리브랜딩 이후 검색 결과에서 품절 상품을 제외하는
        정책으로 동작 — `is_sold_out`은 거의 False만 반환된다. 정확한
        품절 판정은 `get_product_detail`의 `saleStatus` 필드를 사용.
        """
        params = self._build_search_params(keyword, page, cate=cate, brand=brand)
        async with httpx.AsyncClient(
            timeout=self.TIMEOUT, follow_redirects=True
        ) as cli:
            url = urljoin(self.BASE, self.SEARCH_PATH)
            resp = await cli.get(url, params=params, headers=self.HEADERS)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("div.item_box")
        results: list[dict] = []
        seen_ids: set[str] = set()
        for card in cards:
            parsed = self._parse_card(card)
            if not parsed:
                continue
            pid = parsed.get("site_product_id", "")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            results.append(parsed)
        return results

    @staticmethod
    def _build_search_params(
        keyword: str,
        page: int,
        cate: str = "",
        brand: str = "",
    ) -> dict[str, Any]:
        """검색 URL 파라미터.

        rexmonde 사이트 동작:
        - `keyword=` : 느슨한 키워드 매칭 (관련 카테고리 상품 추천 포함)
        - `brand=`   : 브랜드 정확 필터 (해당 브랜드만)
        - `cate=`    : 카테고리 정확 필터

        우선순위:
        - brand가 있으면 brand 사용 (브랜드 정확 매칭)
        - 그 외 keyword가 5자리 숫자면 cate로 해석 (하위호환)
        - 그 외엔 keyword 검색
        cate는 항상 추가 필터로 적용된다.
        """
        params: dict[str, Any] = {"page": max(1, page)}
        if brand:
            params["brand"] = brand
        elif keyword and keyword.isdigit() and len(keyword) >= 5 and not cate:
            params["cate"] = keyword
            params["sort"] = "POINT"
            return params
        elif keyword:
            params["keyword"] = keyword
        if cate:
            params["cate"] = cate
            params["sort"] = "POINT"
        return params

    # ------------------------------------------------------------------
    # 카드 파싱
    # ------------------------------------------------------------------

    def _parse_card(self, card: Tag) -> dict | None:
        """item_box 카드에서 표준 필드 추출."""
        pid = self._extract_product_id(card)
        if not pid:
            return None

        # 영문 브랜드 + 상품명
        brand_en = self._text(card.select_one("p.item_title span.prName_Brand"))
        season = self._text(card.select_one("p.item_title span.prName_Season"))
        name_en = self._text(card.select_one("p.item_title span.prName_PrName"))
        name_full = " ".join(x for x in [season, name_en] if x).strip()

        # 한글 브랜드 + 상품명 (숨김 영역)
        brand_ko = self._text(
            card.select_one("div.brand_detail_layer span.prName_brand")
        )
        name_ko = self._text(
            card.select_one("div.brand_detail_layer span.prName_PrName")
        )

        # 가격
        original_price = self._parse_price_attr(card.select_one("span.orgin_price"))
        sale_price = self._parse_price_text(card.select_one("span.sale_price"))
        okmall_price = self._parse_price_attr(card.select_one("span.okmall_price"))

        # 할인율 / 배송비
        discount_rate = self._text(card.select_one("div.ic_coupon .icon"))
        delivery_fee = self._parse_price_text(card.select_one("span.delivery_fee em"))

        # 이미지 (대표 + 갤러리)
        main_img = self._normalize_image_url(
            self._attr(card.select_one("img.pImg"), "src")
        )
        gallery = self._parse_gallery(card)

        # 베스트 순위 / 성별 / 카테고리 코드 / 사이즈
        best_rank = self._text(card.select_one("div[name='flag_best']"))
        gender = self._parse_gender(card)
        category_code = self._extract_category_code(card)
        sizes_text = self._text(card.select_one("span.t_size"))
        sizes = [s.strip() for s in sizes_text.split(",") if s.strip()]

        # 품절 — item_box 클래스에 'soldout' 또는 'sold_out' 포함
        classes = " ".join(card.get("class") or []).lower()
        is_sold_out = "soldout" in classes or "sold_out" in classes

        return {
            "site_product_id": pid,
            "name": name_full or name_ko or "",
            "name_ko": name_ko,
            "brand": brand_en or brand_ko,
            "brand_ko": brand_ko,
            "original_price": original_price,
            "sale_price": sale_price or okmall_price or original_price,
            "okmall_price": okmall_price,
            "discount_rate": discount_rate,
            "delivery_fee": delivery_fee,
            "main_image": main_img,
            "gallery_images": gallery,
            "best_rank": best_rank,
            "gender": gender,
            "category_code": category_code,
            "sizes": sizes,
            "is_sold_out": is_sold_out,
            "detail_url": f"{self.BASE}{self.DETAIL_PATH}?no={pid}",
        }

    @staticmethod
    def _extract_product_id(card: Tag) -> str:
        pid = card.get("data-ProductNo") or card.get("data-productno") or ""
        if pid:
            return str(pid)
        link = card.select_one("a[href*='products/view?no=']")
        if link:
            m = re.search(r"no=(\d+)", str(link.get("href") or ""))
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _extract_category_code(card: Tag) -> str:
        link = card.select_one("a[href*='products/view?no=']")
        if not link:
            return ""
        m = re.search(r"cate=(\d+)", str(link.get("href") or ""))
        return m.group(1) if m else ""

    @staticmethod
    def _parse_gender(card: Tag) -> str:
        if card.select_one("em.ic_man"):
            return "M"
        if card.select_one("em.ic_woman"):
            return "F"
        if card.select_one("em.ic_uni"):
            return "U"
        return ""

    def _parse_gallery(self, card: Tag) -> list[str]:
        zoom = card.select_one("span.zoom_ic")
        if not zoom:
            return []
        data = zoom.get("img-data") or ""
        if not data:
            return []
        try:
            urls = json.loads(str(data))
            return [self._normalize_image_url(u) for u in urls if u]
        except (json.JSONDecodeError, TypeError):
            return []

    # ------------------------------------------------------------------
    # 상품 상세
    # ------------------------------------------------------------------

    async def get_product_detail(self, site_product_id: str) -> dict:
        """상품 상세 페이지 JSON-LD + 정보고시 파싱.

        명시적 404일 때만 `__product_not_found__` 마킹 (refresh의 hard delete 방지).
        그 외 파싱 실패는 빈 dict 반환 → 호출자가 재시도 가능.
        """
        async with httpx.AsyncClient(
            timeout=self.TIMEOUT, follow_redirects=True
        ) as cli:
            resp = await cli.get(
                urljoin(self.BASE, self.DETAIL_PATH),
                params={"no": site_product_id},
                headers=self.HEADERS,
            )
            if resp.status_code == 404:
                return {"__product_not_found__": True}
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        all_ld = self._extract_all_jsonld(soup)
        ld = self._find_ld_by_type(all_ld, "Product")

        # Product JSON-LD 없으면 미발견 (사이트가 200+빈 페이지로 응답)
        if not ld:
            return {"__product_not_found__": True}

        price_value, currency, availability = self._parse_aggregate_offer(
            ld.get("offers")
        )
        sale_status = (
            "sold_out"
            if ("OutOfStock" in availability or "SoldOut" in availability)
            else "in_stock"
        )

        # categoryPath 우선순위: BreadcrumbList > Product.category
        category_path = self._build_breadcrumb_path(all_ld) or self._format_category(
            ld.get("category")
        )

        brand_value = ld.get("brand")
        if isinstance(brand_value, dict):
            brand_name = str(brand_value.get("name", ""))
        else:
            brand_name = str(brand_value or "")

        info_notice = self._extract_info_notice(soup)

        return {
            # 표준 응답 키 — refresher가 저장 가능하도록
            "site_product_id": site_product_id,
            "name": str(ld.get("name", "") or ""),
            "brand": brand_name,
            "description": str(ld.get("description", "") or ""),
            "main_image": self._jsonld_first_image(ld.get("image")),
            "gallery_images": self._jsonld_image_list(ld.get("image")),
            "sale_price": price_value,
            "currency": currency or "KRW",
            "availability": availability,
            "saleStatus": sale_status,
            "categoryPath": category_path,
            "detail_url": urljoin(
                self.BASE, f"{self.DETAIL_PATH}?no={site_product_id}"
            ),
            "info_notice": info_notice,
        }

    @staticmethod
    def _extract_all_jsonld(soup: BeautifulSoup) -> list[dict]:
        """페이지의 모든 JSON-LD 객체를 dict 리스트로 반환."""
        out: list[dict] = []
        for tag in soup.select("script[type='application/ld+json']"):
            raw = tag.string or tag.get_text() or ""
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                out.append(data)
            elif isinstance(data, list):
                out.extend(d for d in data if isinstance(d, dict))
        return out

    @staticmethod
    def _find_ld_by_type(lds: list[dict], type_name: str) -> dict:
        for d in lds:
            if d.get("@type") == type_name:
                return d
        return {}

    @staticmethod
    def _build_breadcrumb_path(lds: list[dict]) -> str:
        """BreadcrumbList의 itemListElement → 'A > B > C' 형식 문자열."""
        for d in lds:
            if d.get("@type") != "BreadcrumbList":
                continue
            items = d.get("itemListElement") or []
            names: list[str] = []
            for it in items:
                if isinstance(it, dict):
                    n = it.get("name") or ""
                    if n:
                        names.append(str(n))
            if names:
                return " > ".join(names)
        return ""

    @staticmethod
    def _parse_aggregate_offer(offers: Any) -> tuple[int, str, str]:
        """offers / AggregateOffer에서 (price, currency, availability) 추출.

        availability는 inner offers 종합:
        - 하나라도 InStock → "InStock"
        - 모두 OutOfStock/SoldOut → "OutOfStock"
        - 그 외(혼재 등) → 첫 inner 값
        """
        if not isinstance(offers, dict):
            return 0, "", ""

        def _to_int(v: Any) -> int:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0

        inner_raw = offers.get("offers") or []
        inner_dicts: list[dict] = (
            [d for d in inner_raw if isinstance(d, dict)]
            if isinstance(inner_raw, list)
            else []
        )

        price = _to_int(offers.get("price"))
        if not price and inner_dicts:
            price = _to_int(inner_dicts[0].get("price"))
        if not price:
            price = _to_int(offers.get("lowPrice"))

        currency = str(offers.get("priceCurrency") or "")
        if not currency and inner_dicts:
            currency = str(inner_dicts[0].get("priceCurrency") or "")

        if inner_dicts:
            avails = [str(d.get("availability") or "") for d in inner_dicts]
            non_empty = [a for a in avails if a]
            if any("InStock" in a for a in avails):
                availability = "InStock"
            elif non_empty and all(
                ("OutOfStock" in a or "SoldOut" in a) for a in non_empty
            ):
                availability = "OutOfStock"
            else:
                availability = non_empty[0] if non_empty else ""
        else:
            availability = str(offers.get("availability") or "")

        return price, currency, availability

    @staticmethod
    def _format_category(value: Any) -> str:
        if isinstance(value, list):
            return " > ".join(str(x) for x in value if x)
        return str(value or "")

    @staticmethod
    def _jsonld_first_image(value: Any) -> str:
        if isinstance(value, list) and value:
            return str(value[0])
        return str(value or "")

    @staticmethod
    def _jsonld_image_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value if v]
        return [str(value)] if value else []

    def _extract_info_notice(self, soup: BeautifulSoup) -> dict[str, str]:
        """정보고시(table.goods_info_tbl) 키-값 추출."""
        notice: dict[str, str] = {}
        for table in soup.select("table.goods_info_tbl"):
            for row in table.select("tr"):
                cells = row.select("th, td")
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    val = cells[1].get_text(strip=True)
                    if key:
                        notice[key] = val
        return notice

    # ------------------------------------------------------------------
    # 카테고리 스캔
    # ------------------------------------------------------------------

    async def scan_categories(
        self,
        keyword: str,
        pages: int = 3,
        brand: str = "",
        **kwargs: Any,
    ) -> dict:
        """N페이지 순회하며 카테고리 코드 분포 집계 + 이름 매핑.

        brand가 명시되면 brand= 정확 필터로 스캔 (해당 브랜드 카테고리 분포만).
        그렇지 않으면 keyword= 느슨 매칭 (혼합 브랜드 분포).
        """
        cate_counts: dict[str, int] = {}
        cate_samples: dict[str, str] = {}
        for p in range(1, pages + 1):
            cards = await self.search_products(keyword, page=p, brand=brand)
            for c in cards:
                code = c.get("category_code", "")
                if not code:
                    continue
                cate_counts[code] = cate_counts.get(code, 0) + 1
                if code not in cate_samples:
                    cate_samples[code] = c.get("site_product_id", "")

        sem = asyncio.Semaphore(5)

        async def _resolve(code: str, sample_id: str) -> tuple[str, str]:
            if code in self._category_name_cache:
                return code, self._category_name_cache[code]
            async with sem:
                detail = await self.get_product_detail(sample_id)
            name = detail.get("categoryPath", "") if detail else ""
            self._category_name_cache[code] = name
            return code, name

        tasks = [_resolve(code, sid) for code, sid in cate_samples.items() if sid]
        resolved = dict(await asyncio.gather(*tasks)) if tasks else {}

        categories = []
        for code, cnt in sorted(cate_counts.items(), key=lambda x: x[1], reverse=True):
            path = resolved.get(code, "")
            parts = [p.strip() for p in path.split(" > ") if p.strip()] if path else []
            categories.append(
                {
                    "code": code,
                    "categoryCode": code,
                    "name": path,
                    "path": path,
                    "count": cnt,
                    "category1": parts[0] if len(parts) > 0 else "",
                    "category2": parts[1] if len(parts) > 1 else "",
                    "category3": parts[2] if len(parts) > 2 else "",
                    "category4": parts[3] if len(parts) > 3 else "",
                }
            )
        return {
            "categories": categories,
            "total": sum(cate_counts.values()),
            "groupCount": len(cate_counts),
        }

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _text(node: Tag | None) -> str:
        return node.get_text(strip=True) if node else ""

    @staticmethod
    def _attr(node: Tag | None, key: str) -> str:
        if not node:
            return ""
        v = node.get(key)
        return str(v) if v else ""

    @staticmethod
    def _parse_price_attr(node: Tag | None) -> int:
        if not node:
            return 0
        v = str(node.get("val") or "").strip()
        return int(v) if v.isdigit() else 0

    @staticmethod
    def _parse_price_text(node: Tag | None) -> int:
        if not node:
            return 0
        text = node.get_text(strip=True).replace(",", "").replace("원", "")
        m = re.search(r"\d+", text)
        return int(m.group(0)) if m else 0

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http"):
            return url
        return f"https:{url}"

    # ------------------------------------------------------------------
    # 디스패처 어댑터 — routers/sourcing.py·worker.py 호환
    # ------------------------------------------------------------------

    async def search(
        self,
        keyword: str,
        page: int = 1,
        max_count: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """디스패처 호환 검색 — {products, total} 형태로 반환.

        max_count > 0이면 여러 페이지를 자동 순회하여 최대 max_count건 수집.
        """
        all_products: list[dict] = []
        seen_ids: set[str] = set()
        current_page = max(1, page)
        last_error = ""
        empty_streak = 0
        max_pages = 50
        while True:
            try:
                cards = await self.search_products(keyword, page=current_page, **kwargs)
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[REXMONDE] 검색 p{current_page} 실패: {e}")
                break
            new_items = 0
            for c in cards:
                pid = str(c.get("site_product_id", ""))
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                all_products.append(self._to_dispatcher_item(c))
                new_items += 1
            logger.info(
                f"[REXMONDE] 검색 '{keyword}' p{current_page} → {new_items}건 (누적 {len(all_products)})"
            )
            if new_items == 0:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
            if max_count <= 0:
                break
            if len(all_products) >= max_count:
                all_products = all_products[:max_count]
                break
            current_page += 1
            if current_page > max_pages:
                break
        return {
            "products": all_products,
            "total": len(all_products),
            "last_error": last_error,
        }

    async def get_detail(self, product_id: str) -> dict[str, Any]:
        """디스패처 호환 상세 조회 — get_product_detail + 표준 키 정규화."""
        d = await self.get_product_detail(product_id)
        if not d or d.get("__product_not_found__"):
            return d or {}
        # categoryPath 분해 ("A > B > C > D" → category1/2/3/4)
        path = str(d.get("categoryPath") or "")
        parts = [p.strip() for p in path.split(" > ") if p.strip()] if path else []
        info = d.get("info_notice") or {}
        return {
            **d,
            "images": d.get("gallery_images")
            or ([d.get("main_image")] if d.get("main_image") else []),
            "source_url": d.get("detail_url", ""),
            "category": path,
            "category1": parts[0] if len(parts) > 0 else "",
            "category2": parts[1] if len(parts) > 1 else "",
            "category3": parts[2] if len(parts) > 2 else "",
            "category4": parts[3] if len(parts) > 3 else "",
            "manufacturer": info.get("제조자") or info.get("제조사") or "",
            "origin": info.get("제조국") or info.get("원산지") or "",
            "material": info.get("소재") or info.get("주요 소재") or "",
            "free_shipping": False,
            "shipping_fee": 0,
        }

    @staticmethod
    def _to_dispatcher_item(card: dict) -> dict:
        """검색 카드 → 워커가 기대하는 표준 키로 매핑."""
        gallery = card.get("gallery_images") or []
        main = card.get("main_image") or ""
        images = gallery if gallery else ([main] if main else [])
        return {
            "site_product_id": card.get("site_product_id", ""),
            "name": card.get("name", "") or card.get("name_ko", ""),
            "brand": card.get("brand", "") or card.get("brand_ko", ""),
            "original_price": card.get("original_price", 0) or 0,
            "sale_price": card.get("sale_price", 0) or 0,
            "is_sold_out": card.get("is_sold_out", False),
            "images": images,
            "source_url": card.get("detail_url", ""),
            "style_code": "",
            "category": "",
            "category1": "",
            "category2": "",
            "category3": "",
            "category4": "",
            "free_shipping": (card.get("delivery_fee", 0) or 0) == 0,
            # 원본 필드 보존 (디버그용)
            "_rexmonde_raw": {
                "category_code": card.get("category_code", ""),
                "gender": card.get("gender", ""),
                "sizes": card.get("sizes", []),
                "best_rank": card.get("best_rank", ""),
                "discount_rate": card.get("discount_rate", ""),
            },
        }
