"""패션플러스 소싱 클라이언트 - 상품 검색/상세 조회.

사이트: https://www.fashionplus.co.kr
실제 동작 확인된 API: /search/goods/fetch (JSON 응답)
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from backend.domain.samba.proxy.musinsa import RateLimitError
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


def _norm_brand(s: str) -> str:
    """브랜드명 비교용 정규화 — 모든 공백 제거 + 소문자.

    패플은 같은 브랜드를 "코오롱 스포츠"(공백 포함)로 주고, 우리 검색그룹의
    source_brand_name 은 "코오롱스포츠"(공백 없음)인 경우가 많다. 공백만 다른
    동일 브랜드를 오필터하지 않도록 공백을 제거하고 비교한다.
    """
    return "".join((s or "").split()).lower()


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

    # 수집 시 페이지 간 딜레이(초) — 차단 예방. 안전 우선(느려도 안 짤리게).
    SEARCH_PAGE_DELAY = 1.0

    def __init__(self, *, proxy_url: str | None = None) -> None:
        # 오토튠 IP 로테이션용 프록시 (무신사와 동일 패턴). None이면 메인 IP.
        self.proxy_url = proxy_url

    def _client_kwargs(self) -> dict[str, Any]:
        """httpx.AsyncClient 생성 인자 — 프록시 있으면 주입."""
        kw: dict[str, Any] = {"timeout": 15, "follow_redirects": True}
        if self.proxy_url:
            kw["proxy"] = self.proxy_url
        return kw

    async def _fetch_search_meta(self, keyword: str) -> dict[str, Any]:
        """검색 API 호출 후 categories/brands 메타데이터 반환 (상품 목록은 1건만)."""
        async with httpx.AsyncClient(**self._client_kwargs()) as client:
            params: dict[str, str] = {
                "searchWord": keyword,
                "page": "1",
                "pageSize": "1",
            }
            try:
                resp = await client.get(self.SEARCH_API, params=params, headers=HEADERS)
                # 429/403 차단 감지 (무신사와 동일 패턴)
                if resp.status_code in (429, 403):
                    retry_after = int(resp.headers.get("Retry-After", "30"))
                    raise RateLimitError(resp.status_code, retry_after)
                resp.raise_for_status()
                return resp.json()
            except RateLimitError:
                raise
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
            # id 필수 — 서버측 브랜드 필터(brands=<id>)에 사용된다.
            # 문자열로 반환: 프론트 brand_ids(list[str]) 검증 통과 + URL 파라미터 일관성.
            bid = b.get("id")
            if name and count > 0:
                brands.append(
                    {
                        "id": str(bid) if bid is not None else None,
                        "name": name,
                        "count": count,
                    }
                )
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
                            "category1Id": c1_id,
                            "category2Id": "",
                            "category3Id": "",
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
                                "category1Id": c1_id,
                                "category2Id": c2_id,
                                "category3Id": "",
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
                                "category1Id": c1_id,
                                "category2Id": c2_id,
                                "category3Id": c3_id,
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

        async with httpx.AsyncClient(**self._client_kwargs()) as client:
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
                # 브랜드 필터 — 패플은 `brands=<id>` 단일 파라미터만 서버측 필터됨.
                # (brands[][id]/brands[][name]은 무시되어 키워드 전체가 반환됨 → 잡브랜드 혼입)
                brand_id = kwargs.get("brand_id")
                brand_name = kwargs.get("brand_name")
                if brand_id:
                    params["brands"] = str(brand_id)
                elif brand_name:
                    # id 없을 때 폴백 — 서버 필터는 안 되고 아래 클라이언트 필터로 거른다
                    params["brands[][name]"] = str(brand_name)

                try:
                    resp = await client.get(
                        self.SEARCH_API, params=params, headers=HEADERS
                    )
                    # 429/403 차단 감지 — 상위로 전파(무신사와 동일 패턴)
                    if resp.status_code in (429, 403):
                        retry_after = int(resp.headers.get("Retry-After", "30"))
                        raise RateLimitError(resp.status_code, retry_after)
                    resp.raise_for_status()
                    data = resp.json()
                except RateLimitError:
                    raise
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"[패션플러스] 검색 p{current_page} 실패: {e}")
                    break

                paginator = data.get("goodsPaginator", {})
                items = paginator.get("items", [])
                total = paginator.get("totalCount", len(items))

                if not items:
                    break

                # brand_id로 서버측 필터된 경우 클라 필터 불필요. id 없이 name만 있으면
                # 공백 정규화 후 정확 일치로 타판매처/타브랜드 혼입 차단.
                # (패플 키워드검색은 "케이티알파쇼핑" 같은 입점 판매처 상품을 brand 로
                #  섞어 반환 — brand_id 누락 그룹에서 source_brand_name 폴백으로 거른다.)
                target_brand = "" if brand_id else _norm_brand(brand_name)
                filtered_items = []
                for item in items:
                    if item.get("isSoldout"):
                        continue
                    if target_brand:
                        item_brand = item.get("brand") or {}
                        item_brand_name = (
                            item_brand.get("name", "")
                            if isinstance(item_brand, dict)
                            else str(item_brand)
                        )
                        if _norm_brand(item_brand_name) != target_brand:
                            continue
                    filtered_items.append(item)
                products = [self._map_item(item) for item in filtered_items]
                all_products.extend(products)
                logger.info(
                    f"[패션플러스] 검색 '{keyword}' p{current_page} → {len(products)}건 (누적 {len(all_products)}, 전체 {total})"
                    + (f" [브랜드필터: {brand_name}]" if target_brand else "")
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
                # 다음 페이지 요청 전 딜레이 — 차단 예방 (수집 안전 우선)
                await asyncio.sleep(self.SEARCH_PAGE_DELAY)

        return {"products": all_products, "total": total, "last_error": last_error}

    async def get_detail(self, product_id: str) -> dict[str, Any]:
        """상품 상세 조회 — HTML 파싱 + 옵션 API 호출."""
        url = f"{self.DETAIL_URL}/{product_id}"
        async with httpx.AsyncClient(**self._client_kwargs()) as client:
            resp = await client.get(url, headers={**HEADERS, "Accept": "text/html"})
            # 429/403 차단 감지 (무신사와 동일 패턴)
            if resp.status_code in (429, 403):
                retry_after = int(resp.headers.get("Retry-After", "30"))
                raise RateLimitError(resp.status_code, retry_after)
            resp.raise_for_status()
            result = self._parse_detail_html(resp.text, product_id)

            # 옵션/재고 API 호출
            # _options_fetched: 옵션 fetch가 실제로 성공했는지 표시.
            # 패션플러스는 품절 옵션을 응답에서 제거하므로 "빈 옵션=완전품절"을
            # fetch 실패(차단/네트워크)와 구분하려면 이 플래그가 필요하다.
            result["_options_fetched"] = False
            try:
                opt_resp = await client.get(
                    f"{self.DETAIL_URL}/{product_id}/fetch-option-data",
                    headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                )
                if opt_resp.status_code in (429, 403):
                    retry_after = int(opt_resp.headers.get("Retry-After", "30"))
                    raise RateLimitError(opt_resp.status_code, retry_after)
                if opt_resp.status_code == 200:
                    opt_data = opt_resp.json()
                    result["options"] = self._parse_options(opt_data)
                    result["_options_fetched"] = True
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning(f"[패션플러스] 옵션 조회 실패 {product_id}: {e}")

            # 빈 슬롯(placeholder, ~1245B) 제외 — 같은 품번 후보 중 실제 이미지만 남긴다.
            # plgk/plgl/plgr 등이 실제 추가컷이면 유지, 빈 슬롯이면 제거.
            _imgs = result.get("images") or []
            if len(_imgs) > 1:

                async def _img_size(u: str) -> int:
                    try:
                        h = await client.head(u, headers=HEADERS)
                        return int(h.headers.get("content-length", 0))
                    except Exception:
                        return 0

                _sizes = await asyncio.gather(*[_img_size(u) for u in _imgs])
                _real = [u for u, sz in zip(_imgs, _sizes) if sz > 2000]
                if _real:
                    result["images"] = _real[:9]
                    result["detail_images"] = list(_real[:9])
                    result["detail_html"] = "\n".join(
                        f'<div style="text-align:center;"><img src="{img}" '
                        f'style="max-width:860px;width:100%;" /></div>'
                        for img in _real[:9]
                    )

            return result

    async def fetch_options(self, product_id: str) -> list[dict[str, Any]]:
        """옵션/재고 단독 조회."""
        url = f"{self.DETAIL_URL}/{product_id}/fetch-option-data"
        async with httpx.AsyncClient(**self._client_kwargs()) as client:
            resp = await client.get(
                url, headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"}
            )
            # 429/403 차단 감지 (무신사와 동일 패턴)
            if resp.status_code in (429, 403):
                retry_after = int(resp.headers.get("Retry-After", "30"))
                raise RateLimitError(resp.status_code, retry_after)
            resp.raise_for_status()
            return self._parse_options(resp.json())

    @staticmethod
    def _parse_options(data: list | dict) -> list[dict[str, Any]]:
        """옵션 API 응답 → CollectedProduct options 스키마 변환."""
        options: list[dict[str, Any]] = []
        items = data if isinstance(data, list) else [data]
        for group in items:
            if not isinstance(group, dict):
                continue
            raw_opts = group.get("options", [])
            # API가 {"sub": [...]} 형태로 응답하는 경우 처리
            if isinstance(raw_opts, dict):
                raw_opts = raw_opts.get("sub", [])
            for opt in raw_opts:
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
            "is_sold_out": False,
            "saleStatus": "in_stock",
        }

        # 0) 제품 레벨 품절 플래그 — 전체 품절 감지용.
        #    (일부 사이즈만 품절이면 이 값은 False라 옵션 API 누락으로 별도 판정)
        m_sold = re.search(r"isSoldout['\"\s:=]+['\"]?(true|false)", html, re.I)
        if m_sold and m_sold.group(1).lower() == "true":
            result["is_sold_out"] = True
            result["saleStatus"] = "sold_out"

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
                    # SKU → seller_id + 품번(style_no) 추출.
                    # 이미지 파일명이 plg{seller_id}_{품번}.jpg 형태라, seller_id만으로
                    # 거르면 같은 판매자의 추천/연관 상품 이미지가 혼입된다 → 품번으로 필터.
                    sku = data.get("sku", "")
                    seller_id = sku.split("_")[0] if "_" in sku else ""
                    style_no = sku.split("_", 1)[1] if "_" in sku else ""
            except (json.JSONDecodeError, ValueError):
                seller_id = ""
                style_no = ""
        else:
            seller_id = ""
            style_no = ""
            name_m = re.search(
                r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html
            )
            if name_m:
                result["name"] = name_m.group(1)

        # 2) 상품 이미지 — 이 상품 품번(style_no)이 든 product_img만 추출.
        #    seller_id만으로 거르면 같은 판매자의 추천/연관 상품 이미지가 혼입되므로
        #    품번으로 필터한다. 품번 명명 규칙이 다른 상품 대비 seller_id fallback 유지.
        #    plgk/plgr/plgl 등 사이즈 접두사가 다른 동일 이미지는 아래에서 중복 제거.
        all_product_imgs = re.findall(
            r"(https://img\.fashionplus\.co\.kr/mall/assets/product_img/[^\"\'>\s?]+)",
            html,
        )
        if style_no:
            imgs = [img for img in all_product_imgs if style_no in img]
            # 품번이 이미지 파일명에 없는 상품(명명 규칙 상이) → seller_id로 폴백
            if not imgs and seller_id:
                imgs = [img for img in all_product_imgs if f"/{seller_id}/" in img]
        elif seller_id:
            imgs = [img for img in all_product_imgs if f"/{seller_id}/" in img]
        else:
            imgs = all_product_imgs[:5]
        # 같은 품번의 접두사 변형(plg/plgk/plgl/plgr…)은 추가컷일 수도, 빈 슬롯일 수도
        # 있다. 여기서 접두사로 합치면 실제 추가컷까지 사라지므로(셀러마다 다름),
        # 완전 동일 URL만 제거해 후보를 모두 남기고, get_detail()에서 실제 크기로
        # 빈 슬롯(placeholder)을 걸러낸다.
        seen: set[str] = set()
        unique_imgs: list[str] = []
        for img in imgs:
            if img not in seen:
                seen.add(img)
                unique_imgs.append(img)
        result["images"] = unique_imgs[:15]

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
                elif "품번" in k or "모델번호" in k or "모델명" in k or k == "모델":
                    # 고시정보 테이블에 품번/모델 항목이 있으면 우선 사용
                    result["style_code"] = v

        # 고시정보에서 품번을 못 찾은 경우 → 상품명 끝 토큰에서 추출 (폴백)
        # 예: "내셔널지오그래픽 공용 캠핑 신학기 버디백팩 N261ABG040" → N261ABG040
        if not result.get("style_code") and result.get("name"):
            name_model_m = re.search(
                r"(?<!\w)([A-Z][A-Z0-9\-]{4,19})(?:\s|$)", result["name"]
            )
            if name_model_m:
                result["style_code"] = name_model_m.group(1)

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
