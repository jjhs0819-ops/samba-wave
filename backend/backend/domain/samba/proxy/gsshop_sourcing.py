"""GS샵 소싱용 웹 스크래핑 클라이언트 - httpx 기반.

주의: proxy/gsshop.py는 판매처(마켓) 등록용 제휴 API V3 클라이언트이므로,
소싱(상품 수집)용은 이 파일에서 별도로 관리한다.

GS샵 사이트 정보:
  - PC 상세: https://www.gsshop.com/prd/prd.gs?prdid={상품번호}
  - 모바일 상세: https://m.gsshop.com/prd/prd.gs?prdid={상품번호}
  - 이미지 CDN: asset.m-gs.kr, static.m-gs.kr
  - 데이터 소스: 모바일 상세 페이지의 `var renderJson = {...}` 인라인 JSON
  - 검색: GS샵은 검색 URL을 서버단에서 차단(405) → 확장앱 큐(SourcingQueue) 위임

파싱 전략 우선순위:
  1. renderJson (모바일 상세) - 가격, 옵션, 이미지, 카테고리, 배송 전부 포함
  2. JSON-LD (schema.org Product) - 이름, 가격, 브랜드, 이미지 (폴백)
  3. og 메타 태그 - 최소 폴백
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
import httpx

from backend.utils.logger import logger


class RateLimitError(Exception):
    """GS샵 차단 감지 (429/403)."""

    def __init__(self, status: int, retry_after: int = 0):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"HTTP {status} (retry_after={retry_after})")


class GsShopSourcingClient:
    """GS샵 소싱용 웹 스크래핑 클라이언트 (검색, 상세).

    모바일 상세 페이지(m.gsshop.com)의 renderJson 변수에서
    상품 정보를 추출한다. TV홈쇼핑 기반이므로 보수적 간격으로 요청한다.
    """

    # sourcing_queue.py의 SITE_SEARCH_URLS["GSShop"]이 잘못된 URL이므로 여기서 올바른 URL 사용
    SEARCH_URL = "https://www.gsshop.com/shop/search/main.gs?tq={keyword}"
    BASE_PC = "https://www.gsshop.com"
    BASE_MOBILE = "https://m.gsshop.com"
    PRODUCT_URL = "https://m.gsshop.com/prd/prd.gs"
    MAIN_URL = "https://www.gsshop.com/index.gs"

    HEADERS_MOBILE: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://m.gsshop.com/",
    }

    HEADERS_PC: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.gsshop.com/",
    }

    def __init__(self, cookie: str = "") -> None:
        self._timeout = httpx.Timeout(20.0, connect=10.0)
        self.cookie = cookie

    def _headers(
        self,
        mobile: bool = True,
        extra: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        """요청 헤더 생성."""
        h = {**(self.HEADERS_MOBILE if mobile else self.HEADERS_PC)}
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
        url: str = "",
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """GS샵 상품 검색 — 확장앱 큐 위임 방식.

        GS샵은 검색 URL을 서버단에서 차단(405)하므로,
        확장앱 SourcingQueue를 통해 브라우저에서 검색 페이지를 열고
        DOM 파싱 결과를 받아온다.

        Args:
          keyword: 검색 키워드
          page: 페이지 번호 (현재 미사용)
          size: 최대 결과 수

        Returns:
          표준 상품 dict 리스트
        """
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

        logger.info(f'[GSSHOP] 검색 시작 (확장앱 큐): "{keyword}"')

        try:
            # SourcingQueue.add_search_job() 대신 직접 큐 등록 (올바른 검색 URL 사용)
            request_id = str(uuid.uuid4())[:8]
            # url이 전달되면 그대로 사용, 없으면 keyword로 생성
            if not url:
                url = self.SEARCH_URL.replace("{keyword}", keyword)
            loop = asyncio.get_event_loop()
            future: asyncio.Future = loop.create_future()
            SourcingQueue.queue.append(
                {
                    "requestId": request_id,
                    "site": "GSShop",
                    "type": "search",
                    "url": url,
                    "keyword": keyword,
                }
            )
            SourcingQueue.resolvers[request_id] = future
            logger.info(f"[GSSHOP] 큐 등록 완료: {request_id} → {url}")

            # 확장앱 결과 대기 (최대 300초 — 다중 페이지 수집 대응)
            result = await asyncio.wait_for(future, timeout=300)

            products = result.get("products", []) if isinstance(result, dict) else []
            logger.info(f'[GSSHOP] 검색 완료: "{keyword}" -> {len(products)}개')
            return products[:size]

        except asyncio.TimeoutError:
            logger.warning(f'[GSSHOP] 검색 타임아웃 (300초): "{keyword}"')
            return []
        except Exception as e:
            logger.error(f"[GSSHOP] 검색 실패: {keyword} — {e}")
            return []

    def _parse_main_products(
        self, html: str, keyword: str, size: int
    ) -> list[dict[str, Any]]:
        """PC 메인 페이지 entryData에서 상품 목록 추출."""
        products: list[dict[str, Any]] = []
        seen: set[str] = set()
        kw_lower = keyword.lower()

        # entryData JSON 추출
        entry_match = re.search(
            r'<script[^>]+id="entryData"[^>]*>\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
        if not entry_match:
            return products

        try:
            entry_data = json.loads(entry_match.group(1))
        except (json.JSONDecodeError, TypeError):
            return products

        # mainBigBannerList + 기타 상품 리스트에서 추출
        all_items: list[dict[str, Any]] = []
        for key in entry_data:
            val = entry_data[key]
            if isinstance(val, list):
                all_items.extend(
                    item
                    for item in val
                    if isinstance(item, dict) and item.get("dealNo")
                )

        now_iso = datetime.now(tz=timezone.utc).isoformat()

        for item in all_items:
            deal_no = str(item.get("dealNo", ""))
            if not deal_no or deal_no in seen:
                continue

            name = item.get("exposPrdNm", "").strip()
            brand = item.get("dealEtc2Nm", "").strip()

            # 키워드 필터링
            search_text = f"{name} {brand}".lower()
            if kw_lower and kw_lower not in search_text:
                continue

            seen.add(deal_no)
            gs_prc = self._safe_int(item.get("gsPrc", 0))
            sale_prc = self._safe_int(item.get("salePrc", 0))

            products.append(
                {
                    "siteProductId": deal_no,
                    "goodsNo": deal_no,
                    "sourceSite": "GSSHOP",
                    "sourceUrl": f"{self.BASE_PC}/prd/prd.gs?prdid={deal_no}",
                    "name": name,
                    "brand": brand,
                    "salePrice": gs_prc or sale_prc,
                    "originalPrice": sale_prc or gs_prc,
                    "discountRate": self._safe_int(item.get("dcRt", 0)),
                    "image": item.get("bigBannerUrl", "") or item.get("imgUrl", ""),
                    "isSoldOut": bool(item.get("isTempout")),
                    "freeShipping": item.get("freeDlvYn") == "Y",
                    "collectedAt": now_iso,
                    "status": "collected",
                }
            )

            if len(products) >= size:
                break

        return products

    # ------------------------------------------------------------------
    # 카테고리 스캔 — 백화점 탭 사이드바 파싱
    # ------------------------------------------------------------------

    async def scan_categories(
        self,
        keyword: str,
    ) -> dict[str, Any]:
        """GS샵 카테고리 스캔 — 백화점 탭 사이드바에서 카테고리 분포 조회.

        확장앱 SourcingQueue를 통해 백화점 탭 검색 페이지를 열고
        좌측 사이드바의 카테고리별 상품 수를 파싱한다.

        Returns:
          {"categories": [...], "total": int, "groupCount": int}
        """
        import base64
        from urllib.parse import quote

        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

        logger.info(f'[GSSHOP] 카테고리 스캔 시작: "{keyword}"')

        request_id = str(uuid.uuid4())[:8]
        # 백화점 탭 필터 (eh 파라미터) — 공백 없는 compact JSON 필수
        eh = base64.b64encode(
            json.dumps(
                {"part": "DEPT", "selected": "opt-part"}, separators=(",", ":")
            ).encode()
        ).decode()
        encoded_kw = quote(keyword, safe="")
        url = f"{self.BASE_PC}/shop/search/main.gs?tq={encoded_kw}&eh={eh}"

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        SourcingQueue.queue.append(
            {
                "requestId": request_id,
                "site": "GSShop",
                "type": "category-scan",
                "url": url,
                "keyword": keyword,
            }
        )
        SourcingQueue.resolvers[request_id] = future
        logger.info(f"[GSSHOP] 카테고리 스캔 큐 등록: {request_id} → {url}")

        try:
            result = await asyncio.wait_for(future, timeout=60)
        except asyncio.TimeoutError:
            logger.warning(f'[GSSHOP] 카테고리 스캔 타임아웃: "{keyword}"')
            return {"categories": [], "total": 0, "groupCount": 0}

        raw_cats = result.get("categories", []) if isinstance(result, dict) else []
        total = result.get("total", 0) if isinstance(result, dict) else 0

        # 표준 카테고리 분포 포맷으로 변환
        categories = []
        for cat in raw_cats:
            name = cat.get("name", "")
            count = cat.get("count", 0)
            code = cat.get("categoryCode", "")
            href = cat.get("href", "")
            if not name or count <= 0:
                continue
            categories.append(
                {
                    "categoryCode": code or name,
                    "path": f"백화점 > {name}",
                    "count": count,
                    "category1": "백화점",
                    "category2": name,
                    "category3": "",
                    "href": href,
                }
            )

        # count 내림차순 정렬
        categories.sort(key=lambda c: -c["count"])

        logger.info(
            f'[GSSHOP] 카테고리 스캔 완료: "{keyword}" → {len(categories)}개 카테고리, 총 {total}건'
        )

        return {
            "categories": categories,
            "total": total or sum(c["count"] for c in categories),
            "groupCount": len(categories),
        }

    # ------------------------------------------------------------------
    # 상세 조회
    # ------------------------------------------------------------------

    async def get_product_detail(
        self, product_id: str, refresh_only: bool = False
    ) -> dict[str, Any]:
        """GS샵 상품 상세 정보 조회.

        모바일 상세 페이지의 renderJson 변수에서 전체 상품 데이터를 추출한다.
        renderJson이 없으면 JSON-LD → og 메타 태그 순으로 폴백한다.

        Args:
          product_id: GS샵 상품 ID (prdid)
          refresh_only: True이면 가격/재고만 빠르게 갱신

        Returns:
          표준 상품 상세 dict

        Raises:
          RateLimitError: 429/403 응답 시
        """
        url = f"{self.PRODUCT_URL}?prdid={product_id}"
        logger.info(f"[GSSHOP] 상세 조회: {product_id}")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=self._headers(mobile=True))

                # 차단 감지
                if resp.status_code in (429, 403):
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning(
                        f"[GSSHOP] 차단 감지 HTTP {resp.status_code}: {product_id}"
                    )
                    raise RateLimitError(resp.status_code, retry_after)

                if resp.status_code != 200:
                    logger.warning(
                        f"[GSSHOP] 상세 페이지 HTTP {resp.status_code}: {product_id}"
                    )
                    return {}

                html = resp.text

            now_iso = datetime.now(tz=timezone.utc).isoformat()
            timestamp = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

            # 1순위: renderJson 파싱
            render_data = self._extract_render_json(html)
            if render_data:
                result = self._build_from_render_json(
                    render_data, product_id, timestamp, now_iso
                )
                if result.get("name"):
                    return result

            # 2순위: JSON-LD 파싱
            json_ld_data = self._extract_json_ld(html)
            if json_ld_data:
                result = self._build_from_json_ld(
                    json_ld_data, product_id, timestamp, now_iso
                )
                if result.get("name"):
                    return result

            # 3순위: og 메타 태그 (최소 폴백)
            return self._build_from_meta(html, product_id, timestamp, now_iso)

        except RateLimitError:
            raise
        except httpx.TimeoutException:
            logger.error(f"[GSSHOP] 상세 조회 타임아웃: {product_id}")
            return {}
        except Exception as e:
            logger.error(f"[GSSHOP] 상세 조회 실패: {product_id} — {e}")
            return {}

    # ------------------------------------------------------------------
    # renderJson 파싱 (1순위)
    # ------------------------------------------------------------------

    def _extract_render_json(self, html: str) -> Optional[dict[str, Any]]:
        """모바일 상세 페이지의 `var renderJson = {...}` 추출."""
        start_idx = html.find("var renderJson = ")
        if start_idx == -1:
            start_idx = html.find("var renderJson=")
        if start_idx == -1:
            return None

        json_start = html.find("{", start_idx)
        if json_start == -1:
            return None

        text = html[json_start:]
        depth = 0
        end = 0
        for i, c in enumerate(text):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            if depth == 0:
                end = i + 1
                break

        if end == 0:
            return None

        try:
            return json.loads(text[:end])
        except (json.JSONDecodeError, ValueError):
            logger.warning("[GSSHOP] renderJson 파싱 실패")
            return None

    def _build_from_render_json(
        self,
        data: dict[str, Any],
        product_id: str,
        timestamp: int,
        now_iso: str,
    ) -> dict[str, Any]:
        """renderJson 데이터에서 표준 상품 dict 생성."""
        prd = data.get("prd") or {}
        pmo = data.get("pmo") or {}
        prc = pmo.get("prc") or {}

        # 상품명
        name = (prd.get("exposPrdNm", "") or prd.get("prdNm", "") or "").strip()

        # 브랜드
        brand = prd.get("brandNm", "").strip()
        name_info = prd.get("nameInfo") or {}
        if not brand:
            brand = name_info.get("brandShopNm", "").strip()

        # 제조사
        manufacturer = prd.get("mnfcCo", "").strip()

        # 가격
        sale_prc = self._safe_int(prc.get("salePrc", 0))  # 정가
        gs_prc = self._safe_int(pmo.get("gsPrc", 0))  # GS가 (판매가)
        flgd_prc = self._safe_int(prc.get("flgdPrc", 0))  # 할인가
        sale_price = gs_prc or flgd_prc or sale_prc
        original_price = sale_prc or gs_prc
        discount_rate = self._safe_int(prc.get("prcDcRt", 0))
        cpn_dc_amt = self._safe_int(prc.get("cpnDcAmt", 0))  # 쿠폰할인액

        # 최대혜택가 = 판매가 - 쿠폰할인
        best_benefit_price = (sale_price - cpn_dc_amt) if cpn_dc_amt > 0 else sale_price
        if best_benefit_price <= 0:
            best_benefit_price = sale_price

        # 카테고리
        ctgr = prd.get("ctgrInfo") or {}
        category_levels = []
        for key in ["lsectNm", "msectNm", "ssectNm", "dsectNm"]:
            val = ctgr.get(key, "")
            if val:
                category_levels.append(val.strip())
        category_str = " > ".join(category_levels)

        # 이미지 (imgInfo 배열, 최대 9장)
        images: list[str] = []
        for img in prd.get("imgInfo") or []:
            img_url = img.get("imgUrl", "")
            if img_url and img_url not in images:
                images.append(img_url)
            if len(images) >= 9:
                break

        # 이미지 부족 시 mediaInfo에서 보충
        if len(images) < 9:
            media_info = prd.get("mediaInfo") or {}
            for img_url in media_info.get("images") or []:
                if isinstance(img_url, str) and img_url and img_url not in images:
                    images.append(img_url)
                if len(images) >= 9:
                    break

        # 상세 이미지 (prdImgDescd HTML 내 <img>)
        detail_html = prd.get("prdImgDescd", "") or ""
        detail_images = self._extract_detail_images_from_html(detail_html)

        # 옵션 (attrTypList)
        options = self._parse_options_from_render(prd)

        # 품절 판단
        prd_sale_st = prd.get("prdSaleSt", "Y")
        is_out_of_stock = prd_sale_st != "Y"
        if not is_out_of_stock and options:
            is_out_of_stock = all(opt.get("isSoldOut", False) for opt in options)

        sale_status = "sold_out" if is_out_of_stock else "in_stock"

        # 배송
        free_shipping = prd.get("freeDlvFlg") == "Y" or prd.get("dlvcAmt", 0) == 0
        quick_delivery = prd.get("quickDlvFlg") == "Y"

        # 원산지 (orgp 필드 — "필수정보 참조"인 경우 빈 값)
        origin = prd.get("orgp", "").strip()
        if "참조" in origin or "상세" in origin:
            origin = ""

        return {
            "id": f"col_gsshop_{product_id}_{timestamp}",
            "sourceSite": "GSSHOP",
            "siteProductId": str(product_id),
            "sourceUrl": f"{self.BASE_PC}/prd/prd.gs?prdid={product_id}",
            "name": name,
            "brand": brand,
            "manufacturer": manufacturer,
            "category": category_str,
            "category1": category_levels[0] if len(category_levels) > 0 else "",
            "category2": category_levels[1] if len(category_levels) > 1 else "",
            "category3": category_levels[2] if len(category_levels) > 2 else "",
            "category4": category_levels[3] if len(category_levels) > 3 else "",
            "images": images[:9],
            "detailImages": detail_images,
            "detailHtml": detail_html,
            "options": options,
            "originalPrice": original_price,
            "salePrice": sale_price,
            "bestBenefitPrice": best_benefit_price,
            "discountRate": discount_rate,
            "saleStatus": sale_status,
            "isOutOfStock": is_out_of_stock,
            "freeShipping": free_shipping,
            "sameDayDelivery": quick_delivery,
            "origin": origin,
            "collectedAt": now_iso,
            "updatedAt": now_iso,
            "status": "collected",
        }

    def _parse_options_from_render(self, prd: dict[str, Any]) -> list[dict[str, Any]]:
        """renderJson.prd의 attrTypList에서 옵션 추출.

        GS샵 옵션은 `attrTypVal` 필드에 구분자 0x08(\\b)로 연결된 형식:
          예) "블랙\\b090(S)" → 색상=블랙, 사이즈=090(S)
        """
        options: list[dict[str, Any]] = []
        attr_list = prd.get("attrTypList") or []
        nm1 = prd.get("attrTypNm1", "")  # 예: "색상"
        nm2 = prd.get("attrTypNm2", "")  # 예: "사이즈"

        for attr in attr_list:
            raw_val = attr.get("attrTypVal", "")
            parts = raw_val.split("\x08")  # 0x08 = 백스페이스(구분자)
            opt_name = " / ".join(p.strip() for p in parts if p.strip())

            stock_flg = attr.get("stockFlg", "N")
            is_sold_out = stock_flg != "Y"

            options.append(
                {
                    "name": opt_name,
                    "price": 0,  # GS샵 옵션은 추가가격 없음 (동일가)
                    "stock": 0 if is_sold_out else 1,
                    "isSoldOut": is_sold_out,
                    "attrPrdCd": attr.get("attrPrdCd"),
                }
            )

        return options

    # ------------------------------------------------------------------
    # JSON-LD 파싱 (2순위 폴백)
    # ------------------------------------------------------------------

    def _extract_json_ld(self, html: str) -> Optional[dict[str, Any]]:
        """JSON-LD (schema.org Product) 추출."""
        pattern = re.compile(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            re.DOTALL,
        )
        for m in pattern.finditer(html):
            try:
                data = json.loads(m.group(1))
                # @graph 배열에서 Product 타입 찾기
                graph = data.get("@graph") or [data]
                for item in graph:
                    if item.get("@type") == "Product":
                        return item
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _build_from_json_ld(
        self,
        ld: dict[str, Any],
        product_id: str,
        timestamp: int,
        now_iso: str,
    ) -> dict[str, Any]:
        """JSON-LD 데이터에서 표준 상품 dict 생성."""
        name = ld.get("name", "").strip()
        brand_obj = ld.get("brand") or {}
        brand = brand_obj.get("name", "") if isinstance(brand_obj, dict) else ""
        images_raw = ld.get("image") or []
        images = images_raw if isinstance(images_raw, list) else [images_raw]

        offers = ld.get("offers") or {}
        price = self._safe_int(offers.get("price", 0))
        availability = offers.get("availability", "")
        is_out_of_stock = "OutOfStock" in availability

        rating = ld.get("aggregateRating") or {}

        return {
            "id": f"col_gsshop_{product_id}_{timestamp}",
            "sourceSite": "GSSHOP",
            "siteProductId": str(product_id),
            "sourceUrl": f"{self.BASE_PC}/prd/prd.gs?prdid={product_id}",
            "name": name,
            "brand": brand,
            "manufacturer": "",
            "category": "",
            "category1": "",
            "category2": "",
            "category3": "",
            "category4": "",
            "images": images[:9],
            "detailImages": [],
            "detailHtml": "",
            "options": [],
            "originalPrice": price,
            "salePrice": price,
            "bestBenefitPrice": price,
            "discountRate": 0,
            "saleStatus": "sold_out" if is_out_of_stock else "in_stock",
            "isOutOfStock": is_out_of_stock,
            "freeShipping": False,
            "sameDayDelivery": False,
            "origin": "",
            "collectedAt": now_iso,
            "updatedAt": now_iso,
            "status": "collected",
        }

    # ------------------------------------------------------------------
    # og 메타 태그 파싱 (3순위 폴백)
    # ------------------------------------------------------------------

    def _build_from_meta(
        self,
        html: str,
        product_id: str,
        timestamp: int,
        now_iso: str,
    ) -> dict[str, Any]:
        """og 메타 태그에서 최소 정보 추출."""
        name = self._extract_meta(html, "og:title") or ""
        image = self._normalize_image(self._extract_meta(html, "og:image") or "")
        images = [image] if image else []

        return {
            "id": f"col_gsshop_{product_id}_{timestamp}",
            "sourceSite": "GSSHOP",
            "siteProductId": str(product_id),
            "sourceUrl": f"{self.BASE_PC}/prd/prd.gs?prdid={product_id}",
            "name": name.replace("[GS SHOP] ", "").replace(" - GS SHOP", "").strip(),
            "brand": "",
            "manufacturer": "",
            "category": "",
            "category1": "",
            "category2": "",
            "category3": "",
            "category4": "",
            "images": images,
            "detailImages": [],
            "detailHtml": "",
            "options": [],
            "originalPrice": 0,
            "salePrice": 0,
            "bestBenefitPrice": 0,
            "discountRate": 0,
            "saleStatus": "in_stock",
            "isOutOfStock": False,
            "freeShipping": False,
            "sameDayDelivery": False,
            "origin": "",
            "collectedAt": now_iso,
            "updatedAt": now_iso,
            "status": "collected",
        }

    # ------------------------------------------------------------------
    # 상세 이미지 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_detail_images_from_html(
        desc_html: str,
    ) -> list[str]:
        """상세 설명 HTML에서 이미지 URL 추출."""
        if not desc_html:
            return []

        detail_images: list[str] = []
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', desc_html, re.I):
            src = m.group(1).strip()
            if not src:
                continue
            # 프로토콜 보정
            if src.startswith("//"):
                src = f"https:{src}"
            # 아이콘/버튼 이미지 제외
            if "icon" in src.lower() or "btn_" in src.lower():
                continue
            if src not in detail_images:
                detail_images.append(src)

        return detail_images

    # ------------------------------------------------------------------
    # 공통 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_image(url: str) -> str:
        """이미지 URL 정규화 (프로토콜 보정)."""
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
            rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"'
            rf'[^>]+content="([^"]*)"'
        )
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1)
        # content가 먼저 오는 경우
        pattern2 = (
            rf'<meta[^>]+content="([^"]*)"'
            rf'[^>]+(?:property|name)="{re.escape(prop)}"'
        )
        m2 = re.search(pattern2, html, re.IGNORECASE)
        return m2.group(1) if m2 else None

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
