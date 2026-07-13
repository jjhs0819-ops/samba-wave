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
# 필수고시정보 (소재/색상/제조자/제조국/취급주의/품질보증 + brndBcdVal=스타일코드)
MNDR_INFO_LIST = "/proxy/v1/pd/item/inf/mndrInfoList"

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

    async def search(
        self, keyword: str, max_count: int = 100, **filters: Any
    ) -> dict:
        """잡워커 공통 수집 인터페이스 — search_products 페이징 집계.

        keyword 가 그룹 URL(hi.thehyundai.com/search?q=..&flBrand=..&flCate=..)이면
        파라미터를 직접 추출 (워커가 q만 추출해 넘기는 경우 flBrand/flCate 는
        _search_kwargs 로 들어옴 — 둘 다 지원). 반환 {"products": [...], "total": N}.
        """
        kw = keyword or ""
        merged: dict[str, Any] = {}
        # 그룹 URL 직접 수신 폴백 — 워커 외 호출자(진단 스크립트 등) 대비
        if kw.startswith("http") and "thehyundai.com" in kw:
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(kw).query)
            kw = (qs.get("q") or qs.get("searchQuery") or [""])[0]
            for k in ("flBrand", "flCate", "sort"):
                v = (qs.get(k) or [""])[0]
                if v:
                    merged[k] = v
            if (qs.get("includeSoldOut") or [""])[0] == "1":
                merged["includeSoldOut"] = True
        # 워커 _search_kwargs — 유효한 키만 채택 (타 소싱처용 키 무시)
        for k in ("flBrand", "flCate", "sort", "target", "targetCode"):
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
        # 36건/페이지 — max_count 도달 또는 빈 페이지까지 순회 (상한 300페이지 가드)
        while len(products) < max_count and page <= 300:
            batch = await self.search_products(kw, page=page, size=36, **merged)
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
                break  # 전부 중복 → 사이트가 마지막 페이지를 반복 반환하는 경우 종료
            page += 1
        return {"products": products, "total": len(products)}

    async def get_detail(self, site_product_id: str, **_ignored: Any) -> dict:
        """잡워커 범용 상세조회 인터페이스 — get_product_detail 별칭."""
        return await self.get_product_detail(site_product_id)

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
            # stck/bnft/mndr 는 상호 독립 — 병렬 조회로 상세 1건 wall-clock 단축
            import asyncio as _asyncio

            need_stck = detail_data.get("uitmCombYn") == "1"
            stck_task = (
                self._get_uitm_stck_list(client, slitm_cd)
                if need_stck
                else _asyncio.sleep(0, result=None)
            )
            stck_list, max_bnft, mndr_info = await _asyncio.gather(
                stck_task,
                self._get_max_bnft_list(client, slitm_cd),
                self._get_mndr_info(client, slitm_cd),
            )
            if need_stck and stck_list is None:
                stck_list = []
            return self._build_detail(
                slitm_cd, detail_data, stck_list, max_bnft, mndr_info
            )

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
            # flBrand 다중 구분자는 | (파이프). 쉼표는 서버가 0건 반환 (2026-07-13 실측:
            # 101047,141300 → 0건 / 101047|141300 → 1,855건)
            params["flBrand"] = "|".join(str(b) for b in brand_ids if b)

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
        # 2026-07 사이트 변경: Referer 미포함 GET 은 /proxy/* 전체가 HTTP 500.
        # 값은 아무 URL 이나 통과하지만 자체 도메인 루트로 고정 (실측 2026-07-13).
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "follow_redirects": True,
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Referer": BASE_URL + "/",
                "Accept": "application/json",
            },
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

    async def _get_mndr_info(
        self, client: httpx.AsyncClient, slitm_cd: str
    ) -> Optional[dict]:
        """필수고시정보 — 실패해도 상세 자체는 유효하므로 None 허용."""
        return await self._fetch_json(client, MNDR_INFO_LIST, {"slitmCd": slitm_cd})

    # ──────────────────────────────────────────────────────────
    # internal — 정규화
    # ──────────────────────────────────────────────────────────

    # 고시 itstTitl 키워드 → 삼바 필드 매핑. 카테고리별 고시양식(의류/신발/가전)마다
    # itstCd 가 달라 코드 매칭 대신 제목 키워드 매칭 (앞선 키워드 우선).
    _MNDR_FIELD_KEYWORDS = (
        ("material", ("주소재", "소재", "재질")),
        ("color", ("색상",)),
        ("manufacturer", ("제조자", "수입자", "제조사", "판매자")),
        ("origin", ("제조국", "원산지")),
        ("care_instructions", ("취급시 주의사항", "취급주의", "세탁방법")),
        ("quality_guarantee", ("품질보증",)),
    )

    @classmethod
    def _extract_mndr_fields(cls, mndr_info: Optional[dict]) -> dict:
        """mndrInfoList 응답 → {material, color, manufacturer, origin,
        care_instructions, quality_guarantee, style_code} (없는 항목은 미포함)."""
        out: dict[str, str] = {}
        if not mndr_info:
            return out
        style = (mndr_info.get("brndBcdVal") or "").strip()
        if style:
            out["style_code"] = style
        for row in mndr_info.get("mndrInfoList") or []:
            title = (row.get("itstTitl") or "").strip()
            content = (row.get("itstCntn") or "").strip()
            if not title or not content:
                continue
            for field, keywords in cls._MNDR_FIELD_KEYWORDS:
                if field in out:
                    continue
                if any(kw in title for kw in keywords):
                    out[field] = content
                    break
        return out

    @staticmethod
    def _safe_int(v: Any) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _infer_sex(category_path: str, name: str) -> str:
        """성별 추정 — 더현대 API 에 성별 필드가 없어 카테고리 경로+상품명 키워드로
        폴백 추정 (ABC마트 선례와 동일한 값 체계: 여성용/남성용/남여공용/아동·주니어).
        아동 → 여성 → 남성 순 (유아동 카테고리에 여아/남아가 섞여 아동 우선,
        '우먼'에 '먼'이 포함되므로 여성을 남성보다 먼저 체크)."""
        t = f"{category_path} {name}".lower()
        if any(
            k in t
            for k in (
                "키즈",
                "kids",
                "유아",
                "아동",
                "주니어",
                "junior",
                "토들러",
                "베이비",
                "infant",
                "boys",
                "girls",
            )
        ):
            return "아동/주니어공용"
        if any(k in t for k in ("여성", "여아", "우먼", "women", "woman", "wmns")):
            return "여성용"
        if any(k in t for k in ("남성", "남아", "men", "man")):
            return "남성용"
        if any(k in t for k in ("유니섹스", "unisex", "공용")):
            return "남여공용"
        return ""

    # 이미지 리사이즈 — 파라미터 없으면 600×600 기본 서빙. 서버 원본이 커서
    # RS=1000x1000 이 실제 1000px 반환 (2026-07-13 실측, PDP 웹뷰는 600 사용).
    # 마켓 등록 화질 기준(SSG 권장 1000)에 맞춰 1000 고정.
    _IMG_RESIZE = "?RS=1000x1000"

    @classmethod
    def _to_image_url(cls, path: str) -> str:
        if not path:
            return ""
        if path.startswith("http"):
            url = path
        elif path.startswith("//"):
            url = f"https:{path}"
        else:
            if not path.startswith("/"):
                path = "/" + path
            url = f"{IMAGE_HOST}{path}"
        # 이미 쿼리가 있으면 그대로 (이중 부여 방지)
        if "?" in url:
            return url
        return url + cls._IMG_RESIZE

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
            # snake_case 별칭 — 잡워커 수집 루프가 sale_price/original_price/cost(snake)로 읽음.
            # cost 는 상세(new_cost=카드즉시할인가)가 정본이나, 상세 누락 시 폴백용으로 표시가 제공.
            "sale_price": bnft_prc or sell_prc,
            "original_price": sell_prc,
            "cost": bnft_prc or sell_prc,
            "free_shipping": item.get("freeDlvYn") == "1",
            "discountRate": cls._safe_int(
                item.get("bnftPrcRate") or item.get("salePct")
            ),
            "isSoldOut": ostk_yn == "1",
            "imageUrl": cls._to_image_url(item.get("itemImageUrl") or ""),
            "sourceUrl": f"{BASE_URL}/product/{slitm_cd}" if slitm_cd else "",
            # snake_case 별칭 — 잡워커가 source_url(snake)로 읽음 (미제공 시 원문링크 빈값)
            "source_url": f"{BASE_URL}/product/{slitm_cd}" if slitm_cd else "",
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
        mndr_info: Optional[dict] = None,
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
            # snake_case 별칭 — 잡워커 수집 루프 호환 (cost=new_cost 카드즉시할인가 정본)
            "sale_price": dc_prc or sell_prc,
            "original_price": csm_prc if csm_prc > 0 else sell_prc,
            "isSoldOut": detail_data.get("ostkYn") == "1",
            "options": options,
            "images": images,
            "category": category_path,
            "categoryCode": str(detail_data.get("itemDcsfCd") or "").strip(),
            "descriptionHtml": self._extract_description_html(detail_data),
            # snake_case 별칭 — 잡워커가 detail_html/detail_images/shipping_fee(snake)로 읽음.
            # 상세 이미지는 별도 컬럼이 없어 메인 이미지를 상세로 사용(ABC/GS 선례와 동일).
            "detail_html": self._extract_description_html(detail_data),
            "detail_images": images,
            "shipping_fee": self._safe_int(dlv_first.get("dlvCost")),
            "store": (detail_data.get("storeNm") or "").strip(),
            "freeShipping": dlv_first.get("dlvcPlcyBsicGbcd") == "01",
            "free_shipping": dlv_first.get("dlvcPlcyBsicGbcd") == "01",
            "shippingFee": self._safe_int(dlv_first.get("dlvCost")),
            "freeShippingThreshold": self._safe_int(dlv_first.get("baseFee")),
            "remoteAreaFee": self._safe_int(dlv_first.get("irgnMntrDlvCost")),
            "carrierName": (dlv_first.get("dsrvDlvcoNm") or "").strip(),
            "openMarket": detail_data.get("openMktItemYn") == "1",
            "luxury": brnd_info.get("luitYn") == "1",
            "reservation": detail_data.get("hdmalRsvSellYn") == "1",
            "loyaltyPoints": self._safe_int(bnft_info.get("upntAcmPnt")),
            "sourceUrl": f"{BASE_URL}/product/{slitm_cd}",
            "source_url": f"{BASE_URL}/product/{slitm_cd}",
            "itemGbcd": detail_data.get("itemGbcd"),
            "itemGbPtcGbCd": detail_data.get("itemGbPtcGbCd"),
            # 성별 — API 무필드, 카테고리+상품명 추정 (빈값이면 워커가 남녀공용 기본)
            "sex": self._infer_sex(
                category_path, (detail_data.get("slitmNm") or "")
            ),
            # 필수고시 — material/color/manufacturer/origin/care_instructions/
            # quality_guarantee/style_code (잡워커 product_data 가 그대로 저장)
            **self._extract_mndr_fields(mndr_info),
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
