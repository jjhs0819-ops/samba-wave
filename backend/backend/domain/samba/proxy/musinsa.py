"""무신사 API 클라이언트 - httpx 기반.

proxy-server.mjs의 무신사 관련 로직을 Python으로 포팅.
상품 상세, 옵션/재고, 고시정보, 쿠폰, 혜택가, 검색 API를 지원한다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from backend.utils.logger import logger


class RateLimitError(Exception):
    """소싱처 차단 감지 (429/403)."""
    def __init__(self, status: int, retry_after: int = 0):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"HTTP {status} (retry_after={retry_after})")


# 무신사 API 필드 매핑 — 구조 변경 시 여기만 수정
MUSINSA_FIELDS = {
    "normal_price": ["goodsPrice.normalPrice"],
    "sale_price": ["goodsPrice.immediateDiscountedPrice", "goodsPrice.salePrice"],
    "member_discount_rate": [
        "goodsPrice.memberDiscountRate",
        "goodsPrice.gradeDiscountRate",
        "goodsPrice.memberGradeDiscountRate",
        "goodsPrice.gradeRate",
    ],
    "coupon_price": ["goodsPrice.couponPrice"],
    "max_benefit_price": [
        "goodsPrice.maxBenefitPrice",
        "goodsPrice.benefitSalePrice",
        "goodsPrice.bestBenefitPrice",
    ],
    "is_sold_out": ["isSoldOut", "goodsPrice.isSoldOut", "isOutOfStock"],
    "product_name": ["goodsNm"],
    "product_name_en": ["goodsNmEng"],
    "brand_name": ["brandInfo.brandName", "brand"],
    "thumbnail": ["thumbnailImageUrl"],
    "discount_rate": ["goodsPrice.discountRate"],
    "is_sale": ["goodsPrice.isSale"],
    "grade_discount_rate": ["goodsPrice.memberDiscountRate"],
    "sale_reserve_ymdt": ["goodsPrice.saleReserveYmdt", "saleReserveYmdt"],
}


def _resolve_field(data: dict, paths: list[str], default=None):
    """경로 목록에서 첫 번째 존재하는 값 반환 (fallback 체인)."""
    for path in paths:
        value = data
        for key in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
            if value is None:
                break
        if value is not None:
            return value
    return default


class MusinsaClient:
    """무신사 API 클라이언트 (상품 상세, 검색, 로그인 상태 확인)."""

    BASE_DETAIL = "https://goods-detail.musinsa.com/api2/goods"
    BASE_SEARCH = "https://api.musinsa.com/api2/dp/v1/plp/goods"
    BASE_COUPON = "https://api.musinsa.com/api2/coupon/coupons/getUsableCouponsByGoodsNo"
    BASE_MEMBER = "https://api.musinsa.com/api2/member/v1/me"

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.musinsa.com/",
        "Origin": "https://www.musinsa.com",
    }

    def __init__(self, cookie: str = "") -> None:
        self.cookie = cookie

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        h = {**self.HEADERS}
        if self.cookie:
            h["Cookie"] = self.cookie
        if extra:
            h.update(extra)
        return h

    @staticmethod
    def _to_image_url(path: str) -> str:
        if not path:
            return ""
        if path.startswith("http"):
            return path
        if path.startswith("//"):
            return f"https:{path}"
        return f"https://image.msscdn.net{path}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_goods_detail(self, goods_no: str) -> dict[str, Any]:
        """상품 상세 조회 - 상세 + 옵션 + 재고 + 고시정보 + 쿠폰 + 혜택가.

        proxy-server.mjs ``fetchMusinsaProduct()`` 전체 로직 포팅.
        """
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            # 1) 상품 상세 API
            detail_resp = await client.get(
                f"{self.BASE_DETAIL}/{goods_no}",
                headers=self._headers(),
            )
            # 429/403 차단 감지
            if detail_resp.status_code in (429, 403):
                retry_after = int(detail_resp.headers.get("Retry-After", "30"))
                raise RateLimitError(detail_resp.status_code, retry_after)
            detail_resp.raise_for_status()
            detail_json = detail_resp.json()
            meta = detail_json.get("meta", {})
            if meta.get("result") != "SUCCESS" or not detail_json.get("data"):
                raise ValueError("상품 데이터 없음")

            d = detail_json["data"]
            gp = d.get("goodsPrice") or {}
            cat = d.get("category") or {}  # None 방지

            # 2) 옵션 API + 재고 API
            options, option_value_no_map = await self._fetch_options(
                client, goods_no, gp
            )

            # 3) 상품고시정보 API
            essential = await self._fetch_essential(client, goods_no)

            # 카테고리
            category_levels = [
                cat.get(f"categoryDepth{i}Name") for i in range(1, 5)
            ]
            category_levels = [c for c in category_levels if c]

            # 상세페이지 이미지 추출
            desc_html = d.get("goodsContents", "")
            detail_images = self._extract_detail_images(desc_html)

            # 이미지: 썸네일 + 상품이미지 최대 8장
            all_images = [self._to_image_url(d.get("thumbnailImageUrl", ""))]
            for img in d.get("goodsImages", []):
                all_images.append(
                    self._to_image_url(img.get("imageUrl") or img.get("url", ""))
                )
            all_images = [i for i in all_images if i]
            unique_images = list(dict.fromkeys(all_images))[:9]

            # 소재 정보
            materials = (d.get("goodsMaterial") or {}).get("materials", [])
            material_str = ", ".join(
                (
                    f"{m.get('materialName') or m.get('name', '')} "
                    f"{m.get('rate') or m.get('ratio', '')}%"
                ).strip()
                if (m.get("rate") or m.get("ratio"))
                else (m.get("materialName") or m.get("name", ""))
                for m in materials
                if (m.get("materialName") or m.get("name"))
            )

            # 시즌 정보
            season_year = d.get("seasonYear", "")
            if season_year == "0000":
                season_year = ""
            season_code = d.get("season", "")
            if season_code == "0":
                season_code = ""
            season = " ".join(filter(None, [season_year, season_code]))

            # 4) 가격 계산
            normal_p = gp.get("normalPrice", 0) or 0
            raw_sale = gp.get("immediateDiscountedPrice") or gp.get("salePrice", 0) or 0
            s_price = (
                raw_sale
                if (raw_sale > 0 and (normal_p == 0 or raw_sale <= normal_p))
                else (normal_p or raw_sale)
            )
            member_rate = (
                gp.get("memberDiscountRate")
                or gp.get("gradeDiscountRate")
                or gp.get("memberGradeDiscountRate")
                or gp.get("gradeRate")
                or 0
            )

            # 최대혜택가 = 할인가 - 쿠폰 - 등급 - 적립금 - 선할인
            # 1단계: 쿠폰 할인
            coupon_price_raw = gp.get("couponPrice", 0) or 0
            api_best_benefit = (
                gp.get("maxBenefitPrice")
                or gp.get("benefitSalePrice")
                or gp.get("bestBenefitPrice")
                or 0
            )
            best_coupon_discount = 0
            if 0 < coupon_price_raw < s_price:
                best_coupon_discount = s_price - coupon_price_raw
            if api_best_benefit and 0 < api_best_benefit < s_price:
                api_discount = s_price - api_best_benefit
                if api_discount > best_coupon_discount:
                    best_coupon_discount = api_discount
            best_coupon_discount = await self._fetch_coupons(
                client, goods_no, d, s_price, best_coupon_discount
            )
            coupon_applied_price = s_price - best_coupon_discount if best_coupon_discount > 0 else s_price

            # 2단계: 등급할인 (쿠폰적용가 기준, 10원 절사)
            grade_discount_rate = gp.get("memberDiscountRate", 0) or 0
            grade_discount = int(coupon_applied_price * grade_discount_rate / 100 / 10) * 10

            # 3단계: 적립금 사용 (쿠폰적용가 - 등급할인 기준, 10원 절사)
            is_point_restricted = d.get("isRestictedUsePoint") is True
            raw_point_rate = d.get("maxUsePointRate", 0) or 0
            point_rate_pct = raw_point_rate * 100 if 0 < raw_point_rate < 1 else raw_point_rate
            point_base = coupon_applied_price - grade_discount
            point_usage = 0
            if not is_point_restricted and point_rate_pct > 0:
                point_usage = int(point_base * point_rate_pct / 100 / 10) * 10  # 10원 절사

            # 4단계: 적립 선할인 (isPrePoint=True만, 잔액 기준 × 등급율, 10원 절사)
            is_pre_point = d.get("isPrePoint") is True
            remaining = s_price - best_coupon_discount - grade_discount - point_usage
            pre_discount = int(remaining * grade_discount_rate / 100 / 10) * 10 if is_pre_point else 0

            best_benefit_price = remaining - pre_discount

            logger.info(
                f"[무신사 혜택가] {goods_no}: "
                f"할인가={s_price}, 쿠폰=-{best_coupon_discount}({coupon_applied_price}), "
                f"등급({grade_discount_rate}%)=-{grade_discount}, "
                f"적립금({point_rate_pct}%)=-{point_usage}(base={point_base}), "
                f"선할인({grade_discount_rate}%,base={remaining + pre_discount})=-{pre_discount}, "
                f"혜택가={best_benefit_price}"
            )

            now_iso = datetime.now(tz=timezone.utc).isoformat()

            # 판매 상태 관련 필드 디버그 로그
            logger.info(
                f"[무신사 상태 디버그] {goods_no}: "
                f"isSale={gp.get('isSale')!r}, "
                f"isSoldOut_gp={gp.get('isSoldOut')!r}, "
                f"isSoldOut_d={d.get('isSoldOut')!r}, "
                f"isOutOfStock={d.get('isOutOfStock')!r}, "
                f"canBuy={d.get('canBuy')!r}, "
                f"goodsTypeCode={d.get('goodsTypeCode')!r}, "
                f"saleState={gp.get('saleState') or d.get('saleState')!r}, "
                f"timeSale={d.get('timeSale')!r}, "
                f"isTimeSale={d.get('isTimeSale')!r}, "
                f"saleReserveYmdt={gp.get('saleReserveYmdt') or d.get('saleReserveYmdt')!r}"
            )

            brand_info = d.get("brandInfo") or {}
            return {
                "id": f"col_musinsa_{goods_no}_{int(datetime.now(tz=timezone.utc).timestamp() * 1000)}",
                "sourceSite": "MUSINSA",
                "siteProductId": str(d.get("goodsNo") or goods_no),
                "sourceUrl": f"https://www.musinsa.com/products/{goods_no}",
                "searchFilterId": None,
                "name": d.get("goodsNm", ""),
                "nameEn": d.get("goodsNmEng", ""),
                "nameJa": "",
                "brand": brand_info.get("brandName") or d.get("brand", ""),
                "brandCode": d.get("brand", ""),
                "category": " > ".join(category_levels),
                "category1": cat.get("categoryDepth1Name", ""),
                "category2": cat.get("categoryDepth2Name", ""),
                "category3": cat.get("categoryDepth3Name", ""),
                "category4": cat.get("categoryDepth4Name", ""),
                "categoryCode": (
                    cat.get("categoryDepth4Code")
                    or cat.get("categoryDepth3Code")
                    or cat.get("categoryDepth2Code")
                    or cat.get("categoryDepth1Code")
                    or ""
                ),
                "images": unique_images,
                "detailImages": detail_images,
                "detailHtml": desc_html,
                "options": options,
                "originalPrice": gp.get("normalPrice") or raw_sale or 0,
                "salePrice": s_price,
                "couponPrice": coupon_applied_price,
                "bestBenefitPrice": best_benefit_price,
                "memberDiscountRate": member_rate,
                "isLoggedIn": bool(self.cookie),
                "discountRate": gp.get("discountRate", 0),
                "origin": essential.get("origin", ""),
                "material": essential.get("material") or material_str,
                "manufacturer": essential.get("manufacturer", ""),
                "color": essential.get("color", ""),
                "sizeInfo": essential.get("size", ""),
                "careInstructions": essential.get("careInstructions", ""),
                "qualityGuarantee": essential.get("qualityGuarantee", ""),
                "brandNation": brand_info.get("brandNationName", ""),
                "season": season,
                "styleCode": d.get("styleNo", ""),
                "kcCert": "",
                "tags": [],
                "status": "collected",
                "appliedPolicyId": None,
                "marketPrices": {},
                "updateEnabled": True,
                "priceUpdateEnabled": True,
                "stockUpdateEnabled": True,
                "marketTransmitEnabled": True,
                "registeredAccounts": [],
                "sex": d.get("sex", []),
                "storeCodes": d.get("storeCodes", []),
                "isOutlet": d.get("isOutlet", False),
                # 부티끄 판별: goodsTypeCode 또는 saleType
                "isBoutique": (
                    str(d.get("goodsTypeCode", "")).upper() == "BOUTIQUE"
                    or "부티크" in str(d.get("goodsTypeName", ""))
                    or "부티끄" in str(d.get("goodsTypeName", ""))
                    or any(
                        str(sc).upper() in ("BOUTIQUE", "BTQSHOP")
                        for sc in (d.get("storeCodes") or [])
                    )
                ),
                # 품절 판단: isSale=False(판매안함/판매예정) + soldOut + 모든옵션품절
                "isOutOfStock": bool(
                    d.get("isSoldOut")
                    or (d.get("goodsPrice") or {}).get("isSoldOut")
                    or d.get("isOutOfStock", False)
                    or (bool(options) and all(opt.get("isSoldOut", False) for opt in options))
                ),
                "isSale": gp.get("isSale", False),
                # 판매 상태: sold_out(품절) → preorder(판매예정) → in_stock 순서로 판단
                # sold_out을 먼저 체크해야 preorder 상태였다가 품절된 경우를 올바르게 처리
                "saleStatus": (
                    "sold_out"
                    if bool(
                        d.get("isSoldOut")
                        or (d.get("goodsPrice") or {}).get("isSoldOut")
                        or d.get("isOutOfStock", False)
                        or (bool(options) and all(opt.get("isSoldOut", False) for opt in options))
                    )
                    else "preorder"
                    if (
                        # 판매 예약 날짜가 설정된 경우 (판매예정)
                        bool(gp.get("saleReserveYmdt") or d.get("saleReserveYmdt"))
                        # 예약/사전주문 배송 타입 옵션이 있는 경우
                        or bool(
                            options and any(
                                str(opt.get("deliveryType", "")).upper()
                                in ("RESERVATION", "PREORDER", "RESERVE", "SCHEDULED")
                                for opt in options
                            )
                        )
                        # isSale=False 조건 제거 — 무배당발 상품도 isSale=False일 수 있음
                    )
                    else "in_stock"
                ),
                "collectedAt": now_iso,
                "updatedAt": now_iso,
            }

    async def search_products(
        self,
        keyword: str,
        page: int = 1,
        size: int = 30,
        sort: str = "POPULAR",
        category: str = "",
    ) -> dict[str, Any]:
        """상품 검색 (API 방식) - proxy-server.mjs /api/musinsa/search-api 포팅."""
        size = min(size, 200)
        params: dict[str, str] = {
            "caller": "SEARCH",
            "keyword": keyword,
            "page": str(page),
            "size": str(size),
            "sort": sort,
            "gf": "A",
        }
        if category:
            params["category"] = category

        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                self.BASE_SEARCH,
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            api_data = resp.json()

            meta = api_data.get("meta", {})
            if meta.get("result") != "SUCCESS":
                raise ValueError("무신사 API 결과 실패")

            item_list = (api_data.get("data") or {}).get("list", [])
            pagination = (api_data.get("data") or {}).get("pagination", {})
            now_iso = datetime.now(tz=timezone.utc).isoformat()

            products = []
            for item in item_list:
                goods_no = item.get("goodsNo", "")
                products.append(
                    {
                        "id": f"col_musinsa_{goods_no}_{int(datetime.now(tz=timezone.utc).timestamp() * 1000)}",
                        "sourceSite": "MUSINSA",
                        "siteProductId": str(goods_no),
                        "sourceUrl": (
                            item.get("goodsLinkUrl")
                            or f"https://www.musinsa.com/products/{goods_no}"
                        ),
                        "searchFilterId": None,
                        "name": item.get("goodsName", ""),
                        "nameEn": "",
                        "nameJa": "",
                        "brand": item.get("brandName") or item.get("brand", ""),
                        "brandCode": item.get("brand", ""),
                        "category": "",
                        "images": [item["thumbnail"]] if item.get("thumbnail") else [],
                        "detailImages": [],
                        "detailHtml": "",
                        "options": [],
                        "originalPrice": item.get("normalPrice") or item.get("price", 0),
                        "salePrice": item.get("price") or item.get("normalPrice", 0),
                        "discountRate": item.get("saleRate", 0),
                        "origin": "",
                        "material": "",
                        "manufacturer": "",
                        "season": "",
                        "styleCode": "",
                        "kcCert": "",
                        "tags": [],
                        "status": "collected",
                        "isSoldOut": item.get("isSoldOut", False),
                        "appliedPolicyId": None,
                        "marketPrices": {},
                        "updateEnabled": True,
                        "priceUpdateEnabled": True,
                        "stockUpdateEnabled": True,
                        "marketTransmitEnabled": True,
                        "registeredAccounts": [],
                        "collectedAt": now_iso,
                        "updatedAt": now_iso,
                    }
                )

            return {
                "success": True,
                "count": len(products),
                "totalCount": pagination.get("totalCount", 0),
                "totalPages": pagination.get("totalPages", 0),
                "page": pagination.get("page", page),
                "data": products,
            }

    async def search_by_url(self, url: str) -> dict[str, Any]:
        """URL 기반 검색/리다이렉트 처리 - proxy-server.mjs /api/musinsa/search 포팅."""
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            # onelink.me 단축 URL
            if "musinsa.onelink.me" in url:
                resp = await client.get(
                    url, headers={"User-Agent": self.HEADERS["User-Agent"]}
                )
                final_url = str(resp.url)
                match = re.search(r"/(?:app/)?(?:goods|products)/(\d{4,8})", final_url)
                if match:
                    return {
                        "success": True,
                        "count": 1,
                        "goodsNos": [match.group(1)],
                        "source": "redirect",
                    }

            # URL에서 키워드 추출 시도
            try:
                from urllib.parse import parse_qs, urlparse

                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                kw = (
                    (qs.get("keyword") or qs.get("q") or qs.get("query") or [""])[0]
                )
                if kw:
                    params = {
                        "caller": "SEARCH",
                        "keyword": kw,
                        "page": "1",
                        "size": "50",
                        "sort": "POPULAR",
                        "gf": "A",
                    }
                    api_resp = await client.get(
                        self.BASE_SEARCH,
                        params=params,
                        headers={k: v for k, v in self.HEADERS.items()},
                    )
                    if api_resp.status_code == 200:
                        api_data = api_resp.json()
                        if (api_data.get("meta") or {}).get("result") == "SUCCESS":
                            goods_nos = [
                                str(item.get("goodsNo"))
                                for item in (api_data.get("data") or {}).get("list", [])
                            ]
                            return {
                                "success": True,
                                "count": len(goods_nos),
                                "goodsNos": goods_nos,
                                "source": "api",
                            }
            except Exception:
                pass

            # URL에서 상품번호 직접 추출
            match = re.search(r"/(?:app/)?(?:goods|products)/(\d{4,8})", url)
            if match:
                return {
                    "success": True,
                    "count": 1,
                    "goodsNos": [match.group(1)],
                    "source": "url-pattern",
                }

            return {"success": True, "count": 0, "goodsNos": [], "source": "none"}

    async def check_login_status(self, cookie: Optional[str] = None) -> dict[str, Any]:
        """로그인 상태 확인 - proxy-server.mjs /api/musinsa/check-login 포팅."""
        cookie_to_check = cookie or self.cookie
        if not cookie_to_check:
            return {"isLoggedIn": False}

        timeout = httpx.Timeout(10.0, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    self.BASE_MEMBER,
                    headers={**self.HEADERS, "Cookie": cookie_to_check},
                )
                me_json = resp.json()
                data = me_json.get("data") or {}
                is_logged_in = bool(data.get("memberId"))
                return {
                    "isLoggedIn": is_logged_in,
                    "memberId": data.get("memberId", ""),
                    "gradeName": data.get("gradeName", ""),
                }
        except Exception:
            return {"isLoggedIn": False}

    async def set_cookie_and_verify(self, cookie: str) -> dict[str, Any]:
        """쿠키 설정 및 검증 - proxy-server.mjs /api/musinsa/set-cookie 포팅."""
        if not cookie:
            return {"success": False, "message": "쿠키가 없습니다"}

        self.cookie = cookie

        timeout = httpx.Timeout(10.0, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    self.BASE_MEMBER,
                    headers={**self.HEADERS, "Cookie": cookie},
                )
                me_json = resp.json()
                data = me_json.get("data") or {}
                if data.get("memberId"):
                    return {
                        "success": True,
                        "isLoggedIn": True,
                        "memberId": data["memberId"],
                        "gradeName": data.get("gradeName", ""),
                        "message": (
                            f"{data['memberId']} 로그인 성공 "
                            f"({data.get('gradeName') or '등급미확인'})"
                        ),
                    }
        except Exception as exc:
            logger.warning(f"[무신사] 쿠키 검증 API 실패 (쿠키는 저장됨): {exc}")

        return {
            "success": True,
            "isLoggedIn": True,
            "message": "쿠키가 설정되었습니다. 수집 시 로그인 여부가 확인됩니다.",
        }

    async def check_stock(self, goods_nos: list[str]) -> dict[str, Any]:
        """재고 소진 감지 - proxy-server.mjs /api/agents/stock-check 포팅."""
        results = []
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for goods_no in goods_nos:
                try:
                    resp = await client.get(
                        f"{self.BASE_DETAIL}/{goods_no}",
                        headers=self._headers(),
                    )
                    if resp.status_code != 200:
                        results.append(
                            {"goodsNo": goods_no, "error": f"API {resp.status_code}", "isSoldOut": None}
                        )
                        continue
                    d = resp.json().get("data")
                    if not d:
                        results.append(
                            {"goodsNo": goods_no, "error": "데이터 없음", "isSoldOut": None}
                        )
                        continue
                    is_sold_out = bool(
                        d.get("isSoldOut") or (d.get("goodsPrice") or {}).get("isSoldOut")
                    )
                    price = (
                        (d.get("goodsPrice") or {}).get("immediateDiscountedPrice")
                        or (d.get("goodsPrice") or {}).get("salePrice")
                        or 0
                    )
                    results.append(
                        {
                            "goodsNo": goods_no,
                            "isSoldOut": is_sold_out,
                            "price": price,
                            "name": d.get("goodsName", ""),
                        }
                    )
                except Exception as exc:
                    results.append(
                        {"goodsNo": goods_no, "error": str(exc), "isSoldOut": None}
                    )

        sold_out_count = sum(1 for r in results if r.get("isSoldOut") is True)
        return {"success": True, "results": results, "soldOutCount": sold_out_count}

    async def monitor_prices(
        self, products: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """가격 변동 감지 - proxy-server.mjs /api/agents/price-monitor 포팅."""
        results = []
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for p in products:
                goods_no = p.get("goodsNo", "")
                try:
                    resp = await client.get(
                        f"{self.BASE_DETAIL}/{goods_no}",
                        headers=self._headers(),
                    )
                    if resp.status_code != 200:
                        results.append(
                            {
                                "goodsNo": goods_no,
                                "productId": p.get("productId"),
                                "error": f"API {resp.status_code}",
                                "changed": False,
                            }
                        )
                        continue
                    d = resp.json().get("data")
                    if not d:
                        results.append(
                            {
                                "goodsNo": goods_no,
                                "productId": p.get("productId"),
                                "error": "데이터 없음",
                                "changed": False,
                            }
                        )
                        continue
                    gp_inner = d.get("goodsPrice") or {}
                    current_price = (
                        gp_inner.get("immediateDiscountedPrice")
                        or gp_inner.get("salePrice")
                        or 0
                    )
                    stored_price = p.get("storedPrice", 0)
                    diff = current_price - stored_price
                    diff_rate = (
                        round(diff / stored_price * 100) if stored_price > 0 else 0
                    )
                    results.append(
                        {
                            "goodsNo": goods_no,
                            "productId": p.get("productId"),
                            "storedPrice": stored_price,
                            "currentPrice": current_price,
                            "changed": current_price != stored_price,
                            "diff": diff,
                            "diffRate": diff_rate,
                            "name": d.get("goodsName", ""),
                            "isSoldOut": bool(
                                d.get("isSoldOut") or gp_inner.get("isSoldOut")
                            ),
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "goodsNo": goods_no,
                            "productId": p.get("productId"),
                            "error": str(exc),
                            "changed": False,
                        }
                    )

        changed_count = sum(1 for r in results if r.get("changed"))
        return {"success": True, "results": results, "changedCount": changed_count}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_options(
        self,
        client: httpx.AsyncClient,
        goods_no: str,
        gp: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[int, int]]:
        """옵션 + 재고 API 호출."""
        option_value_no_map: dict[int, int] = {}
        options: list[dict[str, Any]] = []

        try:
            opt_resp = await client.get(
                f"{self.BASE_DETAIL}/{goods_no}/options",
                headers=self._headers(),
            )
            if opt_resp.status_code != 200:
                return options, option_value_no_map

            opt_json = opt_resp.json()
            opt_meta = opt_json.get("meta", {})
            if opt_meta.get("result") != "SUCCESS" or not opt_json.get("data"):
                return options, option_value_no_map

            items = opt_json["data"].get("optionItems", [])

            # optionValueNo 목록 수집
            all_option_value_nos: list[int] = []
            for item in items:
                for v in item.get("optionValues", []):
                    if v.get("no"):
                        all_option_value_nos.append(v["no"])
                        option_value_no_map[v["no"]] = item.get("no", 0)

            # 재고 API
            inventory_map: dict[int, dict[str, Any]] = {}
            if all_option_value_nos:
                try:
                    inv_resp = await client.post(
                        f"{self.BASE_DETAIL}/{goods_no}/options/v2/prioritized-inventories",
                        headers={**self.HEADERS, "Content-Type": "application/json"},
                        json={"optionValueNos": all_option_value_nos},
                    )
                    if inv_resp.status_code == 200:
                        inv_json = inv_resp.json()
                        if (
                            (inv_json.get("meta") or {}).get("result") == "SUCCESS"
                            and isinstance(inv_json.get("data"), list)
                        ):
                            for inv in inv_json["data"]:
                                opt_item_no = inv.get("productVariantId")
                                if opt_item_no:
                                    inventory_map[opt_item_no] = {
                                        "remainQuantity": inv.get("remainQuantity"),
                                        "outOfStock": inv.get("outOfStock", False),
                                        "isRedirect": inv.get("isRedirect", False),
                                        "deliveryType": (
                                            (inv.get("domesticDelivery") or {}).get(
                                                "deliveryType", ""
                                            )
                                        ),
                                    }
                except Exception as inv_err:
                    logger.warning(
                        f"[재고] {goods_no} 재고 API 실패 (무시): {inv_err}"
                    )

            # 옵션 정리 — preorder 등 salePrice=0인 경우 normalPrice 폴백
            base_price = (
                gp.get("immediateDiscountedPrice")
                or gp.get("salePrice")
                or gp.get("normalPrice", 0)
            )
            for item in items:
                if not item.get("activated") or item.get("isDeleted"):
                    continue
                vals = [
                    v.get("name", "")
                    for v in item.get("optionValues", [])
                    if v.get("name")
                ]
                inv = inventory_map.get(item.get("no", 0))

                stock: Optional[int] = None
                is_sold_out = False
                is_brand_delivery = False

                if inv:
                    is_brand_delivery = inv.get("isRedirect") is True
                    if inv.get("outOfStock") and not is_brand_delivery:
                        stock = 0
                        is_sold_out = True
                    elif is_brand_delivery:
                        stock = None
                        is_sold_out = False
                    elif inv.get("remainQuantity") is not None:
                        stock = inv["remainQuantity"]
                    else:
                        stock = 999

                options.append(
                    {
                        "no": item.get("no"),
                        "name": " / ".join(vals) or item.get("managedCode", ""),
                        "price": (base_price or 0) + (item.get("price") or 0),
                        "stock": stock,
                        "isSoldOut": is_sold_out,
                        "isBrandDelivery": is_brand_delivery,
                        "deliveryType": (inv or {}).get("deliveryType", ""),
                        "managedCode": item.get("managedCode", ""),
                    }
                )

        except Exception as exc:
            logger.warning(f"[옵션] {goods_no} 옵션 수집 실패: {exc}")

        return options, option_value_no_map

    async def _fetch_essential(
        self, client: httpx.AsyncClient, goods_no: str
    ) -> dict[str, str]:
        """상품고시정보 API 호출."""
        essential: dict[str, str] = {}
        try:
            resp = await client.get(
                f"{self.BASE_DETAIL}/{goods_no}/essential",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return essential
            ess_json = resp.json()
            if (
                (ess_json.get("meta") or {}).get("result") != "SUCCESS"
                or not (ess_json.get("data") or {}).get("essentials")
            ):
                return essential

            for item in ess_json["data"]["essentials"]:
                name = (item.get("name") or "").strip()
                value = (item.get("value") or "").strip()
                if not value:
                    continue
                if "소재" in name or "재질" in name:
                    essential["material"] = value
                elif name == "색상":
                    essential["color"] = value
                elif (
                    ("치수" in name or "사이즈" in name)
                    and "취급" not in name
                    and "주의" not in name
                ):
                    essential["size"] = value
                elif "제조사" in name or "제조자" in name:
                    essential["manufacturer"] = value
                elif "제조국" in name or "원산지" in name:
                    essential["origin"] = value
                elif (
                    ("세탁" in name or "취급" in name or "주의사항" in name)
                    and "치수" not in name
                    and "사이즈" not in name
                ):
                    essential["careInstructions"] = value
                elif "품질보증" in name:
                    essential["qualityGuarantee"] = value

        except Exception as exc:
            logger.warning(f"[고시] {goods_no} 고시정보 수집 실패: {exc}")

        return essential

    async def _fetch_coupons(
        self,
        client: httpx.AsyncClient,
        goods_no: str,
        d: dict[str, Any],
        s_price: int,
        best_coupon_discount: int,
    ) -> int:
        """쿠폰 API 호출."""
        try:
            params = urlencode(
                {
                    "goodsNo": goods_no,
                    "brand": d.get("brand", ""),
                    "comId": d.get("comId", ""),
                    "salePrice": s_price,
                }
            )
            coupon_url = f"{self.BASE_COUPON}?{params}"
            resp = await client.get(coupon_url, headers=self._headers())
            if resp.status_code == 200:
                coupon_json = resp.json()
                coupons = (coupon_json.get("data") or {}).get("list") or coupon_json.get(
                    "data", []
                )
                if isinstance(coupons, list):
                    for c in coupons:
                        actual_discount = 0
                        c_sale_price = c.get("salePrice", 0) or 0
                        # salePrice 우선 처리
                        if 0 < c_sale_price < s_price:
                            if c_sale_price < s_price * 0.5:
                                actual_discount = c_sale_price  # 작은 값 = 할인금액
                            else:
                                actual_discount = s_price - c_sale_price  # 큰 값 = 적용가
                        elif c.get("discountPrice", 0) and c["discountPrice"] > 0:
                            dp = c["discountPrice"]
                            # discountPrice도 적용가일 수 있으므로 가드 추가
                            if dp < s_price * 0.5:
                                actual_discount = dp  # 작은 값 = 할인금액
                            elif dp < s_price:
                                actual_discount = s_price - dp  # 큰 값 = 적용가
                        if actual_discount > best_coupon_discount:
                            best_coupon_discount = actual_discount
        except Exception as exc:
            logger.warning(f"[쿠폰] {goods_no} API 호출 실패: {exc}")

        return best_coupon_discount

    @staticmethod
    def _extract_detail_images(desc_html: str) -> list[str]:
        """상세 HTML에서 이미지 URL 추출."""
        detail_images: list[str] = []
        for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', desc_html, re.I):
            src = MusinsaClient._to_image_url(match.group(1))
            if src and "icon" not in src and "btn_" not in src:
                detail_images.append(src)
        return detail_images
