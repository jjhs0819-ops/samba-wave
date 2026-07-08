"""SNKRDUNK(스니덩크) 소싱 클라이언트.

사이트: https://snkrdunk.com/en
수집 방식:
  - 통합 검색: GET /en/v1/search?keyword=&perPage=&page=&type=
  - 브랜드 카드 리스트: GET /en/v1/trading-cards?brandId=&categoryId=&perPage=&page=
    (perPage 최대 100)
  - 상세(스니커즈/스트릿웨어): HTML SSR + JSON-LD <script application/ld+json> 파싱
  - 통화: /en/ 사이트는 USD 결제 — JSON-LD offers 중 priceCurrency=USD 항목 사용

설계:
  - USD 원본 저장 (영문 사이트 기본 결제 통화)
  - sneakers / streetwears / trading-card 세 카탈로그 지원 (extra_data.snkr_type)
  - 트레이딩카드는 상세 JSON-LD 없음 → 리스트 응답만으로 필드 채움
  - 인증 없음. User-Agent 만 필요.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from backend.utils.logger import logger

BASE = "https://snkrdunk.com"
SEARCH_URL = f"{BASE}/en/v1/search"
KEYWORDS_URL = f"{BASE}/en/v1/search/keywords"
TRADING_CARDS_URL = f"{BASE}/en/v1/trading-cards"
DETAIL_SNEAKER_URL = f"{BASE}/en/sneakers/{{id}}"
DETAIL_STREETWEAR_URL = f"{BASE}/en/streetwears/{{id}}"
DETAIL_TRADING_CARD_URL = f"{BASE}/apparels/{{id}}"
# 트레이딩카드 컨디션(옵션)별 중고 리스팅 API
# 상품코드는 SW---{id} 형식. isOnlyOnSale=true → 판매중(재고) 리스팅만
USED_LISTINGS_URL = f"{BASE}/en/v1/products/SW---{{id}}/used-listings"
# 박스/실드 상품 가격 API — used-listings(중고)에 안 잡히고 sizes(수량단)로 노출
# 예: "1 box" $150(재고 481), "2 boxes" $313 ... 내부적으로 streetwear 타입 취급
SIZES_URL = f"{BASE}/en/v1/products/SW---{{id}}/sizes"
# 일본(JP) API — 엔화 가격. 영문(/en) API는 USD라 엔가 미노출 → 트레이딩카드 수집은 JP 사용.
#   JP_DETAIL: 상세(name·productNumber·primaryMedia·minPrice)
#   JP_USED  : 중고 리스팅(price=엔, displayShortConditionTitle=PSA10, isDisplaySold)
#   JP_SIZES : 박스/봉인 수량단 가격(sizePrices[].minListingPrice)
JP_DETAIL_URL = f"{BASE}/v1/apparels/{{id}}"
JP_USED_URL = f"{BASE}/v1/apparels/{{id}}/used"
JP_SIZES_URL = f"{BASE}/v1/apparels/{{id}}/sizes"
# 구매주문 배송조회 API (해외매입 송장) — session 쿠키 인증 필요. 취引ID = order_id.
#   ORDER_DETAIL: order.trackingNumber(사무국→구매자 발송송장)·orderStatus·orderAdminShippedAt
#   ORDER_DELIVERY_COMPANY: {"deliveryCompany":"yamato"} 택배사 코드 (확인값 2026-07-02)
ORDER_DETAIL_URL = f"{BASE}/v1/orders/{{id}}"
ORDER_DELIVERY_COMPANY_URL = f"{BASE}/v2/orders/{{id}}/get-delivery-company"
# 택배사 코드 → 표시명. 확인값: yamato. 미확인 코드는 원본 그대로 노출.
_DELIVERY_COMPANY_LABELS = {
    "yamato": "야마토운수",
    "kuronekoyamato": "야마토운수",
    "sagawa": "사가와급편",
    "jppost": "일본우편",
    "japanpost": "일본우편",
}
# 사무국→구매자 발송완료 상태 — 이때 order.trackingNumber 채워짐(해외송장 수집 가능).
SNKR_SHIPPED_ORDER_STATUSES = {"waiting-for-delivered-to-buyer"}
# JP API는 ja-JP 로케일로 엔화 반환
JP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Referer": f"{BASE}/",
}
# 브랜드+카테고리 URL 패턴: https://snkrdunk.com/en/brands/{brand}/trading-cards?categoryId={cat}
BRAND_TRADING_CARDS_URL_RE = re.compile(
    r"https?://snkrdunk\.com/en/brands/([^/?]+)/trading-cards(?:\?[^#]*?categoryId=(\d+))?",
    re.IGNORECASE,
)
# 전역 트레이딩카드 리스트 URL 패턴: https://snkrdunk.com/en/trading-cards?type=hottest&slide=right
GLOBAL_TRADING_CARDS_URL_RE = re.compile(
    r"https?://snkrdunk\.com/en/trading-cards(?:\?|$)",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
    "Referer": f"{BASE}/en/",
}

# 추출할 통화 코드 (영문 사이트 결제 통화)
TARGET_CURRENCY = "USD"

# 트레이딩카드 상세 SSR HTML의 productNumber(품번, 예: pkmn-tcg-SV-P-261) 추출
# Vue SSR prop `:trading-card="{...}"` 안에 HTML 엔티티(&#34;=")로 임베드됨
_PRODUCT_NUMBER_RE = re.compile(r"productNumber&#34;:&#34;([^&]+)&#34;")


_CATEGORY_LABELS = {
    "sneaker": "스니커즈",
    "streetwear": "스트릿웨어",
    "trading-card": "트레이딩카드",
}


def _category_label(snkr_type: str | None) -> str:
    return _CATEGORY_LABELS.get(snkr_type or "", "스트릿웨어")


def _is_streetwear_id(site_product_id: str) -> bool:
    """순수 숫자면 streetwear, 그 외(예: IQ1323-001)는 sneaker."""
    return site_product_id.isdigit()


# 트레이딩카드 브랜드(프랜차이즈) 추론 — 이름 키워드 + 품번 접두어
_CARD_BRAND_NAME_MAP = [
    ("one piece", "ONE PIECE"),
    ("pokemon", "Pokémon"),
    ("pokémon", "Pokémon"),
    ("dragon ball", "DRAGON BALL"),
    ("yu-gi-oh", "Yu-Gi-Oh!"),
    ("yugioh", "Yu-Gi-Oh!"),
    ("weiss", "Weiss Schwarz"),
    ("duel masters", "Duel Masters"),
    ("lorcana", "Disney Lorcana"),
    ("union arena", "Union Arena"),
    ("gundam", "GUNDAM"),
    ("digimon", "Digimon"),
    ("hololive", "hololive"),
    ("detective conan", "Detective Conan"),
    ("ultraman", "ULTRAMAN"),
    ("magic", "Magic: The Gathering"),
]
_CARD_BRAND_PREFIX_MAP = [
    ("pkmn", "Pokémon"),
    ("ygo", "Yu-Gi-Oh!"),
    ("dbsc", "DRAGON BALL"),
    ("dbsd", "DRAGON BALL"),
    ("uatcg", "Union Arena"),
    ("ws", "Weiss Schwarz"),
    ("dm", "Duel Masters"),
    ("mtg", "Magic: The Gathering"),
    ("disny", "Disney Lorcana"),
    ("kkk", "Murakami.Flowers"),
    ("holo", "hololive"),
    ("gcg", "GUNDAM"),
    ("cnn", "Detective Conan"),
    ("opcd", "ONE PIECE"),
    ("opc", "ONE PIECE"),
    ("op", "ONE PIECE"),
    ("eb", "ONE PIECE"),
    ("st", "ONE PIECE"),
    ("prb", "ONE PIECE"),
    ("p-", "ONE PIECE"),
]


def _derive_card_brand(name: str, product_number: str = "") -> str:
    """트레이딩카드 브랜드(프랜차이즈) 추론. 못 찾으면 빈 문자열."""
    low = (name or "").lower()
    for kw, brand in _CARD_BRAND_NAME_MAP:
        if kw in low:
            return brand
    sc = (product_number or "").lower()
    for pre, brand in _CARD_BRAND_PREFIX_MAP:
        if sc.startswith(pre):
            return brand
    return ""


def _detail_url(site_product_id: str, snkr_type: str | None = None) -> str:
    # 트레이딩카드는 전용 상세 경로 사용 (/en/trading-cards/{id})
    if snkr_type == "trading-card":
        return DETAIL_TRADING_CARD_URL.format(id=site_product_id)
    if snkr_type == "streetwear" or (
        snkr_type is None and _is_streetwear_id(site_product_id)
    ):
        return DETAIL_STREETWEAR_URL.format(id=site_product_id)
    return DETAIL_SNEAKER_URL.format(id=site_product_id)


def parse_brand_category_url(url: str) -> tuple[str, str] | None:
    """`/en/brands/{brand}/trading-cards?categoryId={cat}` URL → (brand_id, category_id).

    categoryId 누락 시 빈 문자열 반환.
    """
    m = BRAND_TRADING_CARDS_URL_RE.search(url or "")
    if not m:
        return None
    brand = m.group(1) or ""
    cat = m.group(2) or ""
    return brand, cat


def _parse_size_label(desc: str) -> str:
    """JSON-LD offer.description ('US 9', 'US 10.5') 정규화."""
    return (desc or "").strip()


def _extract_jsonld_products(html: str) -> list[dict[str, Any]]:
    """HTML에서 ld+json Product 노드들 추출."""
    products: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<script type="application/ld\+json">(.+?)</script>', html, re.DOTALL
    ):
        body = m.group(1).strip()
        try:
            data = json.loads(body)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            products.append(data)
        elif isinstance(data, list):
            for d in data:
                if isinstance(d, dict) and d.get("@type") == "Product":
                    products.append(d)
    return products


class SnkrdunkClient:
    """SNKRDUNK 소싱 클라이언트."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    async def search(
        self,
        keyword: str,
        page: int = 1,
        per_page: int = 24,
        type_filter: str = "",
        max_count: int = 100,
    ) -> dict[str, Any]:
        """키워드 검색 — sneakers + streetwears 통합 결과 반환.

        keyword가 `https://snkrdunk.com/en/brands/{brand}/trading-cards?categoryId={cat}`
        형식이면 트레이딩카드 전체 페이지네이션 수집으로 라우팅.

        Returns:
            {"products": [...], "total": int}
        """
        bc = parse_brand_category_url(keyword)
        if bc is not None:
            brand_id, category_id = bc
            # 호출자 max_count 존중 — 강제 10000 제거(검색 120초 타임아웃 유발)
            return await self.collect_brand_cards(
                brand_id=brand_id,
                category_id=category_id,
                max_count=max_count,
            )
        # 전역 트레이딩카드 리스트 URL (예: /en/trading-cards?type=hottest&slide=right)
        if GLOBAL_TRADING_CARDS_URL_RE.search(keyword or ""):
            # 호출자 max_count 존중 — 강제 1000 제거(검색 120초 타임아웃 유발)
            return await self.collect_listing_cards(url=keyword, max_count=max_count)
        products: list[dict[str, Any]] = []
        total = 0
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            cur_page = page
            while len(products) < max_count:
                params = {
                    "keyword": keyword,
                    "perPage": per_page,
                    "page": cur_page,
                    "type": type_filter,
                }
                try:
                    r = await client.get(SEARCH_URL, params=params)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    logger.warning(f"[SNKRDUNK] 검색 실패 page={cur_page}: {e}")
                    break

                sneaker_total = data.get("sneakerCount") or 0
                street_total = data.get("streetwearCount") or 0
                total = sneaker_total + street_total

                page_items = self._parse_search_items(
                    data.get("sneakers") or [], "sneaker"
                ) + self._parse_search_items(
                    data.get("streetwears") or [], "streetwear"
                )
                if not page_items:
                    break
                products.extend(page_items)
                logger.info(
                    f"[SNKRDUNK] 검색 '{keyword}' p{cur_page} +{len(page_items)}건"
                    f" (누적 {len(products)}/{total})"
                )
                if len(page_items) < per_page:
                    break
                cur_page += 1

        products = products[:max_count]
        return {"products": products, "total": total}

    @staticmethod
    def _parse_search_items(
        items: list[dict[str, Any]], snkr_type: str
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for it in items:
            sid = str(it.get("id", "")).strip()
            if not sid:
                continue
            thumb = it.get("thumbnailUrl") or ""
            min_price = it.get("minPrice")
            sale_price = int(min_price) if isinstance(min_price, (int, float)) else 0
            # 입찰자 없는 0원(또는 가격 미존재) 상품은 수집 제외
            if sale_price <= 0:
                continue
            results.append(
                {
                    "site_product_id": sid,
                    "name": (it.get("name") or "").strip(),
                    "original_price": sale_price,
                    "sale_price": sale_price,
                    "images": [thumb] if thumb else [],
                    "brand": "",
                    "source_site": "SNKRDUNK",
                    "source_url": _detail_url(sid, snkr_type),
                    "category": _category_label(snkr_type),
                    "category1": "SNKRDUNK",
                    "category2": _category_label(snkr_type),
                    "category3": "",
                    "color": "",
                    "url": _detail_url(sid, snkr_type),
                    "video_url": _detail_url(sid, snkr_type),
                    "options": [],
                    "detail_html": "",
                    "free_shipping": False,
                    "extra_data": {
                        "snkr_type": snkr_type,
                        "currency": TARGET_CURRENCY,
                        "min_price_format": it.get("minPriceFormat"),
                        "listing_count": str(it.get("listingCount", "")),
                        "offer_count": str(it.get("offerCount", "")),
                    },
                }
            )
        return results

    async def collect_brand_cards(
        self,
        brand_id: str,
        category_id: str = "",
        per_page: int = 100,
        max_count: int = 50000,
        sleep_between_pages: float = 0.2,
        max_pages: int = 15,
    ) -> dict[str, Any]:
        """브랜드+카테고리의 트레이딩카드 전체 페이지네이션 수집.

        Args:
            brand_id: ex) "pokemon"
            category_id: ex) "25" (없으면 빈 문자열)
            per_page: 페이지당 (최대 100)
            max_count: 상한 (안전장치)
            max_pages: 페이지 상한 — 검색 120초 타임아웃 방지 (req_count 불명 시 가드)
        """
        import asyncio

        products: list[dict[str, Any]] = []
        per_page = max(1, min(int(per_page or 100), 100))
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            page = 1
            seen: set[str] = set()
            while len(products) < max_count and page <= max_pages:
                params: dict[str, Any] = {
                    "brandId": brand_id,
                    "perPage": per_page,
                    "page": page,
                }
                if category_id:
                    params["categoryId"] = category_id
                try:
                    r = await client.get(TRADING_CARDS_URL, params=params)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    logger.warning(
                        f"[SNKRDUNK] 카드 수집 실패 brand={brand_id} "
                        f"cat={category_id} page={page}: {e}"
                    )
                    break
                items = data.get("tradingCards") or []
                if not items:
                    break
                page_items = self._parse_card_items(items)
                # 중복 제거 (간헐적 페이지 겹침 대비)
                new_items = [p for p in page_items if p["site_product_id"] not in seen]
                seen.update(p["site_product_id"] for p in new_items)
                products.extend(new_items)
                logger.info(
                    f"[SNKRDUNK] 카드 수집 brand={brand_id} cat={category_id} "
                    f"p{page} +{len(new_items)}건 (누적 {len(products)})"
                )
                if len(items) < per_page:
                    break
                page += 1
                if sleep_between_pages:
                    await asyncio.sleep(sleep_between_pages)

        products = products[:max_count]
        return {"products": products, "total": len(products)}

    async def collect_listing_cards(
        self,
        url: str,
        per_page: int = 100,
        max_count: int = 1000,
        sleep_between_pages: float = 1.0,
        max_pages: int = 60,
        start_page: int = 1,
    ) -> dict[str, Any]:
        """전역 트레이딩카드 리스트 URL 페이지네이션 수집.

        예: `/en/trading-cards?type=hottest&slide=right`
        브랜드 지정 없이 `/en/v1/trading-cards?page=N` 글로벌 피드를 페이징하면
        전 브랜드 카드가 신상순으로 섞여 나온다(브랜드 열거 불필요). `_parse_card_items`
        가 listingCount>0 & minPrice>0 (재고 있는) 카드만 통과시킨다.

        주의(검증값):
          - `type`/`slide` 등 UI 파라미터를 v1 API에 넘기면 400(INVALID_ARGUMENT)으로
            전건 실패 → brandId/categoryId만 화이트리스트로 전달.
          - 요청 간격이 짧으면(<1s) 400 레이트리밋 발생 → sleep 1.0 보수값.
          - worker가 search()를 120초 timeout으로 감싸므로 단일 잡은 max_pages=60
            (≈90~100s) 내로 제한. 전체 카탈로그(수백 페이지)는 start_page 기반
            이어하기로 잡을 나눠 수집.

        start_page: 이어하기 — 깊은 페이지부터 재개(반복 잡이 앞쪽만 재스캔 방지)
        """
        import asyncio
        from urllib.parse import urlparse, parse_qs

        per_page = max(1, min(int(per_page or 100), 100))
        # URL 쿼리스트링 중 v1 API가 허용하는 키만 전달 (type/slide 등은 400 유발)
        base_params: dict[str, Any] = {}
        try:
            qs = parse_qs(urlparse(url or "").query)
            for k, v in qs.items():
                if not v:
                    continue
                if k not in ("brandId", "categoryId"):
                    continue
                base_params[k] = v[0]
        except Exception as exc:
            logger.warning(f"[SNKRDUNK] 리스트 URL 파싱 실패: {exc}")

        products: list[dict[str, Any]] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            page = max(1, int(start_page or 1))
            last_page = page + max_pages - 1
            while len(products) < max_count and page <= last_page:
                params: dict[str, Any] = {
                    **base_params,
                    "perPage": per_page,
                    "page": page,
                }
                try:
                    r = await client.get(TRADING_CARDS_URL, params=params)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    logger.warning(
                        f"[SNKRDUNK] 리스트 수집 실패 params={base_params} page={page}: {e}"
                    )
                    break
                items = data.get("tradingCards") or []
                if not items:
                    break
                page_items = self._parse_card_items(items)
                new_items = [p for p in page_items if p["site_product_id"] not in seen]
                seen.update(p["site_product_id"] for p in new_items)
                products.extend(new_items)
                logger.info(
                    f"[SNKRDUNK] 리스트 수집 params={base_params} p{page} "
                    f"+{len(new_items)}건 (누적 {len(products)})"
                )
                if len(items) < per_page:
                    break
                page += 1
                if sleep_between_pages:
                    await asyncio.sleep(sleep_between_pages)

        products = products[:max_count]
        return {"products": products, "total": len(products)}

    @staticmethod
    def _parse_card_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """tradingCards 응답 배열 → 정규화.

        입찰 0건(listingCount=0) 또는 가격 미존재 카드는 수집 제외.
        """
        results: list[dict[str, Any]] = []
        for it in items:
            sid = str(it.get("id", "")).strip()
            if not sid:
                continue
            # 입찰자 수 확인
            try:
                listing_count_int = int(str(it.get("listingCount", "0") or "0"))
            except Exception:
                listing_count_int = 0
            min_price = it.get("minPrice")
            sale_price = int(min_price) if isinstance(min_price, (int, float)) else 0
            # 입찰 0건 또는 가격 0원은 등록 가치 없음 → 수집 제외
            if listing_count_int <= 0 or sale_price <= 0:
                continue

            thumb = it.get("thumbnailUrl") or ""
            url = _detail_url(sid, "trading-card")
            listing_count = str(listing_count_int)
            results.append(
                {
                    "site_product_id": sid,
                    "name": (it.get("name") or "").strip(),
                    "original_price": sale_price,
                    "sale_price": sale_price,
                    "images": [thumb] if thumb else [],
                    "brand": _derive_card_brand(
                        it.get("name") or "", str(it.get("productNumber") or "")
                    ),
                    "source_site": "SNKRDUNK",
                    "source_url": url,
                    "category": _category_label("trading-card"),
                    "category1": "SNKRDUNK",
                    "category2": _category_label("trading-card"),
                    "category3": "",
                    "color": "",
                    "url": url,
                    "video_url": url,
                    "options": [{"name": "기본", "price": sale_price, "stock": 1}],
                    "detail_html": "",
                    "free_shipping": False,
                    "sale_status": "in_stock",
                    "extra_data": {
                        "snkr_type": "trading-card",
                        "currency": TARGET_CURRENCY,
                        "product_number": it.get("productNumber"),
                        "min_price_format": it.get("minPriceFormat"),
                        "listing_count": listing_count,
                        "offer_count": str(it.get("offerCount", "")),
                        "released_at": it.get("releasedAt"),
                    },
                }
            )
        return results

    async def get_trading_card_detail(self, card_id: str) -> dict[str, Any]:
        """트레이딩카드 컨디션(옵션)별 최저가 수집.

        SNKRDUNK 트레이딩카드는 sneakers/streetwears 와 달리 JSON-LD 가 없고
        `/en/v1/products/SW---{id}/used-listings` API 로 컨디션별 중고 리스팅을 제공한다.

        규칙:
          - isOnlyOnSale=true → 판매중(재고 있는) 리스팅만 조회
          - 컨디션(PSA 10 / A / B ...)별로 그룹핑해 **최저가** 1건씩 옵션 생성
          - 재고(판매중 리스팅) 없는 컨디션은 옵션에서 제외 (수집 안 함)
          - stock = 해당 컨디션 판매중 리스팅 수 (실재고)
          - 통화 USD
        """
        import asyncio

        code_id = card_id
        name = ""
        name_ja = ""
        image = ""
        product_number = ""
        cond_min: dict[str, int] = {}
        cond_cnt: dict[str, int] = {}
        size_options: list[dict[str, Any]] = []
        box_min_price = 0

        async with httpx.AsyncClient(
            headers=JP_HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            # 1) JP 상세 — name(영문 유지)·품번·이미지·박스 minPrice(엔)
            try:
                dr = await client.get(JP_DETAIL_URL.format(id=card_id))
                dr.raise_for_status()
                dj = dr.json()
                name = (dj.get("name") or "").strip()
                name_ja = (dj.get("localizedName") or "").strip()  # 일문 상품명
                product_number = (dj.get("productNumber") or "").strip()
                pm = dj.get("primaryMedia") or {}
                image = (pm.get("imageUrl") or "").strip()
                _mp = dj.get("minPrice")
                if isinstance(_mp, (int, float)) and _mp > 0:
                    box_min_price = int(_mp)
            except Exception as e:
                logger.warning(f"[SNKRDUNK] JP 상세 실패 id={card_id}: {e}")

            # 2) 싱글 PSA 10 중고 — isSaleOnly=true(재고만) + 엔화 최저가
            page = 1
            while page <= 50:
                params = {
                    "perPage": 100,
                    "page": page,
                    "sizeId": 0,
                    "isSaleOnly": "true",
                }
                try:
                    r = await client.get(JP_USED_URL.format(id=code_id), params=params)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    logger.warning(
                        f"[SNKRDUNK] JP 카드 리스팅 실패 id={card_id} page={page}: {e}"
                    )
                    break
                items = data.get("apparelUsedItems") or []
                if not items:
                    break
                for x in items:
                    if not isinstance(x, dict):
                        continue
                    if x.get("isDisplaySold"):
                        continue  # 판매완료 제외(재고만)
                    cond = (x.get("displayShortConditionTitle") or "").strip()
                    # PSA 9/10 등급만 수집 — PSA 8/raw/BGS/ARS 제외(크림에서 개별 등급으로 거래되는 건 9·10뿐).
                    # PSA10 단일 하드코딩 시 PSA9 옵션 자체가 상품 DB에 없어 PSA9 주문 원가가 PSA10가로
                    # 오표시되는 사고 발생(2026-07-08) — 등급별로 옵션을 분리해야 함.
                    m = re.match(r"PSA(10|9)\b", cond.upper().replace(" ", ""))
                    if not m:
                        continue
                    price = x.get("price")
                    if not isinstance(price, (int, float)) or price <= 0:
                        continue
                    price = int(price)
                    ckey = f"PSA {m.group(1)}"
                    if ckey not in cond_min or price < cond_min[ckey]:
                        cond_min[ckey] = price
                    cond_cnt[ckey] = cond_cnt.get(ckey, 0) + 1
                if len(items) < 100:
                    break
                page += 1
                await asyncio.sleep(0.3)

            # 3) 박스/봉인(PSA10 중고 없음) → sizes 수량단 최저가(엔) 폴백
            if not cond_min:
                try:
                    sr = await client.get(JP_SIZES_URL.format(id=code_id))
                    sr.raise_for_status()
                    for sz in sr.json().get("sizePrices") or []:
                        if not isinstance(sz, dict):
                            continue
                        price = sz.get("minListingPrice") or sz.get(
                            "minNewListingPrice"
                        )
                        if not isinstance(price, (int, float)) or price <= 0:
                            continue
                        label = (
                            (sz.get("size") or {}).get("localizedName") or "기본"
                        ).strip()
                        cnt = sz.get("listingItemCount")
                        stock = int(cnt) if isinstance(cnt, (int, float)) else 0
                        if stock <= 0:
                            continue
                        size_options.append(
                            {"name": label, "price": int(price), "stock": stock}
                        )
                except Exception as e:
                    logger.warning(f"[SNKRDUNK] JP 박스 sizes 실패 id={card_id}: {e}")
                # sizes 도 비면 상세 minPrice 단일 옵션
                if not size_options and box_min_price > 0:
                    size_options.append(
                        {"name": "기본", "price": box_min_price, "stock": 1}
                    )

        # 재고 있는 컨디션만 옵션화 → 가격 오름차순 정렬
        if cond_min:
            options = [
                {"name": cond, "price": cond_min[cond], "stock": cond_cnt[cond]}
                for cond in cond_min
            ]
        else:
            options = size_options
        options.sort(key=lambda o: o["price"])

        sale_price = options[0]["price"] if options else 0
        sale_status = "in_stock" if options else "sold_out"
        url = _detail_url(card_id, "trading-card")
        return {
            "site_product_id": card_id,
            "name": name,
            "name_en": name,  # 영문 상품명(JP API name = 영문)
            "name_ja": name_ja,  # 일문 상품명(localizedName)
            "brand": _derive_card_brand(name, product_number),
            "sale_price": sale_price,
            "original_price": sale_price,
            "images": [image] if image else [],
            "options": options,
            "category": _category_label("trading-card"),
            "category1": "SNKRDUNK",
            "category2": _category_label("trading-card"),
            "category3": "",
            "source_site": "SNKRDUNK",
            "source_url": url,
            "url": url,
            "video_url": url,
            "detail_html": "",
            "sale_status": sale_status,
            "free_shipping": False,
            "color": "",
            "style_code": product_number,  # 품번 = productNumber (예: pkmn-tcg-SV-P-261)
            "extra_data": {
                "snkr_type": "trading-card",
                "currency": "JPY",  # JP API(엔화) 수집 — USD 아님
                "product_number": product_number,
                "condition_count": {k: cond_cnt[k] for k in cond_cnt},
            },
        }

    async def get_detail(
        self, site_product_id: str, snkr_type: str | None = None
    ) -> dict[str, Any]:
        """상품 상세 조회 — SSR HTML의 JSON-LD 추출.

        트레이딩카드는 JSON-LD 가 없으므로 컨디션별 used-listings API 로 분기.
        """
        if snkr_type == "trading-card":
            return await self.get_trading_card_detail(site_product_id)
        url = _detail_url(site_product_id, snkr_type)
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            try:
                r = await client.get(url)
                if r.status_code == 404 and snkr_type is None:
                    other_type = (
                        "streetwear"
                        if not _is_streetwear_id(site_product_id)
                        else "sneaker"
                    )
                    url = _detail_url(site_product_id, other_type)
                    r = await client.get(url)
                    snkr_type = other_type
                r.raise_for_status()
                html = r.text
            except Exception as e:
                logger.warning(f"[SNKRDUNK] 상세 실패 {site_product_id}: {e}")
                return {"error": str(e)}

        detected_type = snkr_type or (
            "streetwear" if _is_streetwear_id(site_product_id) else "sneaker"
        )
        return self._parse_detail(html, site_product_id, detected_type, url)

    @staticmethod
    def _parse_detail(
        html: str, site_product_id: str, snkr_type: str, url: str
    ) -> dict[str, Any]:
        """JSON-LD Product 노드 + AggregateOffer(priceCurrency=JPY)에서 필드 추출."""
        ld_products = _extract_jsonld_products(html)
        if not ld_products:
            return {"error": "JSON-LD Product 노드 없음"}

        prod = ld_products[0]
        name = (prod.get("name") or "").strip()
        image = prod.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
        brand_node = prod.get("brand") or {}
        brand = (
            brand_node.get("name") if isinstance(brand_node, dict) else str(brand_node)
        ) or ""

        # AggregateOffer 배열에서 JPY 항목 선택
        offers_root = prod.get("offers") or []
        if isinstance(offers_root, dict):
            offers_root = [offers_root]
        jpy_agg: dict[str, Any] | None = None
        for agg in offers_root:
            if isinstance(agg, dict) and agg.get("priceCurrency") == TARGET_CURRENCY:
                jpy_agg = agg
                break

        options: list[dict[str, Any]] = []
        low_price: float | None = None
        high_price: float | None = None
        availability = "out_of_stock"
        if jpy_agg:
            low_price = jpy_agg.get("lowPrice")
            high_price = jpy_agg.get("highPrice")
            inner = jpy_agg.get("offers") or []
            for o in inner:
                if not isinstance(o, dict):
                    continue
                if o.get("priceCurrency") != TARGET_CURRENCY:
                    continue
                size = _parse_size_label(o.get("description", ""))
                price = o.get("price")
                avail = o.get("availability", "")
                in_stock = avail.endswith("InStock")
                options.append(
                    {
                        "name": size or "기본",
                        "price": int(price) if isinstance(price, (int, float)) else 0,
                        "stock": 1 if in_stock else 0,
                    }
                )
            if any(opt.get("stock", 0) > 0 for opt in options):
                availability = "in_stock"

        # 옵션이 비어있으면 sold_out
        if not options:
            sale_status = "sold_out"
        else:
            sale_status = availability

        # 발매가 단서: 정상가 정보가 JSON-LD에 없으므로 lowPrice 를 정상가/할인가 동일 처리
        sale_price = int(low_price) if isinstance(low_price, (int, float)) else 0
        original_price = (
            int(high_price)
            if isinstance(high_price, (int, float)) and high_price
            else sale_price
        )

        release_date = prod.get("releaseDate") or ""

        return {
            "site_product_id": site_product_id,
            "name": name,
            "brand": brand,
            "sale_price": sale_price,
            "original_price": original_price,
            "images": [image] if image else [],
            "options": options,
            "category": "스니커즈" if snkr_type == "sneaker" else "스트릿웨어",
            "category1": "SNKRDUNK",
            "category2": "스니커즈" if snkr_type == "sneaker" else "스트릿웨어",
            "category3": "",
            "source_site": "SNKRDUNK",
            "source_url": url,
            "url": url,
            "video_url": url,
            "detail_html": "",
            "sale_status": sale_status,
            "free_shipping": False,
            "color": "",
            "extra_data": {
                "snkr_type": snkr_type,
                "currency": TARGET_CURRENCY,
                "release_date": release_date,
                "low_price": low_price,
                "high_price": high_price,
            },
        }


async def fetch_order_overseas_tracking(
    session_cookie: str,
    order_id: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """SNKRDUNK 구매주문의 해외송장(사무국→구매자 발송) 조회.

    session 쿠키 인증(MFA라 id/pw 자동로그인 불가 → 확장앱이 캡처한 쿠키 사용).
    발송 전(감정/발송대기)이면 tracking_number 는 빈 문자열로 반환.

    Returns:
        {
          "order_id": str,
          "tracking_number": str,       # order.trackingNumber (해외송장번호)
          "delivery_company": str,      # 표시명 (예: 야마토운수)
          "delivery_company_code": str, # 원본 코드 (예: yamato)
          "order_status": str,          # waiting-for-delivered-to-buyer 등
          "admin_shipped_at": str,      # 사무국 발송일 (없으면 "")
          "shipped": bool,              # trackingNumber 존재 여부
          "error": str,                 # 실패 시에만
        }
    """
    cookie = (session_cookie or "").strip()
    if not cookie:
        return {"order_id": str(order_id), "error": "session 쿠키 없음"}
    # 쿠키 문자열이 "session=..." 형태로 넘어와도 값만 추출
    if cookie.lower().startswith("session="):
        cookie = cookie.split("=", 1)[1]
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json",
        "Cookie": f"session={cookie}",
        "Referer": f"{BASE}/",
    }
    async with httpx.AsyncClient(
        headers=headers, timeout=timeout, follow_redirects=True
    ) as client:
        # 1) 주문 상세 — trackingNumber(해외송장)·orderStatus·orderAdminShippedAt
        try:
            r = await client.get(ORDER_DETAIL_URL.format(id=order_id))
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning(f"[SNKRDUNK] 주문상세 실패 id={order_id}: {e}")
            return {"order_id": str(order_id), "error": str(e)}

        order = (data.get("order") if isinstance(data, dict) else None) or {}
        tracking = str(order.get("trackingNumber") or "").strip()
        status = str(order.get("orderStatus") or "").strip()
        admin_shipped_raw = str(order.get("orderAdminShippedAt") or "").strip()
        # 0001-01-01 = 미발송 sentinel
        admin_shipped = (
            "" if admin_shipped_raw.startswith("0001") else admin_shipped_raw
        )

        # 2) 택배사 코드 (발송 후에만 유의미). 실패해도 송장은 반환.
        company_code = ""
        try:
            cr = await client.get(ORDER_DELIVERY_COMPANY_URL.format(id=order_id))
            if cr.status_code == 200:
                cj = cr.json()
                if isinstance(cj, dict):
                    company_code = str(cj.get("deliveryCompany") or "").strip()
        except Exception as e:
            logger.warning(f"[SNKRDUNK] 택배사 조회 실패 id={order_id}: {e}")

        label = _DELIVERY_COMPANY_LABELS.get(company_code.lower(), company_code)
        return {
            "order_id": str(order_id),
            "tracking_number": tracking,
            "delivery_company": label,
            "delivery_company_code": company_code,
            "order_status": status,
            "admin_shipped_at": admin_shipped,
            # 발송 판정: 송장 有 + 사무국 발송일(admin_shipped) 有 여야 진짜 배대지 발송.
            # admin_shipped 없이 송장만 있으면 셀러→사무국(감정센터) 송장이라 오수집됨.
            "shipped": bool(tracking) and bool(admin_shipped),
        }
