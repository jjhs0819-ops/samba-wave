"""롯데ON 검색 결과 파싱 믹스인.

검색 HTML/JSON에서 상품 목록을 추출하는 파서 메서드를 제공한다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.utils.logger import logger


class SearchParsersMixin:
    """검색 결과 파싱 메서드 믹스인."""

    # 하위 클래스에서 정의되는 상수 (타입 힌트용)
    PRODUCT_URL: str

    def _convert_qapi_items(
        self, items: list[dict[str, Any]], now_iso: str
    ) -> list[dict[str, Any]]:
        """qapi itemList를 표준 상품 dict로 변환."""
        from urllib.parse import unquote

        products: list[dict[str, Any]] = []
        for item in items:
            inner = item.get("data", {})
            spd_no = inner.get("spd_no", "")
            if not spd_no:
                # key 형식: "LE1219458697_1316330136" → spd_no 추출
                key = item.get("key", "")
                spd_no = key.split("_")[0] if "_" in key else key

            if not spd_no:
                continue

            # 가격 추출
            price_map: dict[str, int] = {}
            for p in item.get("priceInfo", []):
                price_map[p.get("type", "")] = p.get("num", 0)

            original_price = price_map.get("original", 0)
            final_price = price_map.get("final", 0)

            # 최대혜택가 = 프로모션 판매가 (카드할인은 상한금액이 있어 API로 정확 계산 불가)
            # 실제 혜택가는 확장앱 DOM 파싱으로 수집
            best_benefit_price = final_price

            # 이미지
            thumbnail = item.get("productImage", "")

            # 상품명 (qapi는 디코딩된 텍스트, inner.name은 URL인코딩)
            name = item.get("productName", "")
            if not name and inner.get("name"):
                name = unquote(inner["name"])

            # 브랜드
            brand = item.get("brandName", "")
            if not brand and inner.get("brand"):
                brand = unquote(inner["brand"])

            # BC 카테고리 코드 (scatNo) — 검색 단계에서 바로 카테고리 매핑 가능
            scat_no = inner.get("category", "")

            products.append(
                {
                    "siteProductId": spd_no,
                    "site_product_id": spd_no,
                    "name": name,
                    "brand": brand,
                    "salePrice": final_price,
                    "sale_price": final_price,
                    "originalPrice": original_price,
                    "original_price": original_price,
                    "thumbnailImageUrl": thumbnail,
                    "thumbnail_image_url": thumbnail,
                    "sourceUrl": f"{self.PRODUCT_URL}/{inner.get('pd_no', spd_no)}",
                    "source_url": f"{self.PRODUCT_URL}/{inner.get('pd_no', spd_no)}",
                    "spdNo": spd_no,
                    "scatNo": scat_no,
                    "scat_no": scat_no,
                    "bestBenefitPrice": best_benefit_price,
                    "best_benefit_price": best_benefit_price,
                    "collectedAt": now_iso,
                    "collected_at": now_iso,
                }
            )
        return products

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
