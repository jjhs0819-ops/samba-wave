"""29CM (www.29cm.co.kr) 소싱 HTTP 클라이언트.

curl_cffi 직접 호출 (NAVERSTORE 패턴). 확장앱 큐 위임 불필요.
httpx 는 29CM 전 API 에서 403 — Cloudflare TLS 지문 차단이라 헤더로 못 넘는다.

API 표면 — 전부 2026-08-24 실호출로 확인한 것만 사용한다. 추측 금지.
    검색      GET  search-api      /api/v4/products/search?keyword&count&page
    브랜드    GET  search-api      /api/v4/products/brand?frontBrandNo&count&page
    카테고리  GET  search-api      /api/v4/products/category?categoryLargeCode&...
    상세      GET  bff-api         /api/v6/product-detail/{itemNo}
    쿠폰      GET  promotion-api   /api/v4/coupons/downloadable/{itemNo}   [쿠키 필요]
    회원      GET  user-api        /api/v4/users/me                        [쿠키 필요]
    카테고리트리 GET display-bff-api /api/v1/category-groups/tree
    브랜드썸네일 GET search-api    /api/v4/products/brand-list?frontBrandNoList&limit

원가(최대혜택가) 정책 — 2026-08-24 로그인 상태로 랜덤 상품을 실제 렌더해 대조한 결과.

    cost = internalDisplayPrice.totalDiscountedItemPrice  (화면 노출가와 일치)

    쿠폰 API 로 직접 계산하면 안 된다. 쿠폰 목록은 "[첫구매 한정]" 쿠폰도
    canDownload=true 로 주는데, 첫구매가 아닌 계정은 실제로 못 쓴다
    (상품 3431574: 쿠폰계산 110,700 vs 화면 123,000, appliedCouponType=NONE).
    canDownload 는 사용 자격 판정이 아니다. 쿠폰으로 계산하면 원가를 낮게 잡아
    역마진이 난다.

    로그인 쿠키는 계속 싣는다(계정 기준 수집 요구 + 계정 전용가 노출 가능성).
    다만 표본에서 익명/로그인 노출가는 동일했다 — 쿠키가 가격을 바꾼 사례는 미관측.
    적립금(마일리지) 차감은 사용 조건을 실측하지 못해 원가에 반영하지 않는다.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, Callable, Optional

from backend.utils.logger import logger

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult


class RateLimitError(Exception):
    """29CM 차단 감지 (429/403)."""

    def __init__(self, status: int, retry_after: int = 0):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"HTTP {status} (retry_after={retry_after})")


# ──────────────────────────────────────────────────────────────
# 상수 — 실호출로 확정된 API 표면
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://www.29cm.co.kr"
IMAGE_HOST = "https://img.29cm.co.kr"

SEARCH_API = "https://search-api.29cm.co.kr"
BFF_API = "https://bff-api.29cm.co.kr"
PROMOTION_API = "https://promotion-api.29cm.co.kr"
USER_API = "https://user-api.29cm.co.kr"
DISPLAY_BFF_API = "https://display-bff-api.29cm.co.kr"

PATH_SEARCH = "/api/v4/products/search"
PATH_BRAND = "/api/v4/products/brand"
PATH_CATEGORY = "/api/v4/products/category"
PATH_DETAIL = "/api/v6/product-detail"
PATH_COUPONS = "/api/v4/coupons/downloadable"
PATH_ME = "/api/v4/users/me"
PATH_CATEGORY_TREE = "/api/v1/category-groups/tree"
PATH_BRAND_LIST = "/api/v4/products/brand-list"

DEFAULT_TIMEOUT = 30.0
# 403/429 자체 재시도 백오프(초) — 29CM 은 연속 호출에 일시 403 을 낸다(실측)
_RETRY_BACKOFF_SEC = (5, 10, 20)
# 검색/목록 API 1페이지 최대 건수 (count 파라미터)
PAGE_SIZE = 40

# sort 매핑 — 29CM 정렬 키. 미확인 값은 빈 문자열(기본 정렬)로 떨군다.
_SORT_MAP = {
    "POPULAR": "",
    "RECENT": "latest",
    "LOW_PRICE": "price_asc",
    "HIGH_PRICE": "price_desc",
    "DISCOUNT": "discount",
}

# 상품번호(itemNo) — 순수 숫자. URL 예: https://www.29cm.co.kr/products/3679452
_ITEM_NO_RE = re.compile(r"^\d{4,10}$")
_PRODUCT_URL_RE = re.compile(r"/products/(\d{4,10})")

# 고시정보 코드표 — 실측(itemDetailsList). 값은 잡워커 product_data 필드명으로 매핑.
_ITEM_DETAILS_MAP = {
    "101101": "material",  # 제품 소재
    "101102": "color",  # 색상
    "101103": "size_info",  # 치수
    "101104": "manufacturer",  # 제조자
    "101105": "origin",  # 제조국
    "101106": "care_instructions",  # 세탁방법 및 취급시 주의사항
    "101107": "manufacture_date",  # 제조연월
    "101108": "quality_guarantee",  # 품질보증기준
    "101109": "as_contact",  # A/S 책임자와 전화번호
}


class TwentyNineCMClient:
    """29CM HTTP 클라이언트.

    사용 예:
        client = TwentyNineCMClient(cookie)
        items = await client.search_products("나이키", page=1)
        detail = await client.get_product_detail("3679452")
        tree = await client.scan_categories("")
        result = await client.refresh_product(product)
    """

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"{BASE_URL}/",
        "Origin": BASE_URL,
    }

    def __init__(
        self,
        cookie: str = "",
        *,
        proxy_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.cookie = cookie or ""
        self.proxy_url = proxy_url
        self.timeout = timeout or DEFAULT_TIMEOUT

    # ──────────────────────────────────────────────────────────
    # public API — plugin / 잡워커가 위임
    # ──────────────────────────────────────────────────────────

    async def search(self, keyword: str, max_count: int = 100, **filters: Any) -> dict:
        """잡워커 공통 수집 인터페이스 — 페이징 집계. {"products": [...], "total": N}.

        keyword 가 그룹 URL(29cm.co.kr/... ?keyword=/frontBrandNo=/categoryLargeCode=)
        이면 파라미터를 직접 추출한다(워커가 URL 만 넘기는 경로 대비).
        """
        kw = keyword or ""
        merged: dict[str, Any] = {}
        if kw.startswith("http") and "29cm.co.kr" in kw:
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(kw).query)
            kw = (qs.get("keyword") or qs.get("q") or [""])[0]
            for k in (
                "frontBrandNo",
                "categoryLargeCode",
                "categoryMediumCode",
                "categorySmallCode",
                "sort",
            ):
                v = (qs.get(k) or [""])[0]
                if v:
                    merged[k] = v
            # 브랜드 상세 URL(/store/brand/95369)도 브랜드 수집으로 해석
            m = re.search(r"/store/brand/(\d+)", keyword)
            if m and "frontBrandNo" not in merged:
                merged["frontBrandNo"] = m.group(1)
        for k in (
            "frontBrandNo",
            "categoryLargeCode",
            "categoryMediumCode",
            "categorySmallCode",
            "sort",
        ):
            v = filters.get(k)
            if v not in (None, ""):
                merged[k] = v
        if filters.get("includeSoldOut"):
            merged["includeSoldOut"] = True

        try:
            max_count = max(1, int(max_count or 100))
        except (TypeError, ValueError):
            max_count = 100

        products: list[dict] = []
        seen: set[str] = set()
        page = 1
        # 상한 300페이지 가드 — 사이트가 마지막 페이지를 반복 반환해도 무한루프 방지
        while len(products) < max_count and page <= 300:
            batch = await self.search_products(kw, page=page, size=PAGE_SIZE, **merged)
            if not batch:
                break
            added = 0
            for it in batch:
                pid = str(it.get("site_product_id") or "")
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                products.append(it)
                added += 1
                if len(products) >= max_count:
                    break
            if added == 0:
                break
            page += 1
        return {"products": products, "total": len(products)}

    async def get_detail(self, site_product_id: str, **_ignored: Any) -> dict:
        """잡워커 범용 상세조회 인터페이스 — get_product_detail 별칭."""
        return await self.get_product_detail(site_product_id)

    async def search_products(self, keyword: str, **filters: Any) -> list[dict]:
        """키워드/브랜드/카테고리 목록 조회 → 정규화 리스트.

        우선순위:
            1) frontBrandNo 지정 → /api/v4/products/brand
            2) categoryLargeCode 지정 → /api/v4/products/category
            3) keyword 가 상품 URL/itemNo → 상세 단건
            4) 그 외 → /api/v4/products/search
        """
        page = max(1, int(filters.get("page") or 1))
        size = max(1, min(int(filters.get("size") or PAGE_SIZE), 100))
        sort_key = _SORT_MAP.get(str(filters.get("sort") or "").upper(), "")
        include_sold_out = bool(filters.get("includeSoldOut", False))

        params: dict[str, Any] = {"count": size, "page": page}
        if sort_key:
            params["sort"] = sort_key
        if not include_sold_out:
            params["excludeSoldOut"] = "true"

        host = SEARCH_API
        if filters.get("frontBrandNo"):
            path = PATH_BRAND
            params["frontBrandNo"] = str(filters["frontBrandNo"])
            for k in ("categoryLargeCode", "categoryMediumCode", "categorySmallCode"):
                if filters.get(k):
                    params[k] = str(filters[k])
        elif filters.get("categoryLargeCode"):
            path = PATH_CATEGORY
            for k in ("categoryLargeCode", "categoryMediumCode", "categorySmallCode"):
                if filters.get(k):
                    params[k] = str(filters[k])
        else:
            item_no = self._extract_item_no(keyword)
            if item_no:
                d = await self.get_product_detail(item_no)
                return [d] if d else []
            path = PATH_SEARCH
            params["keyword"] = keyword or ""

        async with self._client() as client:
            data = await self._fetch_json(client, host + path, params)
            if not data:
                return []
            body = data.get("data") or {}
            raw = body.get("products") or []
            normalized = [self._normalize_search_item(it) for it in raw if it]
            if not include_sold_out:
                normalized = [n for n in normalized if not n.get("isSoldOut")]
            return normalized

    async def get_product_detail(self, site_product_id: str) -> dict:
        """상품 상세 — product-detail + (쿠키 보유 시) 쿠폰 병합."""
        item_no = self._extract_item_no(site_product_id)
        if not item_no:
            return {}

        async with self._client() as client:
            detail_data = await self._get_detail(client, item_no)
            if not detail_data:
                return {}
            coupons = await self._get_coupons(client, item_no)
            return self._build_detail(item_no, detail_data, coupons)

    async def refresh_product(self, product: Any) -> "RefreshResult":
        """오토튠 사이클 — RefreshResult 채움.

        쿠키 없음        → error="29CM_AUTH_MISSING" (원가 오염 차단, 무신사와 동일)
        상세 404/FAIL    → deleted_from_source=True
        쿠폰 API 실패    → price_uncertain=True (한 사이클 더 대기)
        """
        from backend.domain.samba.collector.refresher import (
            RefreshResult,
            count_stock_transitions,
        )

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )
        source_url = getattr(product, "source_url", "") or getattr(
            product, "sourceUrl", ""
        )
        item_no = self._extract_item_no(site_product_id) or self._extract_item_no(
            source_url
        )
        if not item_no:
            return RefreshResult(product_id=product_id, error="29CM 상품번호 없음")

        # 로그인 쿠키 필수 — 계정 자격에 따라 쿠폰 목록이 달라지므로(실측 확인)
        # 익명 원가는 과소평가돼 역마진을 만든다.
        if not self.cookie:
            return RefreshResult(product_id=product_id, error="29CM_AUTH_MISSING")

        try:
            async with self._client() as client:
                detail_data = await self._get_detail(client, item_no)
                if not detail_data:
                    return RefreshResult(
                        product_id=product_id,
                        new_sale_status="sold_out",
                        new_options=[],
                        deleted_from_source=True,
                        changed=True,
                        stock_changed=True,
                    )
                # 쿠폰 API 는 원가 계산에 쓰지 않으므로 갱신 사이클에서 호출하지 않는다
                # (호출당 1 hop 절약 + 403 위험 감소). 원가는 상세의 노출가가 정본이다.
                coupons = None
                # 노출가(internalDisplayPrice)가 없으면 원가 확신 불가 → 한 사이클 대기
                price_uncertain = not (
                    (detail_data.get("internalDisplayPrice") or {}).get(
                        "totalDiscountedItemPrice"
                    )
                    or detail_data.get("sellPrice")
                )
        except RateLimitError as e:
            logger.warning(f"[29CM] 차단 ({item_no}): {e}")
            return RefreshResult(product_id=product_id, error=f"29CM 차단: {e}")
        except Exception as e:
            logger.exception(f"[29CM] refresh 실패 {item_no}: {e}")
            return RefreshResult(product_id=product_id, error=f"29CM refresh 실패: {e}")

        new_original_price = self._safe_int(
            detail_data.get("consumerPrice")
        ) or self._safe_int(detail_data.get("sellPrice"))
        new_cost = self._compute_cost(detail_data, coupons)
        # 판매가 = 화면 노출가. sellPrice 는 화면에 안 뜨므로 쓰지 않는다
        # (_build_detail 주석 참조 — 실측 30건).
        new_sale_price = new_cost or new_original_price

        new_options = self._normalize_options(detail_data)
        is_sold_out = self._is_sold_out(detail_data, new_options)
        new_sale_status = "sold_out" if is_sold_out else "in_stock"

        old_options = getattr(product, "options", None) or []
        stock_changes = count_stock_transitions(old_options, new_options or [])
        old_sale = float(getattr(product, "sale_price", 0) or 0)
        old_status = getattr(product, "sale_status", "in_stock")
        changed = (float(new_sale_price or 0) != old_sale) or (
            new_sale_status != old_status
        )

        return RefreshResult(
            product_id=product_id,
            new_sale_price=float(new_sale_price) if new_sale_price else None,
            new_original_price=float(new_original_price)
            if new_original_price
            else None,
            new_cost=float(new_cost) if new_cost else None,
            # 29CM 은 적립금 사용 조건을 실측하지 못해 원가에 적립을 반영하지 않는다.
            # 따라서 보유적립금 제외 원가 == 원가.
            new_cost_excl_held_point=float(new_cost) if new_cost else None,
            new_benefit_cost=float(new_cost) if new_cost else None,
            new_sale_status=new_sale_status,
            new_options=new_options,
            new_free_shipping=self._is_free_shipping(detail_data),
            changed=changed,
            stock_changed=stock_changes > 0,
            price_uncertain=price_uncertain,
        )

    async def scan_categories(
        self,
        keyword: str = "",
        *,
        log_fn: Optional[Callable[[str], None]] = None,
        **_unused: Any,
    ) -> dict:
        """카테고리 트리 스캔 — category-groups/tree 1회 호출 → 3단계 평탄화."""

        def _log(msg: str) -> None:
            if log_fn:
                try:
                    log_fn(msg)
                except Exception:
                    pass

        async with self._client() as client:
            data = await self._fetch_json(
                client, DISPLAY_BFF_API + PATH_CATEGORY_TREE, {}
            )
        if not data:
            _log("[29CM] 카테고리 트리 조회 실패")
            return {"categories": [], "total": 0, "groupCount": 0}

        groups = (data.get("data") or {}).get("categoryGroups") or []
        categories: list[dict] = []
        for g in groups:
            group_name = (g.get("categoryGroupName") or "").strip()
            for large in g.get("largeCategories") or []:
                l_code = str(large.get("categoryCode") or "")
                l_name = (large.get("categoryName") or "").strip()
                for medium in large.get("mediumCategories") or []:
                    m_code = str(medium.get("categoryCode") or "")
                    m_name = (medium.get("categoryName") or "").strip()
                    smalls = medium.get("smallCategories") or []
                    if not smalls:
                        categories.append(
                            {
                                "code": m_code,
                                "name": m_name,
                                "path": f"{group_name} > {l_name} > {m_name}",
                                "categoryLargeCode": l_code,
                                "categoryMediumCode": m_code,
                                "categorySmallCode": "",
                            }
                        )
                        continue
                    for small in smalls:
                        s_code = str(small.get("categoryCode") or "")
                        s_name = (small.get("categoryName") or "").strip()
                        categories.append(
                            {
                                "code": s_code,
                                "name": s_name,
                                "path": f"{group_name} > {l_name} > {m_name} > {s_name}",
                                "categoryLargeCode": l_code,
                                "categoryMediumCode": m_code,
                                "categorySmallCode": s_code,
                            }
                        )
        _log(f"[29CM] 카테고리 {len(categories):,}개 수집 (그룹 {len(groups):,}개)")
        return {
            "categories": categories,
            "total": len(categories),
            "groupCount": len(groups),
        }

    async def discover_brands(self, keyword: str) -> dict:
        """브랜드 탐색 — 키워드 검색 결과에서 브랜드를 집계한다.

        29CM 은 브랜드 디렉토리 API 가 확인되지 않아(brand-list 는 번호를 이미
        알아야 조회 가능) 검색 결과 기반 집계로 대체한다. count 는 표본 내 노출 수다.
        """
        agg: dict[str, dict] = {}
        # 표본 5페이지(최대 200건) — 브랜드 후보 확보용. 전수 아님.
        for page in range(1, 6):
            items = await self.search_products(
                keyword, page=page, size=PAGE_SIZE, includeSoldOut=True
            )
            if not items:
                break
            for it in items:
                code = str(it.get("brandCode") or "")
                name = (it.get("brand") or "").strip()
                if not code or not name:
                    continue
                cur = agg.setdefault(code, {"name": name, "value": code, "count": 0})
                cur["count"] += 1
        brands = sorted(agg.values(), key=lambda b: -b["count"])
        return {"brands": brands, "total": len(brands)}

    async def get_member_info(self) -> dict:
        """로그인 계정 정보 — 쿠키 유효성 확인용. 실패 시 빈 dict."""
        if not self.cookie:
            return {}
        async with self._client() as client:
            data = await self._fetch_json(client, USER_API + PATH_ME, {})
        if not data or data.get("result") != "SUCCESS":
            return {}
        return data.get("data") or {}

    async def test_auth(self) -> bool:
        """쿠키 인증 테스트."""
        return bool(await self.get_member_info())

    # ──────────────────────────────────────────────────────────
    # 내부 HTTP
    # ──────────────────────────────────────────────────────────

    def _client(self):
        """curl_cffi AsyncSession — Chrome TLS fingerprint 위장.

        httpx 로는 29CM 전 API 가 403 이다(실측: UA/Referer/Origin/HTTP2 조합
        전부 403, curl 은 200). Cloudflare TLS 지문 차단이라 헤더로는 못 넘는다.
        네이버스토어(naverstore_sourcing.py)와 같은 방식으로 우회한다.
        """
        from curl_cffi.requests import AsyncSession

        headers = dict(self.HEADERS)
        if self.cookie:
            headers["Cookie"] = self.cookie
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "impersonate": "chrome",
            "headers": headers,
        }
        if self.proxy_url:
            kwargs["proxies"] = {"http": self.proxy_url, "https": self.proxy_url}
        return AsyncSession(**kwargs)

    async def _fetch_json(
        self,
        client: Any,
        url: str,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """GET → JSON. 404 는 None, 재시도 후에도 429/403 이면 RateLimitError.

        29CM 은 짧은 간격 연속 호출에 403 을 낸다(실측: 3초 간격에도 재발).
        일시적인 경우가 대부분이라 5/10/20초 백오프로 3회까지 자체 재시도한다.
        그래도 막히면 RateLimitError 를 올려 refresher 의 사이트 단위 backoff 에 맡긴다.
        """
        resp = None
        for attempt in range(len(_RETRY_BACKOFF_SEC) + 1):
            try:
                resp = await client.get(url, params=params or {})
            except Exception as e:
                logger.warning(f"[29CM] 요청 실패 {url}: {e}")
                return None
            if resp.status_code not in (403, 429):
                break
            if attempt >= len(_RETRY_BACKOFF_SEC):
                break
            wait = _RETRY_BACKOFF_SEC[attempt]
            logger.warning(
                f"[29CM] HTTP {resp.status_code} — {wait}초 후 재시도 "
                f"({attempt + 1}/{len(_RETRY_BACKOFF_SEC)}) {url}"
            )
            await asyncio.sleep(wait)
        if resp.status_code in (403, 429):
            retry_after = self._safe_int(resp.headers.get("Retry-After"))
            raise RateLimitError(resp.status_code, retry_after)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(f"[29CM] HTTP {resp.status_code} {url}")
            return None
        try:
            return resp.json()
        except Exception as e:
            logger.warning(f"[29CM] JSON 파싱 실패 {url}: {e}")
            return None

    async def _get_detail(self, client: Any, item_no: str) -> Optional[dict]:
        """상세 원본 data. 삭제/비노출 상품은 None."""
        data = await self._fetch_json(client, f"{BFF_API}{PATH_DETAIL}/{item_no}")
        if not data or data.get("result") != "SUCCESS":
            return None
        return data.get("data") or None

    async def _get_coupons(self, client: Any, item_no: str) -> Optional[list]:
        """다운로드 가능 쿠폰 목록(상품 쿠폰). 실패 시 None(=원가 불확실).

        쿠키가 없으면 호출하지 않는다 — 익명 목록은 계정이 받을 수 없는 쿠폰까지
        포함해 원가를 과소평가시키기 때문이다(실측 확인).
        """
        if not self.cookie:
            return None
        data = await self._fetch_json(
            client, f"{PROMOTION_API}{PATH_COUPONS}/{item_no}"
        )
        if not data or data.get("result") != "SUCCESS":
            return None
        return (data.get("data") or {}).get("itemCouponList") or []

    # ──────────────────────────────────────────────────────────
    # 정규화 / 계산
    # ──────────────────────────────────────────────────────────

    @classmethod
    def _normalize_search_item(cls, item: dict) -> dict:
        item_no = str(item.get("itemNo") or "")
        consumer = cls._safe_int(item.get("consumerPrice"))
        sale = cls._safe_int(item.get("lastSalePrice")) or consumer
        url = f"{BASE_URL}/products/{item_no}" if item_no else ""
        return {
            "siteProductId": item_no,
            "site_product_id": item_no,
            "name": (item.get("itemName") or "").strip(),
            "brand": (item.get("frontBrandNameKor") or "").strip(),
            "brandEng": (item.get("frontBrandNameEng") or "").strip(),
            "brandCode": str(item.get("frontBrandNo") or ""),
            "originalPrice": consumer,
            "salePrice": sale,
            # snake_case 별칭 — 잡워커 수집 루프가 snake 로 읽는다.
            # cost 는 상세(쿠폰 반영)가 정본이고 여기 값은 상세 누락 시 폴백이다.
            "sale_price": sale,
            "original_price": consumer,
            "cost": sale,
            "discountRate": cls._safe_int(item.get("lastSalePercent")),
            "isSoldOut": bool(item.get("isSoldOut")),
            "imageUrl": cls._to_image_url(item.get("imageUrl") or ""),
            "sourceUrl": url,
            "source_url": url,
            "freeShipping": bool(item.get("isFreeShipping")),
            "free_shipping": bool(item.get("isFreeShipping")),
            "category": cls._build_search_category_path(item),
            "categoryCode": cls._first_category_code(item),
            "reviewCount": cls._safe_int(item.get("reviewCount")),
            "reviewRating": float(item.get("reviewAveragePoint") or 0),
        }

    @staticmethod
    def _first_category_code(item: dict) -> str:
        infos = item.get("frontCategoryInfo") or []
        if not infos:
            return ""
        first = infos[0] or {}
        return str(
            first.get("categorySmallCode")
            or first.get("categoryMediumCode")
            or first.get("categoryLargeCode")
            or ""
        )

    @staticmethod
    def _build_search_category_path(item: dict) -> str:
        infos = item.get("frontCategoryInfo") or []
        if not infos:
            return ""
        first = infos[0] or {}
        parts = [
            first.get("categoryLargeName") or "",
            first.get("categoryMediumName") or "",
            first.get("categorySmallName") or "",
        ]
        return " > ".join(p for p in parts if p)

    def _build_detail(
        self, item_no: str, detail_data: dict, coupons: Optional[list]
    ) -> dict:
        brand = detail_data.get("frontBrand") or {}
        consumer = self._safe_int(detail_data.get("consumerPrice"))
        cost = self._compute_cost(detail_data, coupons)
        # 판매가 = 화면에 크게 노출되는 최종가(= 노출가). sellPrice 는 쓰지 않는다.
        # 29CM 상세는 consumerPrice / sellPrice / internalDisplayPrice 3단인데
        # 화면은 정가(consumerPrice, 취소선)와 노출가만 보여주고 sellPrice 는
        # 어디에도 안 띄운다 [실측 30건]. 예: 1659305 = 48,000 / 42,000 / 33,600
        # → 화면은 48,000 과 33,600 만 노출. sellPrice 를 판매가로 쓰면 마켓에
        # 사이트 어디에도 없는 가격이 올라간다.
        sale = cost or self._safe_int(detail_data.get("sellPrice")) or consumer
        options = self._normalize_options(detail_data)
        images = [
            self._to_image_url(im.get("imageUrl") or "")
            for im in (detail_data.get("itemImages") or [])
            if im.get("imageUrl")
        ]
        category_path, category_code = self._build_detail_category(detail_data)
        detail_html = detail_data.get("itemDescriptions") or ""
        url = f"{BASE_URL}/products/{item_no}"

        return {
            "siteProductId": item_no,
            "site_product_id": item_no,
            "name": (detail_data.get("itemName") or "").strip(),
            "brand": (brand.get("brandNameKor") or "").strip(),
            "brandEng": (brand.get("brandNameEng") or "").strip(),
            "brandCode": str(brand.get("frontBrandNo") or ""),
            "originalPrice": consumer,
            "salePrice": sale,
            "cost": cost,
            "sale_price": sale,
            "original_price": consumer,
            "isSoldOut": self._is_sold_out(detail_data, options),
            "options": options,
            "images": images,
            "category": category_path,
            "categoryCode": category_code,
            "descriptionHtml": detail_html,
            # snake_case 별칭 — 잡워커가 detail_html/detail_images 로 읽는다.
            # 29CM 은 상세 이미지 컬럼이 따로 없어 상품 이미지를 상세로 쓴다(ABC/GS 선례).
            "detail_html": detail_html,
            "detail_images": images,
            "shipping_fee": 0 if self._is_free_shipping(detail_data) else None,
            "freeShipping": self._is_free_shipping(detail_data),
            "free_shipping": self._is_free_shipping(detail_data),
            "loyaltyPoints": self._safe_int(detail_data.get("mileage")),
            "maxOrderQty": self._safe_int(detail_data.get("maxOrderQty")),
            "sourceUrl": url,
            "source_url": url,
            "sex": self._infer_sex(category_path, detail_data.get("itemName") or ""),
            # 필수고시 — itemDetailsList 코드 매핑 (material/color/origin/…)
            **self._extract_item_details(detail_data),
        }

    @staticmethod
    def _build_detail_category(detail_data: dict) -> tuple[str, str]:
        infos = detail_data.get("frontCategoryInfo") or []
        if not infos:
            return "", ""
        first = infos[0] or {}
        parts = [
            first.get("category1Name") or "",
            first.get("category2Name") or "",
            first.get("category3Name") or "",
        ]
        code = str(
            first.get("category3Code")
            or first.get("category2Code")
            or first.get("category1Code")
            or ""
        )
        return " > ".join(p for p in parts if p), code

    @classmethod
    def _extract_item_details(cls, detail_data: dict) -> dict:
        """고시정보(itemDetailsList) → 필드 매핑. '상세 페이지 참조' 류는 버린다."""
        out: dict[str, str] = {}
        for it in detail_data.get("itemDetailsList") or []:
            field = _ITEM_DETAILS_MAP.get(str(it.get("itemDetailsCode") or ""))
            if not field:
                continue
            val = (it.get("itemDetailsValue") or "").strip()
            if not val or val in ("상세 페이지 참조", "상세페이지 참조"):
                continue
            out[field] = val
        return out

    @classmethod
    def _normalize_options(cls, detail_data: dict) -> list[dict]:
        """옵션 → [{name, price, stock, isSoldOut}].

        29CM 은 옵션별 수량을 주지 않는다(isDisplayOptionQty=false, 실측).
        판매중이면 stock=1, 품절이면 0 으로 둔다 — 수량 기반 로직이 오판하지 않도록
        0/1 만 쓴다.
        """
        options = ((detail_data.get("relationItemGroup") or {}).get("options")) or []
        sell = cls._safe_int(detail_data.get("sellPrice"))
        if not options:
            sold_out = detail_data.get("frontItemStockStatus") == "SOLD_OUT"
            return [
                {
                    "name": "단일",
                    "price": sell,
                    "stock": 0 if sold_out else 1,
                    "isSoldOut": sold_out,
                }
            ]
        out: list[dict] = []
        for o in options:
            if not o.get("isVisible", True):
                continue
            sold_out = bool(o.get("isSoldOut")) or (
                o.get("optionStatusTypeName") == "SOLD_OUT"
            )
            out.append(
                {
                    "name": (
                        o.get("optionItemValue") or o.get("optionName") or ""
                    ).strip(),
                    "price": sell,  # 옵션별 추가금은 hasVisibleOptionExtraPrice 로만 노출
                    "stock": 0 if sold_out else 1,
                    "isSoldOut": sold_out,
                }
            )
        return out

    @staticmethod
    def _is_sold_out(detail_data: dict, options: list[dict]) -> bool:
        if detail_data.get("frontItemStockStatus") == "SOLD_OUT":
            return True
        if options and all(o.get("isSoldOut") for o in options):
            return True
        return False

    @staticmethod
    def _is_free_shipping(detail_data: dict) -> bool:
        brand = detail_data.get("frontBrand") or {}
        if brand.get("isFreeShipping"):
            return True
        for b in detail_data.get("badge") or []:
            if (b or {}).get("type") == "FREE_SHIPPING":
                return True
        return False

    @classmethod
    def _compute_cost(cls, detail_data: dict, coupons: Optional[list] = None) -> int:
        """최대혜택가 = internalDisplayPrice.totalDiscountedItemPrice.

        쿠폰 목록으로 직접 계산하면 안 된다 [실측 근거·2026-08-24].
        상품 3431574(파인드카푸어 모노백)의 쿠폰 API 는 "[첫구매 한정] 10%" 쿠폰을
        canDownload=true 로 준다. 그런데 이 계정은 첫구매가 아니라 실제로는 못 쓴다
        — 상품 페이지는 123,000원(appliedCouponType=NONE)을 노출한다.
        즉 canDownload 는 사용 자격 판정이 아니다. 쿠폰으로 계산하면 원가를
        12,300원 낮게 잡아 역마진이 난다.

        랜덤 10건을 로그인 상태로 실제 렌더해 대조한 결과 화면 노출가는 10/10
        internalDisplayPrice 와 일치했다. 그래서 이 값을 단일 진실로 쓴다.
        coupons 인자는 호환용으로 남겨두되 가격 계산에 쓰지 않는다.
        """
        idp = detail_data.get("internalDisplayPrice") or {}
        display = cls._safe_int(idp.get("totalDiscountedItemPrice"))
        if display > 0:
            return display
        return cls._safe_int(detail_data.get("sellPrice")) or cls._safe_int(
            detail_data.get("consumerPrice")
        )

    @classmethod
    def _coupon_discount(cls, coupon: dict, base_price: int) -> int:
        """쿠폰 1장의 할인액. FIXED_RATE(정률) / 그 외(정액) 처리."""
        value = cls._safe_int(coupon.get("discountValue"))
        if value <= 0 or base_price <= 0:
            return 0
        if (coupon.get("discountType") or "").upper() == "FIXED_RATE":
            disc = base_price * value // 100
            cap = cls._safe_int(coupon.get("maxDiscountPrice"))
            # maxDiscountPrice=0 은 상한 없음 (실측: "나이키 10%" 쿠폰이 0)
            if cap > 0:
                disc = min(disc, cap)
            return disc
        return min(value, base_price)

    # ──────────────────────────────────────────────────────────
    # 유틸
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _safe_int(v: Any) -> int:
        try:
            if v is None or v == "":
                return 0
            return int(float(str(v).replace(",", "")))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_image_url(path: str) -> str:
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return f"{IMAGE_HOST}{path if path.startswith('/') else '/' + path}"

    @staticmethod
    def _extract_item_no(s: Any) -> str:
        """URL / itemNo 문자열에서 상품번호 추출. 실패 시 빈 문자열."""
        if not s:
            return ""
        text = str(s).strip()
        m = _PRODUCT_URL_RE.search(text)
        if m:
            return m.group(1)
        if _ITEM_NO_RE.match(text):
            return text
        return ""

    @staticmethod
    def _infer_sex(category_path: str, name: str) -> str:
        """성별 추정 — 29CM 은 성별 필드가 없어 카테고리/상품명으로만 추정한다.

        genderAttr 필드가 있으나 값이 0(미지정)으로만 관측돼 신뢰하지 않는다.
        """
        text = f"{category_path} {name}"
        has_w = any(k in text for k in ("여성", "우먼", "WOMEN", "Women", " W "))
        has_m = any(k in text for k in ("남성", "맨즈", "MEN", "Men"))
        if has_w and not has_m:
            return "female"
        if has_m and not has_w:
            return "male"
        return ""


async def _selftest(item_no: str = "3679452") -> None:  # pragma: no cover
    """수동 점검용 — 파이썬으로 직접 실행할 때만 쓴다."""
    client = TwentyNineCMClient()
    detail = await client.get_product_detail(item_no)
    print(detail.get("name"), detail.get("salePrice"), detail.get("cost"))


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_selftest())
