"""신세계백화점(department.ssg.com) 소싱용 웹 스크래핑 클라이언트 - httpx 기반.

주의: proxy/ssg.py는 판매처(마켓) 등록용 Open API 클라이언트이므로,
소싱(상품 수집)용은 이 파일에서 별도로 관리한다.

소싱 대상:
  - https://department.ssg.com/ (신세계백화점 온라인전용 상품만 취급)
  - siteNo=6009 (신세계백화점 고정)
  - 일반 SSG.COM 마켓플레이스 판매자 상품 제외

SSG 사이트 정보:
  - 검색: https://department.ssg.com/search?query={keyword}&page={n}
  - 상세: https://department.ssg.com/item/itemView.ssg?itemId={13자리}&siteNo=6009
  - 이미지 CDN: sitem.ssgcdn.com

파싱 전략:
  - 검색 결과: HTML 내 <script id="__NEXT_DATA__"> 태그 JSON 파싱
               queries → fetchSearchItemListArea → ITEM_UNIT_LIST → dataList
  - 상세 조회: HTML 내 var resultItemObj / uitemObjList JS 변수 파싱 (1순위)
               og: 메타태그 + CSS 패턴 폴백 (2순위)
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
    """신세계백화점(department.ssg.com) 소싱용 웹 스크래핑 클라이언트 (검색, 상세).

    신세계백화점 온라인 전용 상품만 수집한다 (siteNo=6009).
    일반 SSG.COM 마켓플레이스 판매자 상품은 수집하지 않는다.
    """

    BASE = "https://department.ssg.com"
    SEARCH_URL = "https://department.ssg.com/search"
    ITEM_URL = "https://department.ssg.com/item/itemView.ssg"
    SITE_NO = "6009"

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

    def __init__(self, cookie: str = "", *, proxy_url: str | None = None) -> None:
        """cookie가 있으면 로그인 상태로 최대혜택가 정밀 계산 가능.
        proxy_url이 있으면 SSG 차단 우회에 사용한다.
        """
        from backend.core.config import settings

        self._timeout = httpx.Timeout(settings.http_timeout_default, connect=10.0)
        self.cookie = cookie
        self.proxy_url = proxy_url

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
        _shared_client: Optional[httpx.AsyncClient] = None,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """신세계백화점 브랜드 검색.

        1단계: keyword로 검색 → 브랜드 필터에서 keyword로 시작하는 브랜드 ID 전부 수집
        2단계: 수집된 repBrandId를 파이프(|)로 결합한 URL로 상품 수집

        예) keyword='아디다스' → 아디다스|아디다스오리지널스|아디다스키즈|아디다스골프
        _shared_client: 외부에서 공유 클라이언트를 넘기면 TCP 연결 재사용 (대량 수집 성능 향상)
        """
        logger.info(f'[SSG] 검색 시작: "{keyword}" (page={page})')

        _client_kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "follow_redirects": True,
        }
        if self.proxy_url:
            _client_kwargs["proxy"] = self.proxy_url

        async def _run(client: httpx.AsyncClient) -> list[dict[str, Any]]:
            # 1단계: page=1로 브랜드 필터 목록 조회
            if page == 1:
                first_url = f"{self.SEARCH_URL}?query={quote(keyword)}&page=1"
                resp = await client.get(first_url, headers=self._headers())
                if resp.status_code in (429, 403):
                    raise RateLimitError(int(resp.status_code))
                if resp.status_code != 200:
                    logger.warning(f"[SSG] 검색 페이지 HTTP {resp.status_code}")
                    return []
                first_html = resp.text
                brand_ids = self._extract_matching_brand_ids(first_html, keyword)
                logger.info(f"[SSG] 매칭 브랜드: {len(brand_ids)}개 → {brand_ids}")
            else:
                # page > 1: filters에서 brand_ids 전달받음
                brand_ids = filters.get("brand_ids", [])
                first_html = None

            # 2단계: 브랜드 필터 적용 URL로 수집
            search_url = f"{self.SEARCH_URL}?query={quote(keyword)}&page={page}"
            if brand_ids:
                search_url += f"&repBrandId={'|'.join(brand_ids)}"

            # page=1은 이미 가져온 HTML 재사용, page>1은 새로 요청
            if page == 1 and brand_ids:
                resp2 = await client.get(search_url, headers=self._headers())
                if resp2.status_code in (429, 403):
                    raise RateLimitError(int(resp2.status_code))
                html = resp2.text if resp2.status_code == 200 else first_html
            elif page == 1:
                html = first_html
            else:
                resp = await client.get(search_url, headers=self._headers())
                if resp.status_code in (429, 403):
                    raise RateLimitError(int(resp.status_code))
                if resp.status_code != 200:
                    return []
                html = resp.text

            products = self._parse_search_html(html, keyword)
            logger.info(
                f'[SSG] 검색 완료: "{keyword}" page={page} -> {len(products)}개'
            )
            return products

        try:
            if _shared_client:
                return await _run(_shared_client)
            async with httpx.AsyncClient(**_client_kwargs) as client:
                return await _run(client)

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[SSG] 검색 타임아웃: {keyword}")
            return []
        except Exception as e:
            logger.error(f"[SSG] 검색 실패: {keyword} — {e}")
            return []

    def _extract_matching_brand_ids(self, html: str, keyword: str) -> list[str]:
        """__NEXT_DATA__에서 keyword로 시작하는 브랜드 ID 목록 추출.

        예) keyword='아디다스' → ['2000000507', '2000000509', '2000047294', '2000000510']
        """
        m = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            return []

        try:
            next_data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []

        queries = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )

        brand_ids: list[str] = []
        seen: set[str] = set()

        for q in queries:
            if "useTemplateFilterQuery" not in (q.get("queryKey") or []):
                continue
            filters_data = q.get("state", {}).get("data") or []
            for f in filters_data:
                if f.get("filterType") != "brandFilter":
                    continue
                for unit in f.get("unitList", []):
                    for item in unit.get("dataList", []):
                        name = item.get("name", "")
                        value = item.get("value", "")
                        # keyword로 시작하는 브랜드 전부 선택
                        if name.startswith(keyword) and value and value not in seen:
                            brand_ids.append(value)
                            seen.add(value)

        return brand_ids

    async def get_brand_filters(self, keyword: str) -> list[dict[str, Any]]:
        """키워드 검색 결과의 브랜드 필터 목록 전체 반환.

        SSG 검색 페이지 좌측 '브랜드' 섹션의 모든 항목을 반환한다.
        반환값: [{name, value, count}]
        """
        _client_kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "follow_redirects": True,
        }
        if self.proxy_url:
            _client_kwargs["proxy"] = self.proxy_url

        search_url = f"{self.SEARCH_URL}?query={quote(keyword)}&page=1"
        try:
            async with httpx.AsyncClient(**_client_kwargs) as client:
                resp = await client.get(search_url, headers=self._headers())
                if resp.status_code in (429, 403):
                    raise RateLimitError(int(resp.status_code))
                if resp.status_code != 200:
                    logger.warning(f"[SSG] 브랜드 스캔 HTTP {resp.status_code}")
                    return []
                html = resp.text
        except RateLimitError:
            raise
        except Exception as e:
            logger.error(f"[SSG] 브랜드 스캔 실패: {keyword} — {e}")
            return []

        return self._extract_all_brand_filters(html)

    def _extract_all_brand_filters(self, html: str) -> list[dict[str, Any]]:
        """__NEXT_DATA__에서 브랜드 필터 전체 목록 추출.

        반환값: [{name: str, value: str, count: int}]
        """
        m = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            return []

        try:
            next_data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []

        queries = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )

        brands: list[dict[str, Any]] = []
        seen: set[str] = set()

        for q in queries:
            if "useTemplateFilterQuery" not in (q.get("queryKey") or []):
                continue
            filters_data = q.get("state", {}).get("data") or []
            for f in filters_data:
                if f.get("filterType") != "brandFilter":
                    continue
                for unit in f.get("unitList", []):
                    for item in unit.get("dataList", []):
                        name = item.get("name", "")
                        value = item.get("value", "")
                        count = int(item.get("count", 0))
                        if value and value not in seen:
                            brands.append(
                                {"name": name, "value": value, "count": count}
                            )
                            seen.add(value)

        return brands

    def _parse_search_html(self, html: str, keyword: str) -> list[dict[str, Any]]:
        """검색 결과 HTML에서 상품 정보 추출.

        1순위: Next.js script 태그 내 dataList JSON 파싱
        2순위: 상품 링크 + HTML 블록 파싱 폴백
        """
        # 1순위: dataList JSON 추출 (ITEM_UNIT_LIST 블록)
        products = self._parse_datalist_json(html)
        if products:
            return products

        # 2순위: 상품 링크 기반 폴백
        logger.warning(f"[SSG] dataList 파싱 실패, 폴백 파싱 시도: {keyword}")
        return self._parse_search_blocks(html)

    def _parse_datalist_json(self, html: str) -> list[dict[str, Any]]:
        """department.ssg.com 검색 HTML의 __NEXT_DATA__ script 태그에서 상품 목록 추출.

        구조: <script id="__NEXT_DATA__" type="application/json">{...}</script>
             → props.pageProps.dehydratedState.queries
             → [fetchSearchItemListArea].state.data.areaList
             → [unitType==ITEM_UNIT_LIST].dataList
        """
        # __NEXT_DATA__ script 태그 추출
        m = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            return []

        try:
            next_data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []

        queries = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )

        data_list: list[dict] = []
        for q in queries:
            qkey = q.get("queryKey") or []
            if "fetchSearchItemListArea" not in qkey:
                continue
            area_list = q.get("state", {}).get("data", {}).get("areaList", [])
            for area in area_list:
                if area.get("unitType") == "ITEM_UNIT_LIST":
                    data_list = area.get("dataList") or []
                    break
            if data_list:
                break

        if not data_list:
            return []

        products: list[dict[str, Any]] = []
        seen: set[str] = set()

        for item in data_list:
            item_id = str(item.get("itemId", ""))
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)

            item_name = item.get("itemName", "").strip()
            if not item_name:
                continue

            # 가격 파싱 (문자열 "135,360" → 정수 135360)
            sale_price = self._safe_int(
                str(item.get("finalPrice", "") or item.get("sellprc", 0)).replace(
                    ",", ""
                )
            )
            original_price = (
                self._safe_int(
                    str(
                        item.get("strikeOutPrice", "") or item.get("norprc", 0)
                    ).replace(",", "")
                )
                or sale_price
            )

            # 할인율 (문자열 "20" 또는 "20%" → 정수 20)
            discount_rate_raw = str(item.get("discountRate", "0")).replace("%", "")
            discount_rate = self._safe_int(discount_rate_raw)

            # 이미지 URL
            image = self._normalize_image(item.get("itemImgUrl", ""))

            # 무료배송 여부
            shipping_list = (
                item.get("shippingCostInfo") or item.get("itemFeatureList") or []
            )
            free_shipping = any(
                "무료배송" in str(s.get("text", "")) for s in shipping_list
            )

            # 품절 여부
            is_sold_out = bool(item.get("soldOutMessage", "").strip())

            # itemUrl이 department.ssg.com 도메인인지 확인
            item_url = (
                item.get("itemDetailLink")
                or item.get("itemUrl")
                or (f"{self.ITEM_URL}?itemId={item_id}&siteNo={self.SITE_NO}")
            )

            products.append(
                {
                    "siteProductId": item_id,
                    "goodsNo": item_id,
                    "name": item_name,
                    "brand": item.get("brandName", ""),
                    "brandEngNm": item.get("brandEngNm", ""),
                    "salePrice": sale_price,
                    "originalPrice": original_price,
                    "discountRate": discount_rate,
                    "image": image,
                    "freeShipping": free_shipping,
                    "isSoldOut": is_sold_out,
                    "sourceUrl": item_url,
                    "siteNo": item.get("siteNo", self.SITE_NO),
                    "salestrNo": str(item.get("salestrNo", "")),
                }
            )

        return products

    def _parse_search_blocks(self, html: str) -> list[dict[str, Any]]:
        """검색 결과 HTML 블록에서 상품 정보 추출 (폴백)."""
        products: list[dict[str, Any]] = []
        seen: set[str] = set()

        item_pattern = re.compile(
            r"itemView\.ssg\?itemId=(\d{10,13})",
            re.IGNORECASE,
        )

        for item_id in item_pattern.findall(html):
            if item_id in seen:
                continue
            seen.add(item_id)
            products.append(
                {
                    "siteProductId": item_id,
                    "goodsNo": item_id,
                    "name": "",
                    "brand": "",
                    "salePrice": 0,
                    "originalPrice": 0,
                    "image": "",
                    "isSoldOut": False,
                    "sourceUrl": f"{self.ITEM_URL}?itemId={item_id}",
                }
            )

        return products

    # ------------------------------------------------------------------
    # 상세 조회
    # ------------------------------------------------------------------

    async def get_product_detail(
        self,
        item_id: str,
        refresh_only: bool = False,
        _shared_client: Optional[httpx.AsyncClient] = None,
    ) -> dict[str, Any]:
        """SSG 상품 상세 정보 조회.

        1순위: var resultItemObj JS 변수 파싱 (가장 안정적)
        2순위: og: 메타태그 + CSS 클래스 패턴 폴백

        Args:
            item_id: SSG 상품 ID (13자리 숫자)
            refresh_only: True이면 가격/재고만 빠르게 갱신
            _shared_client: TCP 연결 재사용용 공유 클라이언트 (대량 수집 성능 향상)

        Returns:
            표준 상품 상세 dict (무신사 프록시 반환 형식과 동일)

        Raises:
            RateLimitError: 429/403 응답 시
        """
        url = f"{self.ITEM_URL}?itemId={item_id}&siteNo={self.SITE_NO}"
        logger.info(f"[SSG] 상세 조회: {item_id}")

        _client_kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "follow_redirects": True,
        }
        if self.proxy_url:
            _client_kwargs["proxy"] = self.proxy_url

        async def _fetch(client: httpx.AsyncClient) -> str:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code in (429, 403):
                retry_after = int(resp.headers.get("Retry-After", "60"))
                logger.warning(f"[SSG] 차단 감지 HTTP {resp.status_code}: {item_id}")
                raise RateLimitError(resp.status_code, retry_after)
            if resp.status_code != 200:
                logger.warning(f"[SSG] 상세 페이지 HTTP {resp.status_code}: {item_id}")
                return ""
            return resp.text

        try:
            if _shared_client:
                html = await _fetch(_shared_client)
            else:
                async with httpx.AsyncClient(**_client_kwargs) as client:
                    html = await _fetch(client)

            if not html:
                return {}

            # 1순위: resultItemObj JS 변수 파싱
            result = self._parse_result_item_obj(html, item_id, refresh_only)
            if result:
                logger.info(f"[SSG] resultItemObj 파싱 성공: {item_id}")
                return result

            # 2순위: 메타태그 + CSS 패턴 폴백
            logger.warning(f"[SSG] resultItemObj 없음, 폴백 파싱: {item_id}")
            return self._parse_detail_fallback(html, item_id)

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[SSG] 상세 조회 타임아웃: {item_id}")
            return {}
        except Exception as e:
            logger.error(f"[SSG] 상세 조회 실패: {item_id} — {e}")
            return {}

    def _parse_result_item_obj(
        self, html: str, item_id: str, refresh_only: bool
    ) -> dict[str, Any]:
        """var resultItemObj JS 변수에서 상품 정보 추출 (1순위).

        SSG HTML의 resultItemObj는 parseInt() 등 JS 표현식이 포함된 객체 리터럴이므로
        JSON 파싱 대신 개별 필드 직접 추출 방식을 사용한다.
        """
        # resultItemObj 블록 추출 (브라켓 카운터)
        start_marker = re.search(r"var\s+resultItemObj\s*=\s*\{", html)
        if not start_marker:
            return {}

        start = start_marker.end() - 1  # '{' 포함
        depth = 0
        end = start
        i = start
        while i < len(html):
            ch = html[i]
            if ch == "\\":
                i += 2
                continue
            if ch in ('"', "'"):
                q = ch
                i += 1
                while i < len(html) and html[i] != q:
                    if html[i] == "\\":
                        i += 1
                    i += 1
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1

        if end <= start:
            return {}

        js_block = html[start:end]

        # 개별 필드 추출 헬퍼 사용
        def get_str(key: str) -> str:
            return self._extract_js_str_field(js_block, key)

        def get_num(key: str) -> int:
            return self._extract_js_num_field(js_block, key)

        # 필수 필드 확인
        name = get_str("itemNm")
        if not name:
            logger.warning(f"[SSG] resultItemObj에서 itemNm 추출 실패: {item_id}")
            return {}

        # uitemObjList JSON 추출 (별도 파싱)
        uitem_list = self._extract_uitem_list(js_block)

        obj = {
            "itemNm": name,
            "repBrandNm": get_str("repBrandNm") or get_str("brandNm"),
            "repBrandId": get_str("repBrandId") or get_str("brandId"),
            "sellprc": get_num("sellprc"),
            "bestAmt": get_num("bestAmt"),
            "soldOut": get_str("soldOut"),
            "stdCtgLclsNm": get_str("stdCtgLclsNm"),
            "stdCtgMclsNm": get_str("stdCtgMclsNm"),
            "stdCtgSclsNm": get_str("stdCtgSclsNm"),
            "stdCtgDclsNm": get_str("stdCtgDclsNm"),
            "dispCtgNm": get_str("dispCtgNm"),
            "itemImgUrl": get_str("itemImgUrl"),
            "shppTypeDtlCd": get_str("shppTypeDtlCd"),
            "deliType": get_str("deliType"),
            "uitemObjList": uitem_list,
        }

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

        # 기본 필드
        name = obj.get("itemNm", "").strip()
        brand = obj.get("repBrandNm") or obj.get("brandNm", "")
        brand_code = str(obj.get("repBrandId") or obj.get("brandId", ""))

        # department.ssg.com: resultItemObj.sellprc = 정상가 (할인 전 원가)
        # 실제 할인가(최적가)는 HTML cdtl_price point 클래스에 렌더링됨
        original_price = self._safe_int(obj.get("sellprc", 0))
        sale_price_html = self._extract_dept_sale_price(html)
        sell_price = sale_price_html if sale_price_html else original_price

        # 할인율 계산
        discount_rate = 0
        if original_price > 0 and sell_price < original_price:
            discount_rate = round((original_price - sell_price) / original_price * 100)

        # 카드혜택가 우선 (JS bestAmt는 일반 최적가이므로 카드혜택가보다 높을 수 있음)
        _card_price = self._extract_card_benefit_price(html)
        best_amt = _card_price or self._safe_int(obj.get("bestAmt", 0)) or sell_price

        # 품절 판단: soldOut 필드 (Y/N)
        is_sold_out = str(obj.get("soldOut", "N")).upper() == "Y"

        # 카테고리: 표준 카테고리 4계층
        cat1 = obj.get("stdCtgLclsNm", "")  # 대분류 (예: 패션의류)
        cat2 = obj.get("stdCtgMclsNm", "")  # 중분류 (예: 여성브랜드패션)
        cat3 = obj.get("stdCtgSclsNm", "")  # 소분류 (예: 패션잡화)
        cat4 = obj.get("stdCtgDclsNm", "")  # 세분류 (예: 슈즈)
        # 전시 카테고리명도 보조로 활용
        disp_ctg_nm = obj.get("dispCtgNm", "")

        category_levels = [c for c in [cat1, cat2, cat3, cat4] if c]
        if not category_levels and disp_ctg_nm:
            category_levels = [disp_ctg_nm]
        category_str = " > ".join(category_levels)

        # 이미지: itemImgUrl 에서 _i1_36.jpg → _i{N}_1200.jpg 패턴으로 재구성
        images = self._build_images_from_base_url(
            obj.get("itemImgUrl", ""), item_id, html
        )

        # 상세 이미지 (갱신 모드에서는 스킵)
        detail_images: list[str] = []
        detail_html = ""
        if not refresh_only:
            detail_html, detail_images = self._parse_detail_content(html)
            # 이미지 9장 미만 시 상세 이미지로 보충 (무신사 동일 패턴)
            if len(images) < 9 and detail_images:
                existing = set(images)
                for di in detail_images:
                    if di not in existing and len(images) < 9:
                        images.append(di)
                        existing.add(di)

        # 옵션/재고: uitemObjList 파싱
        options = self._parse_uitem_options(obj)
        # 품절 재확인: 모든 옵션이 품절이면 품절
        if options and all(opt.get("isSoldOut", False) for opt in options):
            is_sold_out = True

        # 배송 정보
        shpp_type = str(obj.get("shppTypeDtlCd", ""))
        deli_type = str(obj.get("deliType", ""))
        # shppTypeDtlCd: 22=무료배송, deliType: 10=일반, 20=당일
        free_shipping = shpp_type in ("22",) or bool(
            re.search(r"무료배송", html[:5000])
        )
        same_day_delivery = deli_type == "20" or bool(
            re.search(r"(?:당일배송|쓱배송|새벽배송)", html[:5000])
        )

        # 판매 상태
        sale_status = "sold_out" if is_sold_out else "in_stock"

        return {
            "id": f"col_ssg_{item_id}_{timestamp}",
            "sourceSite": "SSG",
            "siteProductId": str(item_id),
            "sourceUrl": f"{self.BASE}/item/itemView.ssg?itemId={item_id}&siteNo={self.SITE_NO}",
            "name": name,
            "nameEn": "",
            "nameJa": "",
            "brand": brand,
            "brandCode": brand_code,
            "category": category_str,
            "category1": cat1,
            "category2": cat2,
            "category3": cat3,
            "category4": cat4,
            "images": images[:9],
            "detailImages": detail_images,
            "detailHtml": detail_html,
            "options": options,
            "originalPrice": original_price,
            "salePrice": sell_price,
            "bestBenefitPrice": best_amt,
            "couponPrice": best_amt,
            "memberDiscountRate": 0,
            "discountRate": discount_rate,
            "origin": "",
            "material": "",
            "manufacturer": "",
            "color": "",
            "sizeInfo": "",
            "care_instructions": "",
            "quality_guarantee": "",
            "season": "",
            "style_code": "",
            "sex": "",
            "brandNation": "",
            "kcCert": "",
            "tags": [],
            "isOutOfStock": is_sold_out,
            "isSale": not is_sold_out,
            "saleStatus": sale_status,
            "freeShipping": free_shipping,
            "sameDayDelivery": same_day_delivery,
            "status": "collected",
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

    def _parse_uitem_options(self, obj: dict) -> list[dict[str, Any]]:
        """uitemObjList에서 옵션/재고 파싱."""
        options: list[dict[str, Any]] = []
        uitem_list = obj.get("uitemObjList") or []

        for uitem in uitem_list:
            uitem_id = uitem.get("_uitemId") or uitem.get("uitemId", "")
            # 00000은 옵션 없는 단일 상품 더미 — 실제 옵션이 있으면 스킵
            if uitem_id == "00000" and len(uitem_list) > 1:
                continue

            opt_name = uitem.get("name", "").strip()
            stock = self._safe_int(uitem.get("stock", 0))
            is_soldout = uitem.get("isSoldOut", False) or stock == 0
            sell_price = self._safe_int(uitem.get("price", 0))

            options.append(
                {
                    "name": opt_name,
                    "price": sell_price,
                    "stock": stock,
                    "isSoldOut": bool(is_soldout),
                }
            )

        return options

    def _build_images_from_base_url(
        self, base_img_url: str, item_id: str, html: str
    ) -> list[str]:
        """resultItemObj.itemImgUrl에서 상품 이미지 목록 재구성.

        패턴: https://sitem.ssgcdn.com/{path}/item/{itemId}_i{N}_{size}.jpg
        base_img_url 예: .../1000626844250_i1_36.jpg  → _i1_1200.jpg 로 교체 후 i1~i9 시도
        """
        images: list[str] = []

        if base_img_url:
            # _i1_36.jpg → _i1_1200.jpg 변환
            high_res = re.sub(r"_i1_\d+\.jpg", "_i1_1200.jpg", base_img_url)
            if high_res:
                images.append(self._normalize_image(high_res))

            # i2~i9 이미지 URL 생성 (CDN 경로 동일, 인덱스만 변경)
            base_path = re.sub(r"_i\d+_\d+\.jpg", "", base_img_url)
            for i in range(2, 10):
                candidate = f"{base_path}_i{i}_1200.jpg"
                images.append(self._normalize_image(candidate))

        # HTML에서 sitem.ssgcdn.com 이미지 수집으로 보충
        ssgcdn_pattern = re.compile(
            r'["\']?(https://sitem\.ssgcdn\.com/[^"\']+_i\d+_(?:1200|500)\.jpg)["\']?',
            re.IGNORECASE,
        )
        seen = set(images)
        for m in ssgcdn_pattern.finditer(html):
            img = self._normalize_image(m.group(1))
            if img and img not in seen and f"/{item_id}_" in img:
                images.append(img)
                seen.add(img)
                if len(images) >= 9:
                    break

        return [i for i in images if i][:9]

    def _parse_detail_content(self, html: str) -> tuple[str, list[str]]:
        """상세 설명 영역 HTML 및 이미지 추출."""
        detail_html = ""
        detail_images: list[str] = []

        # 상세 설명 영역 추출
        detail_area = re.search(
            r'(?:id="cdtl_desc"|id="detail_cont"|class="[^"]*cdtl_desc[^"]*")[^>]*>(.*?)(?=<div[^>]+(?:id|class)="[^"]*(?:cdtl_review|cdtl_qna|cdtl_notice|footer)[^"]*")',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if detail_area:
            detail_html = detail_area.group(1)
            img_pat = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
            for m in img_pat.finditer(detail_html):
                img = self._normalize_image(m.group(1))
                if img and img not in detail_images:
                    detail_images.append(img)

        return detail_html, detail_images

    def _parse_detail_fallback(self, html: str, item_id: str) -> dict[str, Any]:
        """resultItemObj 없을 때 메타태그 + CSS 패턴 폴백."""
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

        name = self._extract_meta(html, "og:title") or ""
        name = name.replace(" - SSG.COM", "").strip()
        thumbnail = self._normalize_image(self._extract_meta(html, "og:image") or "")

        sale_price = self._parse_sale_price(html)
        original_price = self._parse_original_price(html) or sale_price
        best_benefit_price = self._parse_best_benefit_price(html) or sale_price
        brand = self._parse_brand(html)
        category_levels = self._parse_category(html)

        images = [thumbnail] if thumbnail else []
        ssgcdn_pat = re.compile(
            r'https://sitem\.ssgcdn\.com/[^"\']+_i\d+_(?:1200|500)\.jpg',
            re.IGNORECASE,
        )
        seen_imgs = set(images)
        for m in ssgcdn_pat.finditer(html):
            img = m.group(0)
            if img not in seen_imgs and f"/{item_id}_" in img:
                images.append(img)
                seen_imgs.add(img)
                if len(images) >= 9:
                    break

        options = self._parse_options(html)
        is_out_of_stock = self._check_sold_out(html, options)

        return {
            "id": f"col_ssg_{item_id}_{timestamp}",
            "sourceSite": "SSG",
            "siteProductId": str(item_id),
            "sourceUrl": f"{self.BASE}/item/itemView.ssg?itemId={item_id}&siteNo={self.SITE_NO}",
            "name": name,
            "nameEn": "",
            "nameJa": "",
            "brand": brand,
            "brandCode": "",
            "category": " > ".join(category_levels),
            "category1": category_levels[0] if len(category_levels) > 0 else "",
            "category2": category_levels[1] if len(category_levels) > 1 else "",
            "category3": category_levels[2] if len(category_levels) > 2 else "",
            "category4": category_levels[3] if len(category_levels) > 3 else "",
            "images": images[:9],
            "detailImages": [],
            "detailHtml": "",
            "options": options,
            "originalPrice": original_price,
            "salePrice": sale_price,
            "bestBenefitPrice": best_benefit_price,
            "couponPrice": best_benefit_price,
            "memberDiscountRate": 0,
            "discountRate": 0,
            "origin": "",
            "material": "",
            "manufacturer": "",
            "color": "",
            "sizeInfo": "",
            "care_instructions": "",
            "quality_guarantee": "",
            "season": "",
            "style_code": "",
            "sex": "",
            "brandNation": "",
            "kcCert": "",
            "tags": [],
            "isOutOfStock": is_out_of_stock,
            "isSale": not is_out_of_stock,
            "saleStatus": "sold_out" if is_out_of_stock else "in_stock",
            "freeShipping": bool(re.search(r"무료배송", html[:5000])),
            "sameDayDelivery": bool(
                re.search(r"(?:당일배송|쓱배송|새벽배송)", html[:5000])
            ),
            "status": "collected",
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

    # ------------------------------------------------------------------
    # 폴백 가격/정보 파싱 헬퍼 (CSS 클래스 기반)
    # ------------------------------------------------------------------

    def _parse_sale_price(self, html: str) -> int:
        """판매가 추출 (폴백).

        우선순위:
          1순위: 카드혜택가 (존재할 때만)
          2순위: meta product:price:amount
          3순위: CSS 패턴 (ssg_price, sale_price, cdtl_price)
        """
        # 1순위: 카드혜택가
        card_price = self._extract_card_benefit_price(html)
        if card_price > 0:
            return card_price

        # 2순위: meta 태그
        price_meta = self._extract_meta(html, "product:price:amount")
        if price_meta:
            price = self._safe_int(re.sub(r"[^\d]", "", price_meta))
            if price > 0:
                return price

        # 3순위: CSS 패턴
        for pattern in [
            r'class="[^"]*ssg_price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*sale[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*cdtl_price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price
        return 0

    def _parse_original_price(self, html: str) -> int:
        """정상가 추출 (폴백)."""
        for pattern in [
            r'class="[^"]*old[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*org[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*cdtl_old_price[^"]*"[^>]*>.*?(\d[\d,]+)',
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price
        return 0

    def _parse_best_benefit_price(self, html: str) -> int:
        """최대혜택가 추출 (폴백)."""
        for pattern in [
            r'class="[^"]*best[_-]?benefit[^"]*"[^>]*>.*?(\d[\d,]+)',
            r'class="[^"]*coupon[_-]?price[^"]*"[^>]*>.*?(\d[\d,]+)',
            r"(?:최대혜택가|쿠폰적용가)[^<]*?(\d[\d,]+)",
        ]:
            price = self._extract_price(html, pattern)
            if price > 0:
                return price
        return 0

    def _parse_brand(self, html: str) -> str:
        """브랜드명 추출 (폴백)."""
        for pattern in [
            r'class="[^"]*cdtl_brand[^"]*"[^>]*>([^<]+)',
            r'class="[^"]*brand[_-]?name[^"]*"[^>]*>([^<]+)',
        ]:
            brand = self._extract_text(html, pattern)
            if brand:
                return brand.strip()
        return ""

    def _parse_category(self, html: str) -> list[str]:
        """카테고리 경로 추출 (폴백)."""
        # 브레드크럼에서 추출
        breadcrumb_pattern = re.compile(
            r'class="[^"]*(?:breadcrumb|location)[^"]*"[^>]*>(.*?)</(?:ul|ol|div|nav)',
            re.DOTALL | re.IGNORECASE,
        )
        bc = breadcrumb_pattern.search(html)
        if bc:
            cats = [
                t.strip()
                for t in re.findall(r"<a[^>]*>([^<]+)</a>", bc.group(1))
                if t.strip() and t.strip() not in ("홈", "HOME", "SSG.COM")
            ]
            if cats:
                return cats[:4]
        return []

    def _parse_options(self, html: str) -> list[dict[str, Any]]:
        """옵션 추출 (폴백)."""
        options: list[dict[str, Any]] = []

        # JSON 옵션 데이터
        opt_pattern = re.compile(
            r"(?:optionData|itemOptList|optionList)\s*[=:]\s*(\[.*?\]);",
            re.DOTALL,
        )
        j = opt_pattern.search(html)
        if j:
            try:
                opt_list = json.loads(j.group(1))
                for opt in opt_list:
                    opt_name = (opt.get("optNm", "") or opt.get("name", "")).strip()
                    if not opt_name:
                        continue
                    stock = self._safe_int(opt.get("stockQty", 0))
                    is_soldout = opt.get("soldOutYn", "N") == "Y" or stock == 0
                    options.append(
                        {
                            "name": opt_name,
                            "price": self._safe_int(opt.get("sellprc", 0)),
                            "stock": stock,
                            "isSoldOut": bool(is_soldout),
                        }
                    )
                return options
            except (json.JSONDecodeError, TypeError):
                pass

        # select 박스 폴백
        option_area = re.search(
            r'class="[^"]*option[_-]?select[^"]*"[^>]*>(.*?)</select>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if option_area:
            for value, text in re.findall(
                r'<option[^>]+value="([^"]*)"[^>]*>([^<]+)</option>',
                option_area.group(1),
                re.IGNORECASE,
            ):
                text = text.strip()
                if not value or "선택" in text:
                    continue
                is_soldout = "품절" in text
                options.append(
                    {
                        "name": text,
                        "price": 0,
                        "stock": 0 if is_soldout else 1,
                        "isSoldOut": is_soldout,
                    }
                )

        return options

    def _check_sold_out(self, html: str, options: list[dict]) -> bool:
        """품절 여부 판단 (폴백)."""
        if re.search(r'class="[^"]*sold[_-]?out[^"]*"', html, re.IGNORECASE):
            return True
        if options and all(opt.get("isSoldOut", False) for opt in options):
            return True
        return False

    # ------------------------------------------------------------------
    # 공통 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_js_str_field(js_block: str, key: str) -> str:
        """JS 객체 블록에서 문자열 필드 추출. 단일/이중따옴표 모두 지원."""
        pattern = rf"[,\{{]\s*{re.escape(key)}\s*:\s*['\"]([^'\"]*)['\"]"
        m = re.search(pattern, js_block)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_js_num_field(js_block: str, key: str) -> int:
        """JS 객체 블록에서 숫자 필드 추출. parseInt() 표현식도 지원."""
        # parseInt('25480', 10) 또는 25480 또는 '25480'
        pattern = rf"[,\{{]\s*{re.escape(key)}\s*:\s*(?:parseInt\s*\(\s*['\"](\d+)['\"]|['\"](\d+)['\"]|(\d+))"
        m = re.search(pattern, js_block)
        if m:
            val = m.group(1) or m.group(2) or m.group(3)
            return int(val) if val else 0
        return 0

    def _extract_uitem_list(self, js_block: str) -> list[dict]:
        """uitemObjList 배열에서 옵션 목록 추출."""
        # uitemObjList 배열 시작 탐색
        m = re.search(r"uitemObjList\s*:\s*\[", js_block)
        if not m:
            return []

        start = m.end() - 1  # '[' 포함
        depth = 0
        end = start
        i = start
        while i < len(js_block):
            ch = js_block[i]
            if ch == "\\":
                i += 2
                continue
            if ch in ('"', "'"):
                q = ch
                i += 1
                while i < len(js_block) and js_block[i] != q:
                    if js_block[i] == "\\":
                        i += 1
                    i += 1
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1

        if end <= start:
            return []

        array_block = js_block[start:end]

        # 각 객체({...}) 추출
        items = []
        obj_pattern = re.compile(r"\{[^{}]+\}", re.DOTALL)
        for obj_m in obj_pattern.finditer(array_block):
            block = obj_m.group(0)

            def gs(k: str) -> str:
                pm = re.search(
                    rf"[,\{{]\s*{re.escape(k)}\s*:\s*['\"]([^'\"]*)['\"]", block
                )
                return pm.group(1).strip() if pm else ""

            def gn(k: str) -> int:
                pm = re.search(
                    rf"[,\{{]\s*{re.escape(k)}\s*:\s*(?:parseInt\s*\(\s*['\"](\d+)['\"]|['\"](\d+)['\"]|(\d+))",
                    block,
                )
                if pm:
                    v = pm.group(1) or pm.group(2) or pm.group(3)
                    return int(v) if v else 0
                return 0

            # isSoldout 불리언
            soldout_m = re.search(r"isSoldout\s*:\s*(true|false)", block)
            is_soldout = soldout_m.group(1) == "true" if soldout_m else False

            uitem_id = gs("uitemId")
            stock = gn("usablInvQty") or gn("displInvQty")
            if stock == 0 and not is_soldout:
                is_soldout = True

            opt_name = "/".join(
                p
                for p in [gs("uitemOptnNm1"), gs("uitemOptnNm2"), gs("uitemOptnNm3")]
                if p
            ) or gs("uitemNm")

            items.append(
                {
                    "_uitemId": uitem_id,
                    "name": opt_name,
                    "price": gn("sellprc"),
                    "stock": stock,
                    "isSoldOut": is_soldout,
                }
            )

        return items

    @staticmethod
    def _js_literal_to_json(js_str: str) -> str:
        """JS 객체 리터럴을 JSON으로 변환.

        SSG HTML의 resultItemObj는 단일따옴표와 미인용 키를 사용하는 JS 객체 리터럴이므로
        JSON으로 변환이 필요하다.

        처리 항목:
          - 단일따옴표 문자열 → 이중따옴표 (내부 이중따옴표 이스케이프)
          - 미인용 키 → 이중따옴표 키
          - 후행 콤마 제거
        """
        # Step 1: 단일따옴표 문자열 → 이중따옴표 변환
        result: list[str] = []
        i = 0
        length = len(js_str)
        while i < length:
            ch = js_str[i]
            if ch == "'":
                # 단일따옴표 문자열 시작
                j = i + 1
                chars: list[str] = ['"']
                while j < length:
                    c = js_str[j]
                    if c == "\\" and j + 1 < length:
                        nc = js_str[j + 1]
                        if nc == "'":
                            chars.append("'")  # \' → '
                        elif nc == '"':
                            chars.append('\\"')  # \" → \"
                        else:
                            chars.append(c)
                            chars.append(nc)
                        j += 2
                    elif c == "'":
                        chars.append('"')
                        j += 1
                        break
                    elif c == '"':
                        chars.append('\\"')  # 내부 " 이스케이프
                        j += 1
                    else:
                        chars.append(c)
                        j += 1
                result.append("".join(chars))
                i = j
            else:
                result.append(ch)
                i += 1

        converted = "".join(result)

        # Step 2: 미인용 키 → 이중따옴표 키 (예: itemId: → "itemId":)
        converted = re.sub(r"([{,]\s*)([a-zA-Z_]\w*)\s*:", r'\1"\2":', converted)

        # Step 3: 후행 콤마 제거 (예: {..., } → {...})
        converted = re.sub(r",\s*([}\]])", r"\1", converted)

        return converted

    @staticmethod
    def _extract_card_benefit_price(html: str) -> int:
        """카드혜택가 추출.

        <dt class="mndtl_dl_tit">카드혜택가</dt> 가 존재할 때만 해당 가격을 반환한다.
        카드혜택가는 매일 변동되므로 존재하지 않으면 0을 반환한다.
        """
        m = re.search(
            r'<dt[^>]+class="[^"]*mndtl_dl_tit[^"]*"[^>]*>\s*카드혜택가\s*</dt>'
            r'.*?<em[^>]+class="ssg_price"[^>]*>([\d,]+)</em>',
            html,
            re.DOTALL,
        )
        if m:
            return int(m.group(1).replace(",", ""))
        return 0

    @staticmethod
    def _extract_dept_sale_price(html: str) -> int:
        """department.ssg.com 상세 페이지에서 실질 판매가 추출.

        우선순위:
          1순위: 카드혜택가 (mndtl_dl_tit > 카드혜택가 섹션) — 존재할 때만
          2순위: cdtl_new_price notranslate — 항상 현재 최저 비카드가격 표시
                 (최적가가 있으면 최적가, 없으면 세일가를 자동으로 표시)
          3순위: cdtl_price point — 최적가 tooltip fallback
        """
        # 1순위: 카드혜택가
        card_price = SSGSourcingClient._extract_card_benefit_price(html)
        if card_price > 0:
            return card_price

        # 2순위: 메인 표시 가격 (최적가 or 세일가 — 항상 현재 최저 비카드가격)
        m = re.search(
            r"cdtl_new_price\s+notranslate[^>]*>.*?ssg_price[^>]*>([\d,]+)",
            html,
            re.DOTALL,
        )
        if m:
            return int(m.group(1).replace(",", ""))

        # 3순위: 최적가 tooltip (cdtl_price point)
        m = re.search(
            r"cdtl_price\s+point[^>]*>.*?ssg_price[^>]*>([\d,]+)",
            html,
            re.DOTALL,
        )
        if m:
            return int(m.group(1).replace(",", ""))
        return 0

    def _normalize_image(self, url: str) -> str:
        """이미지 URL 정규화."""
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
