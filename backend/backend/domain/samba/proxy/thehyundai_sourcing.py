"""더현대Hi (hi.thehyundai.com) 소싱 HTTP 클라이언트.

순수 httpx 직접 호출 — 인증/UA/Referer/Cookie/CSRF 일체 불필요 (모든 GET 익명 200).
모든 데이터 API prefix: /proxy/v1/...

Chrome 1·2·3차 조사 결과 기반. 사이트 분석 메모는 plan v5 참조.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable, Optional

import httpx

from backend.utils.logger import logger

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult


class RateLimitError(Exception):
    """더현대Hi 차단 감지 (429/403)."""

    def __init__(self, status: int, retry_after: int = 0):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"HTTP {status} (retry_after={retry_after})")


# ──────────────────────────────────────────────────────────────
# 상수 — Chrome 조사로 확정된 API 표면
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://hi.thehyundai.com"
IMAGE_HOST = "https://image.thehyundai.com"  # 잠정 — N섹션 확정 시 변경

SEARCH_RESULT = "/proxy/v1/dp/search/searchResult"
FILTER_INFO = "/proxy/v1/dp/search/searchFilterInfo"
ITEM_DETAIL = "/proxy/v1/pd/item/detail"
UITM_STCK_LIST = "/proxy/v1/pd/item/uitm/uitmStckList"
MAX_BNFT_LIST = "/proxy/v1/pd/item/prmo/maxBnftList"

# sort 매핑 — 1차 B-4 검증
_SORT_MAP = {
    "POPULAR": "",
    "RECENT": "dtm",
    "LOW_PRICE": "sellA",
    "HIGH_PRICE": "sellD",
    "DISCOUNT": "prc",
    "REVIEW": "eval",
}

# slitmCd — 10자 영숫자 (예: 40B0696270, 2246940700)
_SLITM_FULL_RE = re.compile(r"^[0-9A-Za-z]{10}$")
_PRODUCT_URL_RE = re.compile(r"/product/([0-9A-Za-z]{10})", re.IGNORECASE)

# 카테고리 스캔 SKIP — itemGbcd="2" 군 + 여행/E쿠폰/서비스/컬처 (1차 L + 2차 E)
_SKIP_PATH_PREFIXES = (
    "여행",
    "컬처/서비스 > E쿠폰",
    "컬처/서비스 > 서비스",
    "컬처/서비스 > 컬처",
)

DEFAULT_TIMEOUT = 30.0


class TheHyundaiSourcingClient:
    """더현대Hi HTTP 클라이언트.

    사용 예:
        client = TheHyundaiSourcingClient()
        items = await client.search_products("나이키", page=1, size=20)
        detail = await client.get_product_detail("40B0696270")
        tree = await client.scan_categories("")
        brands = await client.discover_brands("스포츠")
        result = await client.refresh_product(product)
    """

    def __init__(
        self, *, proxy_url: Optional[str] = None, timeout: Optional[float] = None
    ):
        self.proxy_url = proxy_url
        self.timeout = timeout or DEFAULT_TIMEOUT

    # ──────────────────────────────────────────────────────────
    # public API — plugin이 위임
    # ──────────────────────────────────────────────────────────

    async def search_products(self, keyword: str, **filters: Any) -> list[dict]:
        """키워드/카테고리/브랜드 검색.

        keyword 가 상품 URL 또는 slitmCd 면 → 단건 상세 1개 반환 (단, target/flBrand 미지정 시).
        그 외 → searchResult 호출 → normalized list.

        filters:
            page (int=1), size (int=36, max 36), sort (str),
            includeSoldOut (bool=False), flBrand (operBrndCd), flCate (catLcd),
            target ("cate"|"brand"), targetCode (str)
        """
        # URL/ID 단건 모드 — 명시 target 없을 때만
        if not filters.get("target") and not filters.get("flBrand"):
            slitm_cd = self._extract_slitm_cd(keyword)
            if slitm_cd:
                d = await self.get_product_detail(slitm_cd)
                return [d] if d else []

        page = max(1, int(filters.get("page") or 1))
        size = max(1, min(int(filters.get("size") or 36), 36))
        sort_key = self._map_sort(filters.get("sort", ""))
        include_sold_out = bool(filters.get("includeSoldOut", False))

        params: dict[str, Any] = {
            "searchType": "NCP_PRODUCT",  # ★ 미지정 시 productList 미반환 (트랩)
            "page": page,
            "disPlaySize": size,
        }
        target = (filters.get("target") or "").lower()
        target_code = filters.get("targetCode") or ""
        if target in ("cate", "brand") and target_code:
            params["target"] = target
            params["targetCode"] = str(target_code)
        else:
            params["searchQuery"] = keyword or ""
        if sort_key:
            params["sort"] = sort_key
        if filters.get("flBrand"):
            params["flBrand"] = str(filters["flBrand"])
        if filters.get("flCate"):
            params["flCate"] = str(filters["flCate"])

        async with self._client() as client:
            data = await self._fetch_json(client, SEARCH_RESULT, params)
            if not data:
                return []
            product_list = (data.get("productList") or {}).get(
                "productInfoList"
            ) or []
            normalized = [
                self._normalize_search_item(it) for it in product_list if it
            ]
            if not include_sold_out:
                normalized = [n for n in normalized if not n.get("isSoldOut")]
            return normalized

    async def get_product_detail(self, site_product_id: str) -> dict:
        """상품 상세 — detail + (uitmCombYn=="1" 시) uitmStckList + maxBnftList 머지."""
        slitm_cd = self._extract_slitm_cd(site_product_id)
        if not slitm_cd:
            return {}

        async with self._client() as client:
            detail_data = await self._get_detail(client, slitm_cd)
            if detail_data is None:
                return {}
            stck_list: Optional[list] = None
            if detail_data.get("uitmCombYn") == "1":
                stck_list = await self._get_uitm_stck_list(client, slitm_cd) or []
            max_bnft = await self._get_max_bnft_list(client, slitm_cd)
            return self._build_detail(slitm_cd, detail_data, stck_list, max_bnft)

    async def refresh_product(self, product: Any) -> "RefreshResult":
        """오토튠 사이클 — RefreshResult 전 필드 채움.

        new_cost = aplyDcPrc − Σ(step8a.dcAmt) − Σ(step8b.dcAmt) (SSG 선례 정책 (b)).
        detail 404 / result!=SUCCESS → deleted_from_source=True.
        maxBnftList 호출 실패 → price_uncertain=True (한 사이클 더 대기).
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
        slitm_cd = self._extract_slitm_cd(site_product_id) or self._extract_slitm_cd(
            source_url
        )
        if not slitm_cd:
            return RefreshResult(
                product_id=product_id, error="더현대 상품 ID(slitmCd) 없음"
            )

        try:
            async with self._client() as client:
                detail_data = await self._get_detail(client, slitm_cd)
                if detail_data is None:
                    return RefreshResult(
                        product_id=product_id,
                        new_sale_status="sold_out",
                        new_options=[],
                        deleted_from_source=True,
                        changed=True,
                        stock_changed=True,
                    )

                stck_list: Optional[list] = None
                if detail_data.get("uitmCombYn") == "1":
                    stck_list = await self._get_uitm_stck_list(client, slitm_cd)
                    if stck_list is None:
                        # 호출 실패 — 빈 리스트로 진행하면 전 옵션 품절 처리됨.
                        # 옵션 재고 불확실하다면 price_uncertain 대신 그대로 진행
                        # (uitmStckList 실패는 가격엔 영향 없고 옵션만 영향).
                        stck_list = []

                max_bnft = await self._get_max_bnft_list(client, slitm_cd)
                price_uncertain = max_bnft is None
        except RateLimitError as e:
            logger.warning(f"[THEHYUNDAI] 차단 ({slitm_cd}): {e}")
            return RefreshResult(
                product_id=product_id, error=f"더현대 차단: {e}"
            )
        except Exception as e:
            logger.exception(f"[THEHYUNDAI] refresh 실패 {slitm_cd}: {e}")
            return RefreshResult(
                product_id=product_id, error=f"더현대 refresh 실패: {e}"
            )

        prc_info = detail_data.get("prcInfo") or {}
        csm_prc = self._safe_int(prc_info.get("csmPrc"))
        sell_prc = self._safe_int(prc_info.get("sellPrc"))
        dc_prc = self._safe_int(prc_info.get("dcPrc"))
        max_dc_prc = self._safe_int(prc_info.get("maxDcPrc"))

        new_original_price = csm_prc if csm_prc > 0 else sell_prc
        new_sale_price = dc_prc or sell_prc
        new_cost = (
            self._compute_new_cost(max_bnft) if max_bnft else (max_dc_prc or dc_prc)
        )

        new_options = self._normalize_options(detail_data, stck_list)

        # 품절: ostkYn 단독 + 다차원 stckList 비어있으면 전 품절
        is_sold_out = detail_data.get("ostkYn") == "1"
        if (
            not is_sold_out
            and detail_data.get("uitmCombYn") == "1"
            and stck_list is not None
            and not stck_list
        ):
            is_sold_out = True
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
            new_sale_status=new_sale_status,
            new_options=new_options,
            changed=changed,
            stock_changed=stock_changes > 0,
            price_uncertain=price_uncertain,
        )

    async def scan_categories(
        self,
        keyword: str,
        *,
        brand_ids: Optional[list[str]] = None,
        selected_brands: Optional[list[str]] = None,  # 시그니처 일관성 (SSG 매개변수 호환)
        brand_total: int = 0,
        log_fn: Optional[Callable[[str], None]] = None,
        proxy_urls: Optional[list[str]] = None,
    ) -> dict:
        """카테고리 트리 스캔 — searchFilterInfo 1회 호출로 4단계 전체 평탄화.

        brand_ids 지정 시 flBrand 로 좁힘 (그 브랜드 판매 카테고리만).
        반환: {"categories": [{path, count, id, categoryCode}], "total": N, "groupCount": M}
        """

        def _log(msg: str) -> None:
            logger.info(msg)
            if log_fn:
                try:
                    log_fn(msg)
                except Exception:
                    pass

        _log(
            f"[THEHYUNDAI] 카테고리 스캔 시작: keyword={keyword!r} "
            f"brand_ids={brand_ids}"
        )

        params: dict[str, Any] = {
            "searchType": "NCP_PRODUCT",
            "page": 1,
            "disPlaySize": 36,
            "searchQuery": keyword or "",
        }
        if brand_ids:
            # flBrand 다중 — 쉼표 구분 (3-A에서 단건만 검증, 다중은 추정)
            params["flBrand"] = ",".join(str(b) for b in brand_ids if b)

        async with self._client() as client:
            data = await self._fetch_json(client, FILTER_INFO, params)
            if not data:
                _log("[THEHYUNDAI] filter info 응답 없음 — 빈 결과")
                return {"categories": [], "total": 0, "groupCount": 0}

            tree = self._build_category_tree(data)
            _log(
                f"[THEHYUNDAI] 트리 빌드 — {tree['groupCount']}개 노드, "
                f"총상품 {tree['total']:,}"
            )
            return tree

    async def discover_brands(self, keyword: str) -> dict:
        """브랜드 디렉토리 — searchFilterInfo.brandList → {name, value, count} 정규화.

        빈 키워드 → 전 사이트 브랜드 (1,672개 검증). 키워드 있으면 결과셋 내 브랜드만.
        canonical key = operBrndCd (= brandList.groupCode).
        """
        params: dict[str, Any] = {
            "searchType": "NCP_PRODUCT",
            "page": 1,
            "disPlaySize": 36,
            "searchQuery": keyword or "",
        }
        async with self._client() as client:
            data = await self._fetch_json(client, FILTER_INFO, params)
            if not data:
                return {"brands": [], "total": 0}

            brand_list = (data.get("brandList") or {}).get("groupInfoList") or []
            seen: set[str] = set()
            brands: list[dict] = []
            for b in brand_list:
                code = str(b.get("groupCode") or "").strip()
                if not code or code in seen:
                    continue
                seen.add(code)
                name = (b.get("groupName") or "").strip() or code
                brands.append(
                    {
                        "name": name,
                        "value": code,
                        "count": int(b.get("groupCnt") or 0),
                    }
                )
            return {"brands": brands, "total": len(brands)}

    # ──────────────────────────────────────────────────────────
    # internal — HTTP
    # ──────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "follow_redirects": True,
        }
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return httpx.AsyncClient(**kwargs)

    async def _fetch_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
    ) -> Optional[dict]:
        """GET path?params → data dict.

        - 429/403 → RateLimitError 발생.
        - 그 외 HTTP 실패, result != "SUCCESS" → None.
        """
        try:
            resp = await client.get(BASE_URL + path, params=params)
        except httpx.HTTPError as e:
            logger.warning(f"[THEHYUNDAI] HTTP error {path}: {e}")
            return None
        if resp.status_code in (429, 403):
            retry_after = self._safe_int(resp.headers.get("Retry-After"))
            raise RateLimitError(resp.status_code, retry_after)
        if resp.status_code != 200:
            logger.warning(f"[THEHYUNDAI] HTTP {resp.status_code} {path}")
            return None
        try:
            body = resp.json()
        except Exception as e:
            logger.warning(f"[THEHYUNDAI] JSON parse 실패 {path}: {e}")
            return None
        if body.get("result") != "SUCCESS":
            logger.info(
                f"[THEHYUNDAI] result={body.get('result')} {path} "
                f"msg={body.get('message')}"
            )
            return None
        return body.get("data") or {}

    async def _get_detail(
        self, client: httpx.AsyncClient, slitm_cd: str
    ) -> Optional[dict]:
        return await self._fetch_json(client, ITEM_DETAIL, {"slitmCd": slitm_cd})

    async def _get_uitm_stck_list(
        self, client: httpx.AsyncClient, slitm_cd: str
    ) -> Optional[list]:
        data = await self._fetch_json(client, UITM_STCK_LIST, {"slitmCd": slitm_cd})
        if data is None:
            return None
        if isinstance(data, list):
            return data
        # 응답이 dict 일 수도 (서버 형식 변동 대비)
        for key in ("uitmStckList", "list", "items"):
            v = data.get(key)
            if isinstance(v, list):
                return v
        return []

    async def _get_max_bnft_list(
        self, client: httpx.AsyncClient, slitm_cd: str
    ) -> Optional[dict]:
        return await self._fetch_json(
            client,
            MAX_BNFT_LIST,
            {
                "slitmCd": slitm_cd,
                "alliRefCd": "",
                "tcCode": "",
                "sectId": "",
                "preview": "",
                "previewVipGrade": "",  # 빈값 = 일반등급 (V0과 동일 검증됨)
            },
        )

    # ──────────────────────────────────────────────────────────
    # internal — 정규화
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _safe_int(v: Any) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _to_image_url(cls, path: str) -> str:
        if not path:
            return ""
        if path.startswith("http"):
            return path
        if path.startswith("//"):
            return f"https:{path}"
        if not path.startswith("/"):
            path = "/" + path
        return f"{IMAGE_HOST}{path}"

    @staticmethod
    def _extract_slitm_cd(s: Any) -> str:
        if not s:
            return ""
        s = str(s).strip()
        m = _PRODUCT_URL_RE.search(s)
        if m:
            return m.group(1).upper()
        if _SLITM_FULL_RE.match(s):
            return s.upper()
        return ""

    @staticmethod
    def _map_sort(sort: str) -> str:
        if not sort:
            return ""
        return _SORT_MAP.get(sort.upper(), sort)

    @classmethod
    def _normalize_search_item(cls, item: dict) -> dict:
        slitm_cd = (item.get("slitmCd") or "").upper()
        sell_prc = cls._safe_int(item.get("sellPrc"))
        bnft_prc = cls._safe_int(item.get("bnftPrc"))
        ostk_yn = item.get("ostkYn", "0")
        return {
            "siteProductId": slitm_cd,
            "site_product_id": slitm_cd,
            "name": (item.get("slitmNm") or "").strip(),
            "brand": (
                item.get("expsBrndNm") or item.get("operBrndNm") or ""
            ).strip(),
            "brandCode": str(item.get("operBrndCd") or "").strip(),
            "originalPrice": sell_prc,
            "salePrice": bnft_prc or sell_prc,
            "discountRate": cls._safe_int(
                item.get("bnftPrcRate") or item.get("salePct")
            ),
            "isSoldOut": ostk_yn == "1",
            "imageUrl": cls._to_image_url(item.get("itemImageUrl") or ""),
            "sourceUrl": f"{BASE_URL}/product/{slitm_cd}" if slitm_cd else "",
            "categoryCode": str(item.get("catLcd") or "").strip(),
            "categoryName": (item.get("catLNm") or "").strip(),
            "category": cls._build_search_category_path(item),
            "store": (item.get("hdptNm") or "").strip(),
            "freeShipping": item.get("freeDlvYn") == "1",
            "openMarket": item.get("openMktItemYn") == "1",
            "reservation": item.get("hdmalRsvSellYn") == "1",
            "reviewCount": cls._safe_int(item.get("itemEvalCnt")),
            "reviewRating": float(item.get("itemAvrgEvalScrg") or 0),
        }

    @staticmethod
    def _build_search_category_path(item: dict) -> str:
        parts = [
            item.get("catLNm") or "",
            item.get("itemLcsfNm") or "",
            item.get("itemMcsfNm") or "",
            item.get("itemScsfNm") or "",
            item.get("itemDcsfNm") or "",
        ]
        return " > ".join(p for p in parts if p)

    def _build_detail(
        self,
        slitm_cd: str,
        detail_data: dict,
        stck_list: Optional[list],
        max_bnft: Optional[dict],
    ) -> dict:
        prc_info = detail_data.get("prcInfo") or {}
        brnd_info = detail_data.get("brndInfo") or {}
        bnft_info = detail_data.get("bnftInfo") or {}

        csm_prc = self._safe_int(prc_info.get("csmPrc"))
        sell_prc = self._safe_int(prc_info.get("sellPrc"))
        dc_prc = self._safe_int(prc_info.get("dcPrc"))
        max_dc_prc = self._safe_int(prc_info.get("maxDcPrc"))
        new_cost = (
            self._compute_new_cost(max_bnft) if max_bnft else (max_dc_prc or dc_prc)
        )

        options = self._normalize_options(detail_data, stck_list)

        thumb_list = detail_data.get("thumbInfoList") or []
        images = [
            self._to_image_url(t.get("orglImgNm") or "")
            for t in thumb_list
            if t.get("orglImgNm")
        ]

        path_parts = [
            detail_data.get("itemLcsfNm") or "",
            detail_data.get("itemMcsfNm") or "",
            detail_data.get("itemScsfNm") or "",
            detail_data.get("itemDcsfNm") or "",
        ]
        category_path = " > ".join(p for p in path_parts if p)

        dlv_info_list = detail_data.get("dlvFormInfoList") or []
        dlv_first = dlv_info_list[0] if dlv_info_list else {}

        return {
            "siteProductId": slitm_cd,
            "site_product_id": slitm_cd,
            "name": (detail_data.get("slitmNm") or "").strip(),
            "brand": (
                brnd_info.get("expsBrndNm") or brnd_info.get("operBrndNm") or ""
            ).strip(),
            "brandCode": str(brnd_info.get("operBrndCd") or "").strip(),
            "brandEng": (brnd_info.get("expsEngBrndNm") or "").strip(),
            "originalPrice": csm_prc if csm_prc > 0 else sell_prc,
            "salePrice": dc_prc or sell_prc,
            "cost": new_cost,
            "isSoldOut": detail_data.get("ostkYn") == "1",
            "options": options,
            "images": images,
            "category": category_path,
            "categoryCode": str(detail_data.get("itemDcsfCd") or "").strip(),
            "descriptionHtml": self._extract_description_html(detail_data),
            "store": (detail_data.get("storeNm") or "").strip(),
            "freeShipping": dlv_first.get("dlvcPlcyBsicGbcd") == "01",
            "shippingFee": self._safe_int(dlv_first.get("dlvCost")),
            "freeShippingThreshold": self._safe_int(dlv_first.get("baseFee")),
            "remoteAreaFee": self._safe_int(dlv_first.get("irgnMntrDlvCost")),
            "carrierName": (dlv_first.get("dsrvDlvcoNm") or "").strip(),
            "openMarket": detail_data.get("openMktItemYn") == "1",
            "luxury": brnd_info.get("luitYn") == "1",
            "reservation": detail_data.get("hdmalRsvSellYn") == "1",
            "loyaltyPoints": self._safe_int(bnft_info.get("upntAcmPnt")),
            "sourceUrl": f"{BASE_URL}/product/{slitm_cd}",
            "itemGbcd": detail_data.get("itemGbcd"),
            "itemGbPtcGbCd": detail_data.get("itemGbPtcGbCd"),
        }

    @staticmethod
    def _extract_description_html(detail_data: dict) -> str:
        html_list = detail_data.get("htmlItstCntnList") or []
        # PC 우선 (htmlItstGbcd="00"), 없으면 첫번째
        for h in html_list:
            if h.get("htmlItstGbcd") == "00":
                return h.get("htmlItstCntn") or ""
        if html_list:
            return html_list[0].get("htmlItstCntn") or ""
        return ""

    @classmethod
    def _normalize_options(
        cls, detail_data: dict, stck_list: Optional[list]
    ) -> list[dict]:
        """plan v5 알고리즘 그대로 — [{name, price, stock, isSoldOut}]."""
        attr_list = detail_data.get("uitmAttrList") or []
        prc_info = detail_data.get("prcInfo") or {}
        sell_prc = cls._safe_int(prc_info.get("dcPrc") or prc_info.get("sellPrc"))

        # 옵션 없는 단일 SKU
        if not attr_list and not stck_list:
            return [
                {
                    "name": "단일",
                    "price": sell_prc,
                    "stock": cls._safe_int(detail_data.get("sellPossQty")),
                    "isSoldOut": detail_data.get("ostkYn") == "1",
                }
            ]

        # 단일 차원 — uitmAttrList 직접 사용
        if detail_data.get("uitmCombYn") == "0" and attr_list:
            return [
                {
                    "name": u.get("uitmTotNm") or u.get("uitmNm", ""),
                    "price": cls._safe_int(u.get("uitmDcPrc")) or sell_prc,
                    "stock": cls._safe_int(u.get("sellPossQty")),
                    "isSoldOut": u.get("uitmSellGbcd") == "11",
                }
                for u in attr_list
            ]

        # 다차원 (uitmCombYn=="1") — stckList 의존. 없는 uitmCd = 품절
        if stck_list:
            return [
                {
                    "name": s.get("uitmTotNm", ""),
                    "price": sell_prc,  # 다차원 옵션별 가격 별도 미제공
                    "stock": cls._safe_int(s.get("sellPossQty")),
                    "isSoldOut": False,
                }
                for s in stck_list
            ]

        # 다차원인데 stckList 비어있음 — 전 옵션 품절
        return []

    @staticmethod
    def _compute_new_cost(max_bnft_data: dict) -> int:
        """new_cost = aplyDcPrc − Σ(step8a.dcAmt) − Σ(step8b.dcAmt).

        SSG bestBenefitPrice 정책 일관 (= 카드 즉시할인 반영 사이트 노출 최저가).
        step1(기본할인)은 aplyDcPrc에 이미 반영. step2(쿠폰)은 보유자 한정이라 제외.
        step8a/b 둘 다 빈 배열이면 자동으로 aplyDcPrc (= maxDcPrc) 그대로.
        """
        aply_dc = int(max_bnft_data.get("aplyDcPrc") or 0)
        step8a_sum = sum(
            int(s.get("dcAmt") or 0)
            for s in (max_bnft_data.get("step8aBnftList") or [])
        )
        step8b_sum = sum(
            int(s.get("dcAmt") or 0)
            for s in (max_bnft_data.get("step8bBnftList") or [])
        )
        return max(0, aply_dc - step8a_sum - step8b_sum)

    @classmethod
    def _build_category_tree(cls, filter_data: dict) -> dict:
        """4단계 트리 평탄화 → {categories, total, groupCount}."""
        nodes: dict[str, dict] = {}
        for key in ("cateLList", "cateMList", "cateSList", "cateDList"):
            sect = filter_data.get(key) or {}
            for n in sect.get("groupInfoList") or []:
                code = str(n.get("groupCode") or "").strip()
                if not code:
                    continue
                parent = str(n.get("highGroupCode") or "").strip() or None
                nodes[code] = {
                    "id": code,
                    "name": (n.get("groupName") or "").strip(),
                    "count": int(n.get("groupCnt") or 0),
                    "parent": parent,
                }

        path_cache: dict[str, str] = {}

        def path(code: str) -> str:
            if code in path_cache:
                return path_cache[code]
            parts: list[str] = []
            cur: Optional[str] = code
            seen: set[str] = set()  # cycle guard
            while cur and cur in nodes and cur not in seen:
                seen.add(cur)
                parts.insert(0, nodes[cur]["name"])
                cur = nodes[cur].get("parent")
            out = " > ".join(p for p in parts if p)
            path_cache[code] = out
            return out

        categories: list[dict] = []
        for code, n in nodes.items():
            p = path(code)
            # SKIP — e쿠폰/여행/서비스/컬처 (prefix 매칭, "여행지" 같은 false-positive 방지)
            if any(
                p == sk or p.startswith(sk + " > ") for sk in _SKIP_PATH_PREFIXES
            ):
                continue
            categories.append(
                {
                    "path": p,
                    "count": n["count"],
                    "id": code,
                    "categoryCode": code,  # brands.py 필터 매칭용
                }
            )

        total = sum(n["count"] for n in nodes.values() if not n.get("parent"))
        return {
            "categories": categories,
            "total": total,
            "groupCount": len(categories),
        }
