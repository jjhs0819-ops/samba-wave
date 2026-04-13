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


# 패션플러스 카테고리 ID → 이름 매핑
_CATEGORY_MAP: dict[str, str] = {
    "18": "여성의류",
    "13": "남성의류",
    "20": "언더웨어",
    "31": "잡화",
    "16": "스포츠",
    "29": "아웃도어/레저",
    "62": "키즈",
    "61": "리빙가전",
    "25": "뷰티",
    "32": "반려동물",
    "83": "여행레저",
    "67": "식품",
    "68": "주얼리/시계",
    "86": "패션소품/ACC",
    "69": "명품",
}


class FashionPlusClient:
    """패션플러스 소싱 클라이언트."""

    SEARCH_API = "https://www.fashionplus.co.kr/search/goods/fetch"
    DETAIL_URL = "https://www.fashionplus.co.kr/goods/detail"

    async def _fetch_search_meta(self, keyword: str) -> dict[str, Any]:
        """검색 API 호출 후 categories/brands 메타데이터 반환 (상품 목록은 1건만)."""
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            params: dict[str, str] = {
                "searchWord": keyword,
                "page": "1",
                "pageSize": "1",
            }
            try:
                resp = await client.get(self.SEARCH_API, params=params, headers=HEADERS)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.warning(f"[패션플러스] 검색 메타 조회 실패: {e}")
                return {}

    async def discover_brands(self, keyword: str) -> dict[str, Any]:
        """키워드로 브랜드 목록 탐색 — 브랜드 선택 모달용."""
        data = await self._fetch_search_meta(keyword)
        raw_brands = data.get("brands", [])
        brands = []
        for b in raw_brands:
            name = b.get("name", "")
            count = b.get("goodsCountInContext", 0)
            if name and count > 0:
                brands.append({"name": name, "count": count})
        brands.sort(key=lambda x: -x["count"])
        logger.info(f"[패션플러스] 브랜드 탐색 '{keyword}' → {len(brands)}개 브랜드")
        return {"brands": brands, "total": len(brands)}

    async def scan_categories(
        self, keyword: str, selected_brands: list[str] | None = None
    ) -> dict[str, Any]:
        """카테고리 스캔 — 검색 API 응답의 categories 트리를 파싱하여 카테고리별 상품수 반환.

        selected_brands가 있으면 해당 브랜드의 상품수 비율로 카테고리 count를 보정한다.
        (패션플러스 API가 브랜드 필터를 지원하지 않으므로 비율 기반 추정)
        """
        data = await self._fetch_search_meta(keyword)
        if not data:
            return {"categories": [], "total": 0, "groupCount": 0}

        raw_categories = data.get("categories", [])
        total_count = data.get("goodsPaginator", {}).get("totalCount", 0)

        # 선택된 브랜드의 상품수 비율 계산
        brand_ratio = 1.0
        brand_total = total_count
        if selected_brands:
            raw_brands = data.get("brands", [])
            brand_names_set = set(selected_brands)
            brand_sum = sum(
                b.get("goodsCountInContext", 0)
                for b in raw_brands
                if b.get("name", "") in brand_names_set
            )
            if brand_sum > 0 and total_count > 0:
                brand_ratio = brand_sum / total_count
                brand_total = brand_sum

        # 카테고리 트리를 평탄화 — 리프(최하위) 노드 기준으로 경로 생성
        categories: list[dict[str, Any]] = []
        for cat1 in raw_categories:
            c1_name = cat1.get("name", "")
            c1_id = str(cat1.get("id", ""))
            children1 = cat1.get("children", [])
            if not children1:
                # 대분류만 있는 경우
                cnt = cat1.get("goodsCountInContext", 0)
                if cnt > 0:
                    categories.append(
                        {
                            "categoryCode": c1_id,
                            "path": c1_name,
                            "count": cnt,
                            "category1": c1_name,
                            "category2": "",
                            "category3": "",
                        }
                    )
                continue
            for cat2 in children1:
                c2_name = cat2.get("name", "")
                c2_id = str(cat2.get("id", ""))
                children2 = cat2.get("children", [])
                if not children2:
                    # 중분류가 리프
                    cnt = cat2.get("goodsCountInContext", 0)
                    if cnt > 0:
                        categories.append(
                            {
                                "categoryCode": c2_id,
                                "path": f"{c1_name} > {c2_name}",
                                "count": cnt,
                                "category1": c1_name,
                                "category2": c2_name,
                                "category3": "",
                            }
                        )
                    continue
                for cat3 in children2:
                    c3_name = cat3.get("name", "")
                    c3_id = str(cat3.get("id", ""))
                    cnt = cat3.get("goodsCountInContext", 0)
                    if cnt > 0:
                        categories.append(
                            {
                                "categoryCode": c3_id,
                                "path": f"{c1_name} > {c2_name} > {c3_name}",
                                "count": cnt,
                                "category1": c1_name,
                                "category2": c2_name,
                                "category3": c3_name,
                            }
                        )

        # 브랜드 비율 보정 적용
        if brand_ratio < 1.0:
            for cat in categories:
                cat["count"] = max(1, round(cat["count"] * brand_ratio))

        # count=0 제거 후 상품수 내림차순 정렬
        categories = [c for c in categories if c["count"] > 0]
        categories.sort(key=lambda x: -x["count"])
        logger.info(
            f"[패션플러스] 카테고리 스캔 '{keyword}' → {len(categories)}개 카테고리, {brand_total}건"
            + (f" (비율 보정 {brand_ratio:.1%})" if brand_ratio < 1.0 else "")
        )

        return {
            "categories": categories,
            "total": brand_total,
            "groupCount": len(categories),
        }

    async def search(
        self, keyword: str, page: int = 1, max_count: int = 0, **kwargs: Any
    ) -> dict[str, Any]:
        """상품 검색 — /search/goods/fetch JSON API.

        max_count > 0이면 여러 페이지를 자동 순회하여 최대 max_count건 수집.
        """
        all_products: list[dict[str, Any]] = []
        total = 0
        current_page = page
        last_error = ""

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            while True:
                params: dict[str, str] = {
                    "searchWord": keyword,
                    "page": str(current_page),
                    "pageSize": "40",
                }
                # URL 파라미터에서 추가 필터 전달
                for k in (
                    "category1Id",
                    "category2Id",
                    "category3Id",
                    "sort",
                    "minPrice",
                    "maxPrice",
                ):
                    if kwargs.get(k):
                        params[k] = str(kwargs[k])
                # brands 파라미터
                brand_id = kwargs.get("brand_id")
                brand_name = kwargs.get("brand_name")
                if brand_id:
                    params["brands[][id]"] = str(brand_id)
                if brand_name:
                    params["brands[][name]"] = str(brand_name)

                try:
                    resp = await client.get(
                        self.SEARCH_API, params=params, headers=HEADERS
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"[패션플러스] 검색 p{current_page} 실패: {e}")
                    break

                paginator = data.get("goodsPaginator", {})
                items = paginator.get("items", [])
                total = paginator.get("totalCount", len(items))

                if not items:
                    break

                products = [
                    self._map_item(item) for item in items if not item.get("isSoldout")
                ]
                all_products.extend(products)
                logger.info(
                    f"[패션플러스] 검색 '{keyword}' p{current_page} → {len(products)}건 (누적 {len(all_products)}, 전체 {total})"
                )

                if max_count <= 0:
                    break
                if len(all_products) >= max_count:
                    all_products = all_products[:max_count]
                    break
                if len(items) < 40:
                    break
                current_page += 1
                if current_page > 25:
                    break

        return {"products": all_products, "total": total, "last_error": last_error}

    async def get_detail(self, product_id: str) -> dict[str, Any]:
        """상품 상세 조회 — HTML 파싱 + 옵션 API 호출."""
        url = f"{self.DETAIL_URL}/{product_id}"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={**HEADERS, "Accept": "text/html"})
            resp.raise_for_status()
            result = self._parse_detail_html(resp.text, product_id)

            # 옵션/재고 API 호출
            try:
                opt_resp = await client.get(
                    f"{self.DETAIL_URL}/{product_id}/fetch-option-data",
                    headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                )
                if opt_resp.status_code == 200:
                    opt_data = opt_resp.json()
                    result["options"] = self._parse_options(opt_data)
            except Exception as e:
                logger.warning(f"[패션플러스] 옵션 조회 실패 {product_id}: {e}")

            return result

    async def fetch_options(self, product_id: str) -> list[dict[str, Any]]:
        """옵션/재고 단독 조회."""
        url = f"{self.DETAIL_URL}/{product_id}/fetch-option-data"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url, headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"}
            )
            resp.raise_for_status()
            return self._parse_options(resp.json())

    @staticmethod
    def _parse_options(data: list | dict) -> list[dict[str, Any]]:
        """옵션 API 응답 → CollectedProduct options 스키마 변환."""
        options: list[dict[str, Any]] = []
        items = data if isinstance(data, list) else [data]
        for group in items:
            for opt in group.get("options", []):
                stock = opt.get("_stock", 0)
                options.append(
                    {
                        "no": opt.get("_id", 0),
                        "name": opt.get("_name", ""),
                        "price": opt.get("_price", 0),
                        "stock": stock if stock is not None else 999,
                        "isSoldOut": stock == 0 if stock is not None else False,
                        "isBrandDelivery": False,
                        "deliveryType": "GENERAL",
                        "managedCode": "",
                    }
                )
        return options

    @staticmethod
    def _map_item(item: dict[str, Any]) -> dict[str, Any]:
        """API 응답 아이템 → CollectedProduct flat 스키마 변환."""
        brand_info = item.get("brand") or {}
        brand_name = ""
        if isinstance(brand_info, dict):
            brand_name = brand_info.get("name", "")
        elif isinstance(brand_info, str):
            brand_name = brand_info

        thumbnail = item.get("thumbnailUrl", "")
        # 고해상도 이미지로 변환 (RS 파라미터 제거)
        if thumbnail and "?" in thumbnail:
            thumbnail = thumbnail.split("?")[0]
        images = [thumbnail] if thumbnail else []

        product_id = str(item.get("id") or "")
        consumer_price = int(item.get("consumerPrice", 0))
        sale_price = int(item.get("salePrice", 0))
        display_price = int(item.get("displayPrice", 0))
        # displayPrice = 쿠폰 적용가 (최저가)
        best_price = display_price if display_price > 0 else sale_price
        is_free = item.get("isFreeDelivery", False)

        return {
            "site_product_id": product_id,
            "name": item.get("name", ""),
            "original_price": consumer_price or sale_price,
            "sale_price": sale_price or consumer_price,
            "cost": best_price,
            "images": images,
            "brand": brand_name,
            "source_site": "FashionPlus",
            "source_url": f"https://www.fashionplus.co.kr/goods/detail/{product_id}"
            if product_id
            else "",
            "is_sold_out": item.get("isSoldout", False),
            "saleStatus": "sold_out" if item.get("isSoldout") else "in_stock",
            "free_shipping": item.get("isFreeDelivery", False),
            "options": [],
            "category": "",
            "category1": "",
            "category2": "",
            "category3": "",
            "detail_html": "",
            "origin": "",
            "material": "",
            "manufacturer": brand_name,
            "color": "",
        }

    @staticmethod
    def _parse_detail_html(html: str, product_id: str) -> dict[str, Any]:
        """상세 페이지 HTML에서 이미지/고시정보/상세HTML 추출."""
        import json
        import re

        result: dict[str, Any] = {
            "site_product_id": product_id,
            "name": "",
            "brand": "",
            "original_price": 0,
            "sale_price": 0,
            "images": [],
            "options": [],
            "source_site": "FashionPlus",
            "source_url": f"https://www.fashionplus.co.kr/goods/detail/{product_id}",
            "category": "",
            "category1": "",
            "category2": "",
            "category3": "",
            "detail_html": "",
            "detail_images": [],
            "material": "",
            "color": "",
            "manufacturer": "",
            "origin": "",
            "care_instructions": "",
            "quality_guarantee": "",
            "size_info": "",
        }

        # 1) JSON-LD에서 기본 정보
        json_m = re.search(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
        )
        if json_m:
            try:
                data = json.loads(json_m.group(1))
                if isinstance(data, list):
                    data = next(
                        (d for d in data if d.get("@type") == "Product"),
                        data[0] if data else {},
                    )
                if data.get("@type") == "Product":
                    offers = data.get("offers", {})
                    if isinstance(offers, dict):
                        result["original_price"] = int(offers.get("price", 0))
                        sale_p = offers.get("sale_price")
                        result["sale_price"] = (
                            int(sale_p) if sale_p else result["original_price"]
                        )
                    result["name"] = data.get("name", "")
                    brand_info = data.get("brand", {})
                    result["brand"] = (
                        brand_info.get("name", "")
                        if isinstance(brand_info, dict)
                        else str(brand_info)
                    )
                    # SKU → style_code (품번) + seller_id 추출
                    sku = data.get("sku", "")
                    result["style_code"] = sku
                    seller_id = sku.split("_")[0] if "_" in sku else ""
            except (json.JSONDecodeError, ValueError):
                seller_id = ""
        else:
            seller_id = ""
            name_m = re.search(
                r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html
            )
            if name_m:
                result["name"] = name_m.group(1)

        # 2) 상품 이미지 — 동일 seller_id의 product_img만 추출
        #    plgk/plgr/plgl 등 사이즈 접두사가 다른 동일 이미지 중복 제거
        all_product_imgs = re.findall(
            r"(https://img\.fashionplus\.co\.kr/mall/assets/product_img/[^\"\'>\s?]+)",
            html,
        )
        if seller_id:
            imgs = [img for img in all_product_imgs if f"/{seller_id}/" in img]
        else:
            imgs = all_product_imgs[:5]
        # 사이즈 접두사(plgk/plgr/plgl/plgs 등) 제거 후 파일명 기준 중복 제거
        seen_basenames: set[str] = set()
        unique_imgs: list[str] = []
        for img in imgs:
            # .../plgk671652_5008758480.jpg → 671652_5008758480.jpg
            fname = img.rsplit("/", 1)[-1]
            base = re.sub(r"^plg[a-z]", "", fname)
            if base not in seen_basenames:
                seen_basenames.add(base)
                unique_imgs.append(img)
        result["images"] = unique_imgs[:9]

        # 3) 고시정보 추출 (상품 정보 제공고시 테이블)
        notice_match = re.search(
            r"상품\s*정보\s*제공고시(.*?)(?:상품\s*일반정보|반품|$)", html, re.S
        )
        if notice_match:
            rows = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", notice_match.group(1), re.S)
            _strip = lambda s: re.sub(r"<[^>]+>", "", s).strip()
            notice: dict[str, str] = {}
            for i in range(0, len(rows) - 1, 2):
                key = _strip(rows[i])
                val = _strip(rows[i + 1]) if i + 1 < len(rows) else ""
                if key and val and "반품" not in key:
                    notice[key] = val

            # 고시정보 → 필드 매핑
            for k, v in notice.items():
                if v in ("상세설명참조", "상세페이지참조", ""):
                    continue
                kl = k.lower()
                if "소재" in k or "재질" in k:
                    result["material"] = v
                elif k == "색상":
                    result["color"] = v
                elif "제조자" in k or "제조사" in k:
                    result["manufacturer"] = v
                elif "제조국" in k or "원산지" in k:
                    result["origin"] = v
                elif "세탁" in k or "취급" in k or "주의" in k:
                    result["care_instructions"] = v
                elif "품질" in k or "보증" in k:
                    result["quality_guarantee"] = v
                elif "치수" in k or "사이즈" in kl:
                    result["size_info"] = v

        # 4) 상세 HTML — 상품 이미지를 img 태그로 조합
        if result["images"]:
            detail_img_html = "\n".join(
                f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                for img in result["images"]
            )
            result["detail_html"] = detail_img_html
            result["detail_images"] = list(result["images"])

        # 5) 배송비 추출
        fee_match = re.search(r"배송비\s*(\d[\d,]+)\s*원", html)
        result["shipping_fee"] = (
            int(fee_match.group(1).replace(",", "")) if fee_match else 3000
        )

        logger.info(
            f"[패션플러스 상세] {product_id}: 이미지={len(result['images'])}장, 배송비={result['shipping_fee']}, 소재={result['material'][:20]}, 색상={result['color']}, 제조사={result['manufacturer']}"
        )
        return result
