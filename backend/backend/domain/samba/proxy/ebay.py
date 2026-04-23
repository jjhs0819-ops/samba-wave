"""eBay Inventory API 클라이언트 - 상품 등록/수정/삭제.

인증 방식: OAuth 2.0 (Authorization Code Grant)
- Refresh Token → Access Token 자동 발급 (2시간 캐싱)
- Authorization: Basic base64(appId:certId)

등록 플로우 3단계:
  1. PUT  /sell/inventory/v1/inventory_item/{SKU}  → 상품 정보
  2. POST /sell/inventory/v1/offer                 → 가격/정책/카테고리
  3. POST /sell/inventory/v1/offer/{offerId}/publish → 실제 리스팅
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any
from urllib.parse import quote

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


# eBay 신발 카테고리 ID (Men's Shoes, Women's Shoes, Kids' Shoes 하위 전체)
_SHOES_CATEGORY_IDS = {
    "15709",  # Men's Athletic Shoes
    "93427",  # Women's Athletic Shoes
    "57929",  # Kids' Athletic Shoes
    "53557",  # Men's Shoes (상위)
    "3034",  # Women's Shoes (상위)
    "57974",  # Kids & Baby Shoes
    "181304",  # Other Climbing & Caving
    "155202",  # Men's Shoes
    "62107",  # Men's Boots
    "62109",  # Women's Boots
    "95672",  # Outdoor Sports: Climbing Footwear
    "57990",  # Hiking Shoes/Boots
    "159094",  # Athletic Shoes (Unisex)
    "24087",  # Men's Hiking Shoes
    "24088",  # Women's Hiking Shoes
}


def _is_shoes_category(category_id: str) -> bool:
    """신발 카테고리인지 확인."""
    return category_id in _SHOES_CATEGORY_IDS


def _category_looks_like_shoes(product: dict) -> bool:
    """수집 카테고리 이름에 '신발/화/부츠' 등 신발 키워드가 포함되어 있는지."""
    cat = product.get("category") or ""
    for k in ("category4", "category3", "category2", "category1"):
        v = product.get(k)
        if v:
            cat += " " + v
    keywords = [
        "신발",
        "화",
        "부츠",
        "슈즈",
        "샌들",
        "슬리퍼",
        "Shoe",
        "Boot",
        "Sneaker",
    ]
    return any(k in cat for k in keywords)


class EbayApiError(Exception):
    """eBay API 에러."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


# ─── 프록시 인스턴스 간 공유 캐시 (모듈 레벨) ───
# EbayClient는 매 요청마다 새로 생성되므로 인스턴스 캐시는 의미 없음
# 전역 dict로 SKU → hash/offer_id 매핑을 영구 유지 (프로세스 라이프)
_inventory_item_hash_cache: dict[
    str, str
] = {}  # sku → md5 hash of last sent inventory_item
_offer_id_cache: dict[str, str] = {}  # sku → offer_id (SKU 조회 생략용)
_ebay_cache_max_size = 5000  # 과도한 메모리 사용 방지


