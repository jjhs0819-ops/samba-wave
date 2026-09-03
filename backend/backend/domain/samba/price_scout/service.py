"""주문건 소싱처 최저가 탐색 서비스.

기존 소싱 플러그인 레지스트리(plugins.SOURCING_PLUGINS)의 search() 를 직접 호출한다
— 전부 직접 HTTP 라 확장앱 큐 없이 동작한다
(proxy/sourcing.py 의 /sourcing/{site}/search 는 ABC·LOTTEON을 확장앱으로 보내므로 쓰지 않음).
"""

import asyncio
import logging
from typing import Any

from backend.domain.samba.price_scout.extractor import extract_model_code, normalize_code

logger = logging.getLogger(__name__)

# 탐색 대상 소싱처 — plugins.SOURCING_PLUGINS 의 site_name 과 정확히 일치해야 한다
SCOUT_SITES = ["MUSINSA", "ABCmart", "LOTTEON", "SSG", "THEHYUNDAI"]

# 사이트별 검색 타임아웃(초) / 전체 타임아웃(초)
SITE_TIMEOUT = 12.0
TOTAL_TIMEOUT = 25.0

# 검색 결과 항목에서 모델코드 매칭에 쓰는 이름/코드 후보 필드
_NAME_KEYS = (
    "name",
    "goodsName",
    "productName",
    "title",
    "styleCode",
    "styleNo",
    "modelCode",
    "code",
)

# 검색 결과 항목에서 가격으로 인정하는 후보 필드
_PRICE_KEYS = (
    "price",
    "salePrice",
    "sale_price",
    "discountPrice",
    "finalPrice",
    "lowestPrice",
)

# 검색 결과 항목에서 상품 링크 후보 필드
_URL_KEYS = ("sourceUrl", "url", "link", "goodsLinkUrl")

# 검색 결과 항목에서 상품 ID 후보 필드
_PRODUCT_ID_KEYS = ("siteProductId", "goodsNo", "productId", "id")


def _as_item_list(raw: Any) -> list[dict]:
    """plugin.search() 반환값을 항목 리스트로 정규화.

    대부분 list[dict] 지만 MUSINSA 는 {"success", "count", "data": [...]} dict 를
    반환하므로 (플러그인 시그니처 주석과 실제가 다름) 양쪽 다 수용한다.
    """
    if isinstance(raw, list):
        return [it for it in raw if isinstance(it, dict)]
    if isinstance(raw, dict):
        for key in ("data", "products", "list", "items"):
            inner = raw.get(key)
            if isinstance(inner, list):
                return [it for it in inner if isinstance(it, dict)]
    return []


def _item_matches_code(item: dict, norm_code: str) -> bool:
    """항목의 이름/코드 필드에 정규화된 모델코드가 포함되는지."""
    for key in _NAME_KEYS:
        val = item.get(key)
        if val and norm_code in normalize_code(str(val)):
            return True
    return False


def _extract_price(item: dict) -> int | None:
    """항목에서 0보다 큰 최소 정수 가격을 뽑는다. 없으면 None(→ 항목 제외)."""
    prices: list[int] = []
    for key in _PRICE_KEYS:
        val = item.get(key)
        if val is None:
            continue
        try:
            num = int(float(str(val).replace(",", "")))
        except (ValueError, TypeError):
            continue
        if num > 0:
            prices.append(num)
    return min(prices) if prices else None


def _first_str(item: dict, keys: tuple[str, ...]) -> str | None:
    """후보 키 중 첫 번째 truthy 문자열값."""
    for key in keys:
        val = item.get(key)
        if val:
            return str(val)
    return None


async def _search_site(site: str, code: str) -> list[dict]:
    """단일 사이트 검색 (사이트별 타임아웃 적용)."""
    from backend.domain.samba.plugins import SOURCING_PLUGINS

    plugin = SOURCING_PLUGINS.get(site)
    if plugin is None:
        raise RuntimeError(f"소싱 플러그인 미등록: {site}")
    raw = await asyncio.wait_for(plugin.search(code), timeout=SITE_TIMEOUT)
    return _as_item_list(raw)


async def scout_order(order) -> dict:
    """주문 1건의 소싱처 최저가 탐색.

    반환: {model_code, base_cost, best_site, best_price, best_url,
           results: [{site, price, name, url, product_id}], suspect, error}
    모델코드가 없으면 {"skipped": "모델코드 없음"}.
    실패한 사이트는 결과에서 빼고 warning 로그만 남긴다 — 예외를 위로 던지지 않는다.
    """
    code = extract_model_code(getattr(order, "product_name", None))
    if not code:
        return {"skipped": "모델코드 없음"}

    norm_code = normalize_code(code)
    base_cost = float(getattr(order, "cost", 0) or 0)

    site_results: list[Any]
    try:
        site_results = await asyncio.wait_for(
            asyncio.gather(
                *[_search_site(site, code) for site in SCOUT_SITES],
                return_exceptions=True,
            ),
            timeout=TOTAL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"[최저가탐색] 전체 타임아웃({TOTAL_TIMEOUT}s) — code={code}")
        return {
            "model_code": code,
            "base_cost": base_cost,
            "best_site": None,
            "best_price": None,
            "best_url": None,
            "results": [],
            "suspect": False,
            "error": f"전체 타임아웃({int(TOTAL_TIMEOUT)}초)",
        }

    results: list[dict] = []
    failed_sites: list[str] = []
    for site, raw in zip(SCOUT_SITES, site_results):
        if isinstance(raw, BaseException):
            failed_sites.append(site)
            logger.warning(f"[최저가탐색] {site} 검색 실패 — code={code}: {raw!r}")
            continue

        # 모델코드가 이름/코드 필드에 포함된 항목만 채택 → 사이트 내 최저가 1건
        best_item: dict | None = None
        best_item_price: int | None = None
        for item in raw:
            if not _item_matches_code(item, norm_code):
                continue
            price = _extract_price(item)
            if price is None:
                continue
            if best_item_price is None or price < best_item_price:
                best_item = item
                best_item_price = price

        if best_item is None or best_item_price is None:
            continue
        results.append(
            {
                "site": site,
                "price": best_item_price,
                "name": _first_str(best_item, _NAME_KEYS),
                "url": _first_str(best_item, _URL_KEYS),
                "product_id": _first_str(best_item, _PRODUCT_ID_KEYS),
            }
        )

    # 전체 최저가 산출
    best: dict | None = min(results, key=lambda r: r["price"]) if results else None
    best_price = best["price"] if best else None

    # 오매칭 의심 — 원가의 절반 미만이면 다른 상품일 가능성이 크다
    suspect = bool(
        best_price is not None and base_cost > 0 and best_price < base_cost * 0.5
    )

    error: str | None = None
    if not results and len(failed_sites) == len(SCOUT_SITES):
        error = "전 사이트 검색 실패"

    return {
        "model_code": code,
        "base_cost": base_cost,
        "best_site": best["site"] if best else None,
        "best_price": float(best_price) if best_price is not None else None,
        "best_url": best["url"] if best else None,
        "results": results,
        "suspect": suspect,
        "error": error,
    }