def _evict_if_needed(cache: dict) -> None:
    """캐시 크기가 max 초과 시 앞쪽 절반 삭제 (FIFO LRU 근사)."""
    if len(cache) > _ebay_cache_max_size:
        to_remove = len(cache) - (_ebay_cache_max_size // 2)
        keys_to_remove = list(cache.keys())[:to_remove]
        for k in keys_to_remove:
            cache.pop(k, None)


class EbayClient:
    """eBay Inventory API + Account API 클라이언트."""

    BASE_URL = "https://api.ebay.com"
    SANDBOX_URL = "https://api.sandbox.ebay.com"
    # Finance API는 별도 호스트(apiz) 사용
    FINANCE_URL = "https://apiz.ebay.com"
    FINANCE_SANDBOX_URL = "https://apiz.sandbox.ebay.com"
    TOKEN_URL_PROD = "https://api.ebay.com/identity/v1/oauth2/token"
    TOKEN_URL_SANDBOX = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

    # EBAY_US 카테고리 트리 ID
    CATEGORY_TREE_ID = "0"
    MARKETPLACE_ID = "EBAY_US"

    def __init__(
        self,
        app_id: str,
        dev_id: str,
        cert_id: str,
        refresh_token: str,
        sandbox: bool = False,
    ) -> None:
        self.app_id = app_id
        self.dev_id = dev_id
        self.cert_id = cert_id
        self.refresh_token = refresh_token
        self.sandbox = sandbox

        self._base_url = self.SANDBOX_URL if sandbox else self.BASE_URL
        self._token_url = self.TOKEN_URL_SANDBOX if sandbox else self.TOKEN_URL_PROD
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._app_token: str = ""
        self._app_token_expires_at: float = 0.0

    # -------------------------------------------------------------------------
    # OAuth 2.0 토큰 관리
    # -------------------------------------------------------------------------

    def _basic_auth(self) -> str:
        """app_id:cert_id Base64 인코딩 → Basic 인증 헤더 값."""
        raw = f"{self.app_id}:{self.cert_id}"
        return base64.b64encode(raw.encode()).decode()

    async def _get_access_token(self) -> str:
        """Refresh Token → Access Token 자동 발급 (2시간 캐싱)."""
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        headers = {
            "Authorization": f"Basic {self._basic_auth()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "scope": (
                "https://api.ebay.com/oauth/api_scope/sell.inventory "
                "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly "
                "https://api.ebay.com/oauth/api_scope/sell.account "
                "https://api.ebay.com/oauth/api_scope/sell.account.readonly "
                "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
                "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly "
                "https://api.ebay.com/oauth/api_scope/sell.finances "
                "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly"
            ),
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._token_url, headers=headers, data=data)

        if resp.status_code != 200:
            raise EbayApiError(f"eBay 토큰 발급 실패 ({resp.status_code}): {resp.text}")

        result = resp.json()
        self._access_token = result["access_token"]
        # expires_in 기본 7200초
        self._token_expires_at = now + result.get("expires_in", 7200)
        logger.info("[eBay] Access Token 발급 완료")
        return self._access_token

    async def _get_application_token(self) -> str:
        """Application Token 발급 (client_credentials). Taxonomy API 등 공개 API용."""
        now = time.time()
        if self._app_token and now < self._app_token_expires_at - 60:
            return self._app_token

        headers = {
            "Authorization": f"Basic {self._basic_auth()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._token_url, headers=headers, data=data)

        if resp.status_code != 200:
            raise EbayApiError(
                f"eBay Application Token 발급 실패 ({resp.status_code}): {resp.text}"
            )

        result = resp.json()
        self._app_token = result["access_token"]
        self._app_token_expires_at = now + result.get("expires_in", 7200)
        logger.info("[eBay] Application Token 발급 완료")
        return self._app_token

    async def _headers(self) -> dict[str, str]:
        token = await self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-US",
            "X-EBAY-C-MARKETPLACE-ID": self.MARKETPLACE_ID,
        }

    # -------------------------------------------------------------------------
    # 공통 HTTP 호출
    # -------------------------------------------------------------------------

    async def _call(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """공통 API 호출. 빈 응답(204)은 {} 반환."""
        url = f"{self._base_url}{path}"
        headers = await self._headers()

        async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                resp = await client.post(url, headers=headers, json=body, params=params)
            elif method == "PUT":
                resp = await client.put(url, headers=headers, json=body, params=params)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, params=params)
            else:
                raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

        logger.debug("[eBay] %s %s → %d", method, path, resp.status_code)

        if resp.status_code == 204:
            return {}

        if resp.status_code >= 400:
            try:
                err_body = resp.json()
                errors = err_body.get("errors", [])
                msg = errors[0].get("message", resp.text) if errors else resp.text
            except Exception:
                msg = resp.text[:500]
                errors = []
            logger.error(
                "[eBay] API 에러 %s %s → %d: %s | errors=%s",
                method,
                path,
                resp.status_code,
                msg,
                errors,
            )
            # 25604(Product not found) 에러 디버깅용 — 요청 body 로깅
            if any(e.get("errorId") == 25604 for e in errors):
                import json as _json

                try:
                    body_preview = _json.dumps(body, ensure_ascii=False)[:2000]
                    logger.error(
                        "[eBay 25604 디버그] path=%s body=%s",
                        path,
                        body_preview,
                    )
                except Exception:
                    pass
            # 에러 메시지에 전체 에러 포함 (프론트 로그에서 확인 가능)
            full_msg = msg
            if len(errors) > 1:
                full_msg = " | ".join(e.get("message", "") for e in errors)
            raise EbayApiError(
                f"eBay API 오류 ({resp.status_code}): {full_msg}", errors
            )

        if not resp.content:
            return {}

        return resp.json()

    # -------------------------------------------------------------------------
    # Inventory Item
    # -------------------------------------------------------------------------

    async def create_inventory_item(self, sku: str, data: dict) -> dict:
        """Inventory Item 생성/업데이트.

        PUT /sell/inventory/v1/inventory_item/{SKU}
        성공 시 204 No Content → {} 반환.
        """
        encoded_sku = quote(sku, safe="")
        return await self._call(
            "PUT", f"/sell/inventory/v1/inventory_item/{encoded_sku}", body=data
        )

    async def get_inventory_item(self, sku: str) -> dict:
        """GET /sell/inventory/v1/inventory_item/{SKU}."""
        encoded_sku = quote(sku, safe="")
        return await self._call(
            "GET", f"/sell/inventory/v1/inventory_item/{encoded_sku}"
        )

    async def delete_inventory_item(self, sku: str) -> dict:
        """DELETE /sell/inventory/v1/inventory_item/{SKU}."""
        # 캐시 무효화 (상품이 삭제되므로 offer_id/hash 모두 제거)
        _inventory_item_hash_cache.pop(sku, None)
        _offer_id_cache.pop(sku, None)
        encoded_sku = quote(sku, safe="")
        return await self._call(
            "DELETE", f"/sell/inventory/v1/inventory_item/{encoded_sku}"
        )

    # -------------------------------------------------------------------------
    # Offer
    # -------------------------------------------------------------------------

    async def create_offer(self, data: dict) -> str:
        """Offer 생성.

        POST /sell/inventory/v1/offer
        반환: offerId (string)
        """
        result = await self._call("POST", "/sell/inventory/v1/offer", body=data)
        offer_id = result.get("offerId", "")
        if not offer_id:
            raise EbayApiError(f"offerId 미반환: {result}")
        return offer_id

    async def get_offers_by_sku(self, sku: str) -> list:
        """SKU로 연결된 Offer 목록 조회."""
        result = await self._call(
            "GET", "/sell/inventory/v1/offer", params={"sku": sku}
        )
        return result.get("offers", [])

    async def update_offer(self, offer_id: str, data: dict) -> dict:
        """Offer 수정. PUT /sell/inventory/v1/offer/{offerId}."""
        return await self._call(
            "PUT", f"/sell/inventory/v1/offer/{offer_id}", body=data
        )

    async def publish_offer(self, offer_id: str) -> str:
        """Offer 게시 → listingId 반환.

        POST /sell/inventory/v1/offer/{offerId}/publish
        """
        result = await self._call(
            "POST", f"/sell/inventory/v1/offer/{offer_id}/publish"
        )
        listing_id = result.get("listingId", "")
        if not listing_id:
            raise EbayApiError(f"listingId 미반환: {result}")
        return listing_id

    async def withdraw_offer(self, offer_id: str) -> dict:
        """리스팅 판매중지(철회).

        POST /sell/inventory/v1/offer/{offerId}/withdraw
        """
        return await self._call("POST", f"/sell/inventory/v1/offer/{offer_id}/withdraw")

    # -------------------------------------------------------------------------
    # Business Policy 조회 (배송/결제/반품)
    # -------------------------------------------------------------------------

    async def get_fulfillment_policies(self) -> list:
        """배송 정책 목록. GET /sell/account/v1/fulfillment_policy."""
        result = await self._call(
            "GET",
            "/sell/account/v1/fulfillment_policy",
            params={"marketplace_id": self.MARKETPLACE_ID},
        )
        return result.get("fulfillmentPolicies", [])

    async def get_payment_policies(self) -> list:
        """결제 정책 목록. GET /sell/account/v1/payment_policy."""
        result = await self._call(
            "GET",
            "/sell/account/v1/payment_policy",
            params={"marketplace_id": self.MARKETPLACE_ID},
        )
        return result.get("paymentPolicies", [])

    async def get_return_policies(self) -> list:
        """반품 정책 목록. GET /sell/account/v1/return_policy."""
        result = await self._call(
            "GET",
            "/sell/account/v1/return_policy",
            params={"marketplace_id": self.MARKETPLACE_ID},
        )
        return result.get("returnPolicies", [])

    # -------------------------------------------------------------------------
    # 카테고리
    # -------------------------------------------------------------------------

    async def suggest_category(self, query: str) -> list:
        """키워드 기반 카테고리 추천 (Application Token 사용).

        GET /commerce/taxonomy/v1/category_tree/{id}/get_category_suggestions?q={query}
        반환: [{"categoryId": "...", "categoryName": "...", "categoryPath": "..."}]
        """
        token = await self._get_application_token()
        url = (
            f"{self._base_url}/commerce/taxonomy/v1/category_tree/"
            f"{self.CATEGORY_TREE_ID}/get_category_suggestions"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params={"q": query})
        if resp.status_code != 200:
            logger.warning(
                "[eBay] suggest_category 실패 (%d): %s",
                resp.status_code,
                resp.text[:200],
            )
            return []
        result = resp.json()
        suggestions = result.get("categorySuggestions", [])
        results = []
        for s in suggestions:
            cat = s.get("category", {})
            ancestors = s.get("categoryTreeNodeAncestors", [])
            # 전체 경로 구성: 최상위 → 최하위
            path_parts = [a.get("categoryName", "") for a in reversed(ancestors)]
            path_parts.append(cat.get("categoryName", ""))
            full_path = " > ".join(p for p in path_parts if p)
            results.append(
                {
                    "categoryId": cat.get("categoryId", ""),
                    "categoryName": cat.get("categoryName", ""),
                    "categoryPath": full_path,
                }
            )
        return results

    async def get_category_tree(self) -> dict:
        """전체 카테고리 트리 조회 (Application Token 사용).

        GET /commerce/taxonomy/v1/category_tree/{id}
        Taxonomy API는 Application Token(client_credentials)이 필요.
        반환: rootCategoryNode 포함 트리 구조
        """
        token = await self._get_application_token()
        url = f"{self._base_url}/commerce/taxonomy/v1/category_tree/{self.CATEGORY_TREE_ID}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise EbayApiError(
                f"eBay 카테고리 트리 조회 실패 ({resp.status_code}): {resp.text[:200]}"
            )
        return resp.json()

    async def get_item_aspects_for_category(self, category_id: str) -> list:
        """카테고리별 필수 aspect 목록 조회.

        GET /commerce/taxonomy/v1/category_tree/{id}/get_item_aspects_for_category
        반환: [{"name": "...", "required": bool, "values": [...]}, ...]
        """
        token = await self._get_application_token()
        url = (
            f"{self._base_url}/commerce/taxonomy/v1/category_tree/"
            f"{self.CATEGORY_TREE_ID}/get_item_aspects_for_category"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url, headers=headers, params={"category_id": category_id}
            )
        if resp.status_code != 200:
            logger.warning(
                "[eBay] 카테고리 aspect 조회 실패 (%s): %s",
                resp.status_code,
                resp.text[:200],
            )
            return []
        data = resp.json()
        result = []
        for asp in data.get("aspects", []):
            constraint = asp.get("aspectConstraint", {})
            values = [v.get("localizedValue", "") for v in asp.get("aspectValues", [])]
            result.append(
                {
                    "name": asp.get("localizedAspectName", ""),
                    "required": constraint.get("aspectRequired", False),
                    "data_type": constraint.get("aspectDataType", "STRING"),
                    "values": values,
                }
            )
        return result

    async def _fill_required_aspects(
        self, inventory_item: dict, category_id: str
    ) -> None:
        """카테고리별 필수 aspect를 inventory_item에 자동 채우기.

        값이 없는 필수 aspect는 허용값 목록의 첫 번째 값 또는 'Other'로 설정.
        """
        if not category_id:
            return
        try:
            required_aspects = await self.get_item_aspects_for_category(category_id)
        except Exception as e:
            logger.warning("[eBay] 카테고리 aspect 조회 실패: %s", e)
            return

        current_aspects = inventory_item.setdefault("product", {}).setdefault(
            "aspects", {}
        )
        for asp in required_aspects:
            if not asp.get("required"):
                continue
            name = asp["name"]
            if name in current_aspects and current_aspects[name]:
                continue  # 이미 값이 있음
            values = asp.get("values", [])
            if values:
                current_aspects[name] = [values[0]]
            else:
                current_aspects[name] = ["Other"]
            logger.info(
                "[eBay] 필수 aspect 자동 설정: %s = %s",
                name,
                current_aspects[name],
            )

    # -------------------------------------------------------------------------
    # 상품 데이터 변환 (CollectedProduct → eBay Inventory API 포맷)
    # -------------------------------------------------------------------------

    @staticmethod
    def transform_product(product: dict, category_id: str, **kwargs) -> dict:
        """CollectedProduct dict → eBay Inventory Item + Offer 포맷.

        반환 구조:
        {
          "inventory_item": { ... },   # PUT /inventory_item/{SKU} 바디
          "offer": { ... },            # POST /offer 바디
          "sku": "...",
        }
        """
        # eBay US는 영문 상품명 우선. name_en(DB 필드) → ebay_title → name 순서
        name = (
            product.get("name_en")
            or product.get("ebay_title")
            or product.get("name", "")
        )[:80]
        brand = product.get("brand") or "Unbranded"
        color = product.get("color") or ""
        material = product.get("material") or ""
        origin = product.get("origin") or ""
        options = product.get("options") or []

        # SKU: style_code 우선, 없으면 source_product_id
        sku = (
            product.get("style_code")
            or str(product.get("source_product_id", ""))
            or str(product.get("id", "unknown"))
        )

        # 이미지: 최대 12장
        images: list[str] = product.get("images") or []
        detail_images: list[str] = product.get("detail_images") or []
        all_images = (images + detail_images)[:12]

        # Aspects (카테고리별 필수 속성)
        aspects: dict[str, list[str]] = {}
        if brand:
            aspects["Brand"] = [brand]
        if color:
            aspects["Color"] = [color]
        if material:
            aspects["Material"] = [material]
        if origin:
            aspects["Country/Region of Manufacture"] = [origin]

        # 사이즈 옵션 추출 — "색상 / 사이즈" 형식이면 사이즈 부분만 추출
        def _extract_size(raw: str) -> str:
            if not raw:
                return ""
            # "/" 구분자로 분리되어 있으면 마지막 토큰이 사이즈
            if "/" in raw:
                parts = [p.strip() for p in raw.split("/") if p.strip()]
                if parts:
                    return parts[-1]
            return raw.strip()

        sizes = [
            _extract_size(
                opt.get("size") or opt.get("name") or opt.get("option_value", "")
            )
            for opt in options
            if opt.get("sale_status") != "sold_out"
        ]
        sizes = [s for s in sizes if s]
        if sizes:
            first_size = sizes[0]
            # 한글이 포함된 값은 사이즈가 아닌 상품 변형명 → "One Size"
            if any("가" <= c <= "힣" for c in first_size):
                aspects["Size"] = ["One Size"]
            else:
                aspects["Size"] = [first_size]

        # Department — 상품명 기반 추론 (수집 데이터 sex가 부정확한 경우 많음)
        name_text = (product.get("name") or "") + " " + (product.get("name_en") or "")
        department = ""
        name_lower = name_text.lower()
        if "여성" in name_text or "여자" in name_text or "women" in name_lower:
            department = "Women"
        elif (
            "남성" in name_text
            or "남자" in name_text
            or "men's" in name_lower
            or "men " in name_lower
        ):
            department = "Men"
        elif "키즈" in name_text or "아동" in name_text or "kids" in name_lower:
            department = "Kids"
        # 추론 실패 → sex 컬럼
        if not department:
            department = (
                product.get("sex")
                or product.get("gender")
                or product.get("department")
                or "Unisex Adults"
            )
        # 한글 잔존 시 Unisex Adults
        if not department or any("가" <= c <= "힣" for c in department):
            department = "Unisex Adults"
        aspects["Department"] = [department]

        # 신발 카테고리 감지 (ID 기반 + 카테고리명 키워드 기반)
        is_shoes = _is_shoes_category(category_id) or _category_looks_like_shoes(
            product
        )
        if is_shoes and sizes:
            from backend.domain.samba.ebay_mapping.seed import (
                convert_shoe_size_kr_to_us,
            )

            us_size = convert_shoe_size_kr_to_us(sizes[0], department)
            if us_size:
                aspects["US Shoe Size"] = [us_size]
                # Size 필드도 US 사이즈로 표시 (한국 mm 대신)
                aspects["Size"] = [us_size]
        elif not is_shoes and sizes:
            # 의류 사이즈 변환 (한국 081 → US S 등, 범위 기반)
            from backend.domain.samba.ebay_mapping.seed import (
                convert_clothing_size_kr_to_us,
            )

            us_clothing_size = convert_clothing_size_kr_to_us(sizes[0], department)
            if us_clothing_size:
                aspects["Size"] = [us_clothing_size]

        # Model — style_code (DB 수집 컬럼)
        if product.get("style_code"):
            aspects["Model"] = [str(product["style_code"])]
            aspects["Style Code"] = [str(product["style_code"])]

        # Manufacturer — manufacturer 컬럼 > brand 폴백
        # "Unbranded"/"Manufacturer" 등 의미없는 값이면 brand로 교체
        mfr = product.get("manufacturer") or ""
        _invalid_mfr = {
            "unbranded",
            "manufacturer",
            "n/a",
            "unknown",
            "",
        }
        if (
            not mfr
            or mfr.strip().lower() in _invalid_mfr
            or any("가" <= c <= "힣" for c in mfr)
        ):
            mfr = brand or ""
        if mfr and mfr != "Unbranded":
            aspects["Manufacturer"] = [mfr]

        # Type — 카테고리 leaf에서 TYPE_SEED 매핑 조회
        from backend.domain.samba.ebay_mapping.seed import TYPE_SEED

        product_type = product.get("product_type", "")
        if not product_type:
            # 카테고리 leaf 추출 (category4 → category3 → ... → category)
            cat_leaf = ""
            for k in ("category4", "category3", "category2", "category1"):
                v = product.get(k)
                if v:
                    cat_leaf = v.strip()
                    break
            if not cat_leaf and product.get("category"):
                # "스포츠/레저 > 잡화 > 장갑" → 마지막 토큰
                cat_leaf = product["category"].split(">")[-1].strip()
            # TYPE_SEED 조회 (포함 매칭)
            if cat_leaf:
                for kr_kw, en_type in TYPE_SEED.items():
                    if kr_kw in cat_leaf:
                        product_type = en_type
                        break
        if not product_type:
            product_type = "Sneakers" if is_shoes else "Other"
        aspects["Type"] = [product_type]
        # Style — 신발은 Athletic, 의류는 Casual
        aspects["Style"] = [
            product.get("style") or ("Athletic" if is_shoes else "Casual")
        ]
        # Size Type — 신발: Men's/Women's, 의류: Regular
        if is_shoes:
            shoe_size_type = (
                "Women's" if "Women" in department or "Girls" in department else "Men's"
            )
            aspects["Size Type"] = [product.get("size_type") or shoe_size_type]
        else:
            aspects["Size Type"] = [product.get("size_type") or "Regular"]
        # Pattern (의류 일부 카테고리 필수) — 기본 Solid
        aspects["Pattern"] = [product.get("pattern") or "Solid"]
        # Color 폴백
        if "Color" not in aspects:
            aspects["Color"] = ["Multicolor"]
        # Material 폴백
        if "Material" not in aspects:
            aspects["Material"] = ["Mixed Materials"]
        # Upper Material (신발 카테고리용, material 값 재사용)
        if material and "Upper Material" not in aspects:
            aspects["Upper Material"] = [material]

        # Season — season 컬럼에서 정규화
        if product.get("season"):
            from backend.domain.samba.ebay_mapping.seed import extract_season

            season_val = extract_season(product["season"])
            if season_val:
                aspects["Season"] = [season_val]

        # Garment Care — care_instructions 키워드 기반 단순화
        if product.get("care_instructions"):
            from backend.domain.samba.ebay_mapping.seed import extract_care_code

            care_val = extract_care_code(product["care_instructions"])
            if care_val:
                aspects["Garment Care"] = [care_val]

        # MPN (= style_code, Model과 동일)
        if product.get("style_code") and "MPN" not in aspects:
            aspects["MPN"] = [str(product["style_code"])]

        # 고정값 aspects (무재고 위탁판매 정책)
        aspects.setdefault("Vintage", ["No"])
        aspects.setdefault("Handmade", ["No"])
        aspects.setdefault("Personalize", ["No"])
        aspects.setdefault("Unit Quantity", ["1"])
        aspects.setdefault("Unit Type", ["Item"])
        aspects.setdefault("California Prop 65 Warning", ["No warning applicable"])

        # eBay 재고 고정: 항상 1개로 고정 (무재고 위탁판매 정책)
        # 소싱처 재고 변동과 무관하게 eBay는 1개로 유지 — 주문 시 수동 발주 처리
        quantity = 1

        # 가격: sale_price 우선, 없으면 original_price
        price_krw = float(
            product.get("sale_price") or product.get("original_price") or 0
        )
        # KRW → USD 환율 (kwargs로 exchange_rate 전달 가능, 기본 1400)
        exchange_rate = float(kwargs.get("exchange_rate", 1400))
        price_usd = round(price_krw / exchange_rate, 2) if price_krw > 0 else 0.0

        # 상세 설명: detail_html 우선, 없으면 이미지 HTML 생성
        description = product.get("detail_html") or ""
        if not description and all_images:
            img_tags = "".join(
                f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                for img in all_images
            )
            description = img_tags
        if not description:
            description = f"<p>{name}</p>"

        # eBay Inventory Item 포맷
        inventory_item: dict[str, Any] = {
            "product": {
                "title": name,
                "description": description,
                "imageUrls": all_images,
                "aspects": aspects,
            },
            "condition": "NEW",
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": quantity,
                }
            },
        }

        # Offer 포맷 (정책 ID는 kwargs 또는 계정 creds에서 전달)
        listing_policies: dict[str, str] = {}
        if kwargs.get("fulfillment_policy_id"):
            listing_policies["fulfillmentPolicyId"] = kwargs["fulfillment_policy_id"]
        if kwargs.get("payment_policy_id"):
            listing_policies["paymentPolicyId"] = kwargs["payment_policy_id"]
        if kwargs.get("return_policy_id"):
            listing_policies["returnPolicyId"] = kwargs["return_policy_id"]

        offer: dict[str, Any] = {
            "sku": sku,
            "marketplaceId": "EBAY_US",
            "format": "FIXED_PRICE",
            "availableQuantity": quantity,
            "categoryId": category_id or "",
            "listingDescription": description,
            "pricingSummary": {
                "price": {
                    "value": str(price_usd),
                    "currency": "USD",
                }
            },
            "listingPolicies": listing_policies,
        }
        if kwargs.get("merchant_location_key"):
            offer["merchantLocationKey"] = kwargs["merchant_location_key"]

        return {
            "sku": sku,
            "inventory_item": inventory_item,
            "offer": offer,
        }

    # -------------------------------------------------------------------------
    # 상품 등록 (3단계 플로우)
    # -------------------------------------------------------------------------

    async def register_product(
        self,
        data: dict,
        fulfillment_policy_id: str = "",
        payment_policy_id: str = "",
        return_policy_id: str = "",
        merchant_location_key: str = "",
    ) -> dict:
        """상품 등록 3단계: Inventory Item → Offer → Publish.

        data: transform_product() 반환값 또는 동일 구조 dict.
        반환: {"listingId": "...", "offerId": "...", "sku": "..."}
        """
        sku = data.get("sku", "")
        inventory_item = data.get("inventory_item", {})
        offer_data = data.get("offer", {})

        # 정책 ID 오버라이드 (전달된 경우)
        if fulfillment_policy_id:
            offer_data.setdefault("listingPolicies", {})["fulfillmentPolicyId"] = (
                fulfillment_policy_id
            )
        if payment_policy_id:
            offer_data.setdefault("listingPolicies", {})["paymentPolicyId"] = (
                payment_policy_id
            )
        if return_policy_id:
            offer_data.setdefault("listingPolicies", {})["returnPolicyId"] = (
                return_policy_id
            )
        if merchant_location_key:
            offer_data["merchantLocationKey"] = merchant_location_key

        # 카테고리별 필수 aspect 자동 채우기
        category_id = offer_data.get("categoryId", "")
        await self._fill_required_aspects(inventory_item, category_id)

        # Step 1: Inventory Item 생성
        logger.info("[eBay] Inventory Item 생성: SKU=%s", sku)
        await self.create_inventory_item(sku, inventory_item)

        # Step 2: Offer 생성 (기존 Offer 있으면 삭제 후 재생성)
        logger.info(
            "[eBay] Offer 생성: SKU=%s, category=%s", sku, offer_data.get("categoryId")
        )
        try:
            offer_id = await self.create_offer(offer_data)
        except EbayApiError as e:
            if any(err.get("errorId") == 25002 for err in (e.errors or [])):
                # "Offer entity already exists" — 기존 Offer 삭제 후 재시도
                logger.info("[eBay] 기존 Offer 존재, 삭제 후 재생성")
                existing = await self._call(
                    "GET", "/sell/inventory/v1/offer", params={"sku": sku}
                )
                for old_offer in existing.get("offers", []):
                    old_id = old_offer.get("offerId", "")
                    if old_offer.get("status") == "PUBLISHED":
                        await self.withdraw_offer(old_id)
                    await self._call("DELETE", f"/sell/inventory/v1/offer/{old_id}")
                offer_id = await self.create_offer(offer_data)
            else:
                raise

        # Step 3: Publish
        logger.info("[eBay] Offer 게시: offerId=%s", offer_id)
        listing_id = await self.publish_offer(offer_id)

        # 캐시 채우기 (다음 업데이트 시 get_offers_by_sku 생략)
        _offer_id_cache[sku] = offer_id
        try:
            import hashlib as _h1
            import json as _j1

            _inv_hash = _h1.md5(
                _j1.dumps(inventory_item, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            _inventory_item_hash_cache[sku] = _inv_hash
            _evict_if_needed(_offer_id_cache)
            _evict_if_needed(_inventory_item_hash_cache)
        except Exception:
            pass

        logger.info("[eBay] 등록 완료: listingId=%s", listing_id)
        return {"listingId": listing_id, "offerId": offer_id, "sku": sku}

    async def update_product(self, data: dict) -> dict:
        """기존 상품 수정 — Inventory Item + Offer 업데이트.

        data: transform_product() 반환값.
        existing_offer_id가 data에 있으면 Offer 수정, 없으면 SKU로 조회.
        Offer가 없으면 자동으로 신규 등록으로 폴백.

        성능 최적화:
        - Inventory Item 해시 캐시: 이전과 동일하면 PUT 스킵 (가격만 변경 시)
        - Offer ID 캐시: SKU 조회 API 호출 스킵
        - 병렬 실행: Inventory PUT과 Offer PUT을 asyncio.gather로 동시 실행
        """
        import hashlib as _hashlib
        import json as _json

        sku = data.get("sku", "")
        inventory_item = data.get("inventory_item", {})
        offer_data = data.get("offer", {})

        # 카테고리별 필수 aspect 자동 채우기
        category_id = offer_data.get("categoryId", "")
        await self._fill_required_aspects(inventory_item, category_id)

        # ─── 최적화 1: Inventory Item 해시 비교 ───
        try:
            inv_hash = _hashlib.md5(
                _json.dumps(inventory_item, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        except Exception:
            inv_hash = ""

        skip_inventory = (
            inv_hash
            and sku in _inventory_item_hash_cache
            and _inventory_item_hash_cache[sku] == inv_hash
        )

        # ─── 최적화 2: Offer ID 캐시 조회 ───
        offer_id = data.get("existing_offer_id", "") or _offer_id_cache.get(sku, "")

        if not offer_id:
            try:
                offers = await self.get_offers_by_sku(sku)
                if offers:
                    offer_id = offers[0].get("offerId", "")
                    if offer_id:
                        _offer_id_cache[sku] = offer_id
                        _evict_if_needed(_offer_id_cache)
            except Exception as e:
                logger.warning("[eBay] Offer 조회 실패 (신규 등록으로 폴백): %s", e)

        async def _safe_create_offer(sku_arg: str, offer: dict) -> str:
            """Offer 생성 — 25002(이미 존재) 발생 시 기존 삭제 후 재생성."""
            try:
                return await self.create_offer(offer)
            except EbayApiError as ce:
                if any(err.get("errorId") == 25002 for err in (ce.errors or [])):
                    logger.info("[eBay] 폴백 중 기존 Offer 존재, 삭제 후 재생성")
                    existing = await self._call(
                        "GET", "/sell/inventory/v1/offer", params={"sku": sku_arg}
                    )
                    for old_offer in existing.get("offers", []):
                        old_id = old_offer.get("offerId", "")
                        if old_offer.get("status") == "PUBLISHED":
                            try:
                                await self.withdraw_offer(old_id)
                            except Exception:
                                pass
                        try:
                            await self._call(
                                "DELETE", f"/sell/inventory/v1/offer/{old_id}"
                            )
                        except Exception:
                            pass
                    return await self.create_offer(offer)
                raise

        # Offer 없으면 신규 등록으로 폴백
        if not offer_id:
            logger.info("[eBay] 기존 Offer 없음 — 신규 등록 시도: SKU=%s", sku)
            try:
                offer_id = await _safe_create_offer(sku, offer_data)
                logger.info("[eBay] Offer 게시: offerId=%s", offer_id)
                listing_id = await self.publish_offer(offer_id)
                return {"listingId": listing_id, "offerId": offer_id, "sku": sku}
            except Exception as e:
                logger.error("[eBay] 폴백 신규 등록 실패: %s", e)
                raise

        # 일시 오류(500/Internal/Product not found/system error)는 재시도만, 폴백 금지
        # → 일시 오류를 "offer 없음"으로 오해해 publish_offer로 새 리스팅을 만들면 Insertion Fee 발생
        async def _update_with_retry(offer_id_arg: str, data: dict) -> None:
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    await self.update_offer(offer_id_arg, data)
                    return
                except EbayApiError as ue:
                    last_exc = ue
                    err_s = str(ue).lower()
                    is_transient = (
                        "500" in str(ue)
                        or "internal" in err_s
                        or "product not found" in err_s
                        or "system error" in err_s
                    )
                    if not is_transient:
                        raise  # 404/400 등은 즉시 raise
                    if attempt < 2:
                        wait = 2 * (attempt + 1)
                        logger.warning(
                            "[eBay] Offer 수정 일시오류 %s — %d초 후 재시도 (%d/3)",
                            str(ue)[:60],
                            wait,
                            attempt + 1,
                        )
                        await asyncio.sleep(wait)
                    else:
                        raise
            if last_exc:
                raise last_exc

        # ─── 최적화 3: Inventory Item PUT + Offer PUT 병렬 실행 ───
        # Inventory Item은 hash 캐시 확인 → 동일하면 스킵
        async def _inventory_task() -> None:
            if skip_inventory:
                logger.info("[eBay] Inventory Item %s 변경 없음 — skip (캐시 hit)", sku)
                return
            logger.info("[eBay] Inventory Item 수정: SKU=%s", sku)
            await self.create_inventory_item(sku, inventory_item)
            # 성공 시 해시 캐시 업데이트
            if inv_hash:
                _inventory_item_hash_cache[sku] = inv_hash
                _evict_if_needed(_inventory_item_hash_cache)

        async def _offer_task() -> None:
            logger.info("[eBay] Offer 수정: offerId=%s", offer_id)
            await _update_with_retry(offer_id, offer_data)

        try:
            # 병렬 실행: inventory + offer 동시
            await asyncio.gather(_inventory_task(), _offer_task())
        except EbayApiError as e:
            err_str = str(e).lower()
            # 404 / not available 만 "진짜 없음" → 신규 등록 폴백 허용
            if "404" in str(e) or "not available" in err_str:
                logger.info("[eBay] Offer 진짜 없음 (404) — 신규 등록 폴백")
                # 캐시 무효화 (오래된 offer_id로 실패했을 수 있음)
                _offer_id_cache.pop(sku, None)
                _inventory_item_hash_cache.pop(sku, None)
                try:
                    offer_id = await _safe_create_offer(sku, offer_data)
                    logger.info("[eBay] 신규 Offer 게시: offerId=%s", offer_id)
                    listing_id = await self.publish_offer(offer_id)
                    _offer_id_cache[sku] = offer_id
                    return {"listingId": listing_id, "offerId": offer_id, "sku": sku}
                except Exception as fe:
                    logger.error("[eBay] 폴백 신규 등록 실패: %s", fe)
                    raise
            # 500/internal 재시도 소진, 400 validation 등 → 캐시 무효화 + raise (과금 방지)
            _offer_id_cache.pop(sku, None)
            _inventory_item_hash_cache.pop(sku, None)
            raise

        # Offer update는 이미 라이브 리스팅에 자동 반영됨 (publish 재호출 불필요 — Insertion Fee 방지)
        return {"sku": sku, "offerId": offer_id}

    # -------------------------------------------------------------------------
    # 주문/반품/취소/CS 조회 (Fulfillment + Post-Order + Trading API)
    # -------------------------------------------------------------------------

    @staticmethod
    def _utc_iso(dt) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    async def get_orders(self, days: int = 7, limit: int = 200) -> list[dict]:
        """GET /sell/fulfillment/v1/order — 최근 days일 주문 전체 페이징 수집.

        filter=creationdate:[from..to] 는 URL 인코딩 필수.
        """
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        since = now - timedelta(days=days)
        filt = f"creationdate:[{self._utc_iso(since)}..{self._utc_iso(now)}]"
        params_filter = quote(filt, safe="")

        orders: list[dict] = []
        offset = 0
        while True:
            path = (
                f"/sell/fulfillment/v1/order"
                f"?filter={params_filter}&limit={limit}&offset={offset}"
            )
            resp = await self._call("GET", path)
            batch = resp.get("orders", []) or []
            orders.extend(batch)
            total = int(resp.get("total", 0) or 0)
            offset += limit
            if offset >= total or not batch:
                break
        logger.info("[eBay] 주문 조회 완료: %d건 (최근 %d일)", len(orders), days)
        return orders

    async def _post_order_call(self, path: str) -> dict[str, Any]:
        """Post-Order API 전용 호출 — Authorization 스킴이 "IAF"여야 함 (Bearer 불가).

        Post-Order API는 구 스타일 IAF(Individual Auth & Fraud) 헤더 규격을 유지한다.
        """
        token = await self._get_access_token()
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"IAF {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.MARKETPLACE_ID,
        }
        async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 204 or not resp.content:
            return {}
        if resp.status_code >= 400:
            try:
                err_body = resp.json()
                errors = err_body.get("errors") or err_body.get("errorMessage") or []
                if isinstance(errors, dict):
                    errors = errors.get("error", [])
                msg = (
                    errors[0].get("message", resp.text)
                    if errors and isinstance(errors[0], dict)
                    else resp.text
                )
            except Exception:
                msg = resp.text[:500]
                errors = []
            logger.error(
                "[eBay] Post-Order 에러 %s → %d: %s", path, resp.status_code, msg
            )
            raise EbayApiError(
                f"eBay Post-Order 오류 ({resp.status_code}): {msg}",
                errors if isinstance(errors, list) else [],
            )
        return resp.json()

    async def _post_order_search(
        self, resource: str, days: int, result_key: str, limit: int = 200
    ) -> list[dict]:
        """Post-Order search 공통 페이징 (return/cancellation/inquiry)."""
        from datetime import UTC, datetime, timedelta

        since = self._utc_iso(datetime.now(UTC) - timedelta(days=days))
        until = self._utc_iso(datetime.now(UTC))
        items: list[dict] = []
        offset = 0
        while True:
            path = (
                f"/post-order/v2/{resource}/search"
                f"?creation_date_range_from={since}"
                f"&creation_date_range_to={until}"
                f"&role=SELLER&limit={limit}&offset={offset}"
            )
            try:
                resp = await self._post_order_call(path)
            except EbayApiError as e:
                # role=SELLER 지원 안 되는 리소스가 있거나, 권한 부족 시
                logger.warning("[eBay] Post-Order %s 조회 실패: %s", resource, e)
                raise
            batch = resp.get(result_key, []) or resp.get("members", []) or []
            items.extend(batch)
            # paginationOutput 또는 total 필드
            pag = resp.get("paginationOutput") or {}
            total = int(resp.get("total", pag.get("totalEntries", 0)) or 0)
            offset += limit
            if offset >= total or not batch:
                break
        return items

    async def get_returns(self, days: int = 90, limit: int = 200) -> list[dict]:
        """GET /post-order/v2/return/search — 반품 목록."""
        items = await self._post_order_search("return", days, "members", limit)
        logger.info("[eBay] 반품 조회 완료: %d건 (최근 %d일)", len(items), days)
        return items

    async def get_cancellations(self, days: int = 90, limit: int = 200) -> list[dict]:
        """GET /post-order/v2/cancellation/search — 취소 목록."""
        items = await self._post_order_search(
            "cancellation", days, "cancellations", limit
        )
        logger.info("[eBay] 취소 조회 완료: %d건 (최근 %d일)", len(items), days)
        return items

    async def get_inquiries(self, days: int = 90, limit: int = 200) -> list[dict]:
        """GET /post-order/v2/inquiry/search — INR(Item Not Received) 분쟁 문의."""
        items = await self._post_order_search("inquiry", days, "inquiries", limit)
        logger.info("[eBay] 문의 조회 완료: %d건 (최근 %d일)", len(items), days)
        return items

    async def get_transactions(
        self, days: int = 7, limit: int = 200, transaction_type: str = "SALE"
    ) -> list[dict]:
        """GET apiz.ebay.com/sell/finances/v1/transaction — 실제 정산 내역 조회.

        각 SALE 거래는 orderId, amount(총액 USD), totalFeeAmount(실제 수수료 USD) 포함.
        net 정산액 = amount - totalFeeAmount.

        Finance API는 별도 호스트(apiz.ebay.com)를 사용하므로 전용 HTTP 호출.
        상품 등록 직후 주문은 아직 거래가 확정되지 않아 반환 안 될 수 있음 → 호출부에서 폴백.
        """
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        since = now - timedelta(days=days)
        # Finance API 필터 형식: transactionDate:[from..to],transactionType:{SALE}
        filt = (
            f"transactionDate:[{self._utc_iso(since)}..{self._utc_iso(now)}],"
            f"transactionType:{{{transaction_type}}}"
        )
        params_filter = quote(filt, safe="")

        finance_base = self.FINANCE_SANDBOX_URL if self.sandbox else self.FINANCE_URL
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.MARKETPLACE_ID,
        }

        transactions: list[dict] = []
        offset = 0
        while True:
            url = (
                f"{finance_base}/sell/finances/v1/transaction"
                f"?filter={params_filter}&limit={limit}&offset={offset}"
            )
            async with httpx.AsyncClient(
                timeout=settings.http_timeout_default
            ) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                try:
                    err_body = resp.json()
                    errors = err_body.get("errors", [])
                    msg = errors[0].get("message", resp.text) if errors else resp.text
                except Exception:
                    msg = resp.text[:500]
                    errors = []
                logger.error(
                    "[eBay] Finance API 오류 %d: %s | errors=%s",
                    resp.status_code,
                    msg[:200],
                    errors,
                )
                raise EbayApiError(
                    f"eBay Finance API 오류 ({resp.status_code}): {msg}", errors
                )
            data = resp.json() if resp.content else {}
            batch = data.get("transactions", []) or []
            transactions.extend(batch)
            total = int(data.get("total", 0) or 0)
            offset += limit
            if offset >= total or not batch:
                break
        logger.info(
            "[eBay] Finance 거래 조회 완료: %d건 (최근 %d일, type=%s)",
            len(transactions),
            days,
            transaction_type,
        )
        return transactions

    # -------------------------------------------------------------------------
    # 쓰기 액션 (취소/송장/반품/환불/메시지)
    # -------------------------------------------------------------------------

    async def seller_cancel_order(
        self,
        legacy_order_id: str,
        reason: str = "OUT_OF_STOCK_OR_CANNOT_FULFILL",
    ) -> dict:
        """Post-Order Cancellation API — 판매자 주문 취소."""
        token = await self._get_access_token()
        url = f"{self._base_url}/post-order/v2/cancellation"
        headers = {
            "Authorization": f"IAF {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.MARKETPLACE_ID,
        }
        body = {"legacyOrderId": legacy_order_id, "cancelReason": reason}
        async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise EbayApiError(
                f"eBay 주문취소 실패 ({resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json() if resp.content else {}
        logger.info(
            "[eBay] 주문취소 요청 완료: orderId=%s reason=%s cancelId=%s",
            legacy_order_id,
            reason,
            data.get("cancelId", ""),
        )
        return data

    async def ship_order(
        self,
        order_id: str,
        tracking_number: str,
        carrier_code: str = "USPS",
        line_items: list[dict] | None = None,
    ) -> dict:
        """Fulfillment API — 송장 전송."""
        from datetime import UTC, datetime

        if not line_items:
            order_info = await self._call(
                "GET", f"/sell/fulfillment/v1/order/{order_id}"
            )
            line_items = [
                {
                    "lineItemId": li.get("lineItemId"),
                    "quantity": int(li.get("quantity", 1) or 1),
                }
                for li in (order_info.get("lineItems") or [])
                if li.get("lineItemId")
            ]
        if not line_items:
            raise EbayApiError("송장 전송 실패: lineItem이 없습니다")

        body = {
            "lineItems": line_items,
            "shippedDate": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "shippingCarrierCode": carrier_code,
            "trackingNumber": tracking_number,
        }
        await self._call(
            "POST",
            f"/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment",
            body=body,
        )
        logger.info(
            "[eBay] 송장 전송: order=%s carrier=%s tracking=%s",
            order_id,
            carrier_code,
            tracking_number,
        )
        return {"success": True}

    async def _return_decide(
        self, return_id: str, decision: str, reason: str = ""
    ) -> dict:
        """Post-Order Return decide — APPROVE / DENY."""
        token = await self._get_access_token()
        url = f"{self._base_url}/post-order/v2/return/{return_id}/decide"
        headers = {
            "Authorization": f"IAF {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body: dict = {"decision": decision}
        if reason:
            body["comments"] = {"content": reason}
        async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise EbayApiError(
                f"eBay 반품 결정 실패 ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json() if resp.content else {}

    async def approve_return(self, return_id: str) -> dict:
        """반품 승인."""
        result = await self._return_decide(return_id, "APPROVE")
        logger.info("[eBay] 반품 승인: returnId=%s", return_id)
        return result

    async def reject_return(
        self, return_id: str, reason: str = "Seller decline"
    ) -> dict:
        """반품 거부."""
        result = await self._return_decide(return_id, "DENY", reason)
        logger.info("[eBay] 반품 거부: returnId=%s reason=%s", return_id, reason)
        return result

    async def issue_refund(
        self, return_id: str, amount: float, currency: str = "USD"
    ) -> dict:
        """Post-Order Return issue_refund — 환불 처리."""
        token = await self._get_access_token()
        url = f"{self._base_url}/post-order/v2/return/{return_id}/issue_refund"
        headers = {
            "Authorization": f"IAF {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {
            "refundAmount": {"value": f"{amount:.2f}", "currency": currency},
        }
        async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise EbayApiError(
                f"eBay 환불 실패 ({resp.status_code}): {resp.text[:300]}"
            )
        logger.info(
            "[eBay] 환불 완료: returnId=%s amount=%s %s",
            return_id,
            amount,
            currency,
        )
        return resp.json() if resp.content else {}

    async def reply_message(
        self,
        parent_message_id: str,
        text: str,
        recipient: str,
        item_id: str = "",
    ) -> dict:
        """Trading API AddMemberMessageRTQ — CS 메시지 답장."""
        import xml.etree.ElementTree as ET

        access_token = await self._get_access_token()
        item_xml = f"<ItemID>{item_id}</ItemID>" if item_id else ""
        text_escaped = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        xml_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<AddMemberMessageRTQRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"{item_xml}"
            "<MemberMessage>"
            f"<ParentMessageID>{parent_message_id}</ParentMessageID>"
            f"<Body>{text_escaped}</Body>"
            f"<RecipientID>{recipient}</RecipientID>"
            "</MemberMessage>"
            "</AddMemberMessageRTQRequest>"
        )
        headers = {
            "X-EBAY-API-CALL-NAME": "AddMemberMessageRTQ",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
            "X-EBAY-API-IAF-TOKEN": access_token,
            "Content-Type": "text/xml",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/ws/api.dll", content=xml_body, headers=headers
            )
        if resp.status_code != 200:
            raise EbayApiError(
                f"Trading AddMemberMessageRTQ {resp.status_code}: {resp.text[:200]}"
            )
        root = ET.fromstring(resp.text)
        ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.findtext("e:Ack", namespaces=ns) or ""
        if ack not in ("Success", "Warning"):
            err_msg = (
                root.findtext(".//e:Errors/e:LongMessage", namespaces=ns)
                or resp.text[:200]
            )
            raise EbayApiError(f"메시지 답장 실패: {err_msg}")
        logger.info(
            "[eBay] CS 메시지 답장 완료: parent=%s recipient=%s",
            parent_message_id,
            recipient,
        )
        return {"success": True, "ack": ack}

    async def get_my_messages(self, days: int = 90, page_size: int = 25) -> list[dict]:
        """Trading API GetMyMessages — 구매자-판매자 member-to-member 메시지.

        OAuth User Token을 X-EBAY-API-IAF-TOKEN 헤더에 전달하는 XML RPC.
        """
        import xml.etree.ElementTree as ET
        from datetime import UTC, datetime, timedelta

        access_token = await self._get_access_token()
        start = self._utc_iso(datetime.now(UTC) - timedelta(days=days))
        end = self._utc_iso(datetime.now(UTC))

        messages: list[dict] = []
        page = 1
        ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
        trading_headers = {
            "X-EBAY-API-CALL-NAME": "GetMyMessages",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
            "X-EBAY-API-IAF-TOKEN": access_token,
            "Content-Type": "text/xml",
        }
        api_url = f"{self._base_url}/ws/api.dll"

        # Step 1: ReturnHeaders — 메시지 ID 목록 (페이징)
        all_msg_ids: list[str] = []
        while True:
            xml_headers = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                "<DetailLevel>ReturnHeaders</DetailLevel>"
                f"<StartTime>{start}</StartTime>"
                f"<EndTime>{end}</EndTime>"
                f"<Pagination><EntriesPerPage>{page_size}</EntriesPerPage>"
                f"<PageNumber>{page}</PageNumber></Pagination>"
                "</GetMyMessagesRequest>"
            )
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    api_url, content=xml_headers, headers=trading_headers
                )
            if resp.status_code != 200:
                raise EbayApiError(
                    f"Trading GetMyMessages {resp.status_code}: {resp.text[:200]}"
                )
            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError as pe:
                raise EbayApiError(f"GetMyMessages XML 파싱 실패: {pe}") from pe
            ack = root.findtext("e:Ack", namespaces=ns) or ""
            if ack not in ("Success", "Warning"):
                err_msg = (
                    root.findtext(".//e:Errors/e:LongMessage", namespaces=ns)
                    or resp.text[:200]
                )
                raise EbayApiError(f"GetMyMessages 실패: {err_msg}")

            for msg_el in root.findall(".//e:Messages/e:Message", namespaces=ns):
                mid = msg_el.findtext("e:MessageID", namespaces=ns)
                sender = msg_el.findtext("e:Sender", namespaces=ns) or ""
                # eBay 시스템 메시지 제외 — 구매자 메시지만 수집
                sender_lower = sender.lower()
                is_system = (
                    sender_lower == "ebay"
                    or "ebay.com" in sender_lower
                    or sender_lower.startswith("cs")
                )
                if mid and not is_system:
                    all_msg_ids.append(mid)

            total_pages = int(
                root.findtext(
                    ".//e:PaginationResult/e:TotalNumberOfPages",
                    default="1",
                    namespaces=ns,
                )
                or 1
            )
            if page >= total_pages:
                break
            page += 1

        # Step 2: ReturnMessages — 상세 조회 (10개씩 배치)
        import re as _re_msg

        for i in range(0, len(all_msg_ids), 10):
            batch = all_msg_ids[i : i + 10]
            ids_xml = "".join(f"<MessageID>{mid}</MessageID>" for mid in batch)
            xml_detail = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                "<DetailLevel>ReturnMessages</DetailLevel>"
                f"<MessageIDs>{ids_xml}</MessageIDs>"
                "</GetMyMessagesRequest>"
            )
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    api_url, content=xml_detail, headers=trading_headers
                )
            if resp.status_code != 200:
                continue
            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError:
                continue

            for msg_el in root.findall(".//e:Messages/e:Message", namespaces=ns):
                raw_text = msg_el.findtext("e:Text", namespaces=ns) or ""
                # style/script 블록 전체 제거 → HTML 태그 제거 → 공백 정리
                clean_text = _re_msg.sub(
                    r"<style[^>]*>.*?</style>", "", raw_text, flags=_re_msg.DOTALL
                )
                clean_text = _re_msg.sub(
                    r"<script[^>]*>.*?</script>", "", clean_text, flags=_re_msg.DOTALL
                )
                clean_text = _re_msg.sub(r"<[^>]+>", "", clean_text)
                import html as _html_mod

                clean_text = _html_mod.unescape(clean_text)
                clean_text = clean_text.replace("\u200b", "").replace("\xa0", " ")
                clean_text = _re_msg.sub(r"\s+", " ", clean_text).strip()

                # eBay 스레드 → [발신자] 메시지 형식 추출
                sender_name = msg_el.findtext("e:Sender", namespaces=ns) or ""
                # Dear 패턴 + 헤더/푸터 제거
                t = _re_msg.sub(r"Dear \w+,.*?- \w+", "", clean_text)
                t = _re_msg.sub(
                    r"New message:.*?(?=\b"
                    + _re_msg.escape(sender_name)
                    + r"\b|Your previous|$)",
                    "",
                    t,
                )
                t = _re_msg.sub(
                    r"New message from:.*?(?=\b"
                    + _re_msg.escape(sender_name)
                    + r"\b|Your previous|$)",
                    "",
                    t,
                )
                t = _re_msg.sub(
                    r"-->.*?(?=\b"
                    + _re_msg.escape(sender_name)
                    + r"\b|Your previous|$)",
                    "",
                    t,
                )
                t = _re_msg.sub(
                    r"(Millet|Order status|Item ID|Transaction|Order number"
                    r"|We scan messages|Asking your trading).*$",
                    "",
                    t,
                )
                t = _re_msg.sub(r"\s+", " ", t).strip()
                # split by sender / "Your previous message"
                parts = _re_msg.split(
                    r"(" + _re_msg.escape(sender_name) + r"|Your previous message)",
                    t,
                )
                thread_msgs: list[str] = []
                i = 0
                while i < len(parts):
                    p = parts[i].strip()
                    if p == sender_name and i + 1 < len(parts):
                        msg = parts[i + 1].strip()
                        msg = _re_msg.sub(r"^\(\d+\)\s*", "", msg)
                        if msg:
                            thread_msgs.append(f"[{sender_name}] {msg}")
                        i += 2
                    elif p == "Your previous message" and i + 1 < len(parts):
                        msg = parts[i + 1].strip()
                        if msg:
                            thread_msgs.append(f"[seller] {msg}")
                        i += 2
                    else:
                        i += 1
                thread_msgs.reverse()
                if thread_msgs:
                    clean_text = "\n".join(thread_msgs)[:1000]
                else:
                    clean_text = clean_text[:200]
                messages.append(
                    {
                        "messageId": msg_el.findtext("e:MessageID", namespaces=ns),
                        "externalMessageId": msg_el.findtext(
                            "e:ExternalMessageID", namespaces=ns
                        ),
                        "sender": msg_el.findtext("e:Sender", namespaces=ns),
                        "subject": msg_el.findtext("e:Subject", namespaces=ns),
                        "text": clean_text,
                        "receiveDate": msg_el.findtext("e:ReceiveDate", namespaces=ns),
                        "itemId": msg_el.findtext("e:ItemID", namespaces=ns),
                        "messageType": msg_el.findtext("e:MessageType", namespaces=ns),
                        "read": msg_el.findtext("e:Read", namespaces=ns),
                    }
                )

        logger.info("[eBay] CS 메시지 조회 완료: %d건 (최근 %d일)", len(messages), days)
        return messages

    async def test_auth(self) -> bool:
        """인증 테스트 — 배송 정책 1건 조회로 확인."""
        try:
            await self._get_access_token()
            return True
        except EbayApiError as e:
            logger.error("[eBay] 인증 실패: %s", e)
            return False
