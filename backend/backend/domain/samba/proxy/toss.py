"""토스쇼핑 Open API 클라이언트.

인증: OAuth2 client_credentials → Bearer 토큰
  POST https://oauth2.cert.toss.im/token (form, snake_case client_id/client_secret)
  → Authorization: Bearer {access_token}

★함정★ 토스는 실패 응답도 HTTP 200 으로 내려준다. 성공/실패는 봉투의
resultType 으로 판정해야 한다. status_code 만 보면 실패가 조용히 성공으로 보인다.

  성공: {"resultType":"SUCCESS","success":{...},"error":null}
  실패: {"resultType":"FAIL","success":null,"error":{"errorCode":..,"reason":..}}
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from backend.domain.samba.proxy.base_client import BaseProxyClient

# access_key → (토큰, 만료 epoch). 토큰 수명은 실측 3599초.
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_MARGIN = 60.0  # 만료 직전 재발급 여유


# 고시 항목 title 키워드 → 상품 필드 매핑. 토스는 항목 id 를 카테고리코드별로
# 동적으로 내려주므로, id 가 아니라 title 키워드로 붙인다.
_NOTICE_FIELD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("주소재", "소재", "재질"), "material"),
    (("색상",), "color"),
    (("제조국", "원산지"), "origin"),
    (("제조자", "수입자", "제조사"), "manufacturer"),
    (("치수", "크기", "사이즈"), "size_notice"),
    (("취급시", "취급 시", "세탁"), "care_instructions"),
]
_NOTICE_DEFAULT = "상세페이지 참조"
_NOTICE_WARRANTY = "관련 법령 및 소비자분쟁해결기준에 따름"
_NOTICE_MAX_LEN = 4000


# 고시 카테고리코드 → 항목목록 캐시(항목 구성은 자주 바뀌지 않는다)
_NOTICE_ITEM_CACHE: dict[str, list[dict[str, Any]]] = {}


def clear_notice_cache() -> None:
    """고시 항목 캐시 비우기(테스트/강제 갱신용)."""
    _NOTICE_ITEM_CACHE.clear()


async def fetch_notice_items(client, category_code: str) -> list[dict[str, Any]]:
    """고시 항목 조회 — 카테고리코드별 1회만 호출한다."""
    cached = _NOTICE_ITEM_CACHE.get(category_code)
    if cached is not None:
        return cached
    data = await client.list_notice_items(category_code)
    items = list(data.get("items") or [])
    _NOTICE_ITEM_CACHE[category_code] = items
    return items


def build_notice_items(
    notice_items: list[dict[str, Any]],
    product: dict[str, Any],
    account_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """토스 고시 항목(id/title) + 상품 → 등록용 notice.items.

    항목 content 가 비면 등록이 거부되므로 값이 없는 항목은
    "상세페이지 참조" 로 채운다.
    """
    s = account_settings or {}
    built: list[dict[str, Any]] = []
    for item in notice_items or []:
        title = str(item.get("title") or "")
        content = ""

        if "A/S" in title or "AS 책임자" in title or "전화번호" in title:
            content = str(s.get("asPhone") or "")
        elif "품질보증" in title:
            content = _NOTICE_WARRANTY
        else:
            for keywords, field in _NOTICE_FIELD_RULES:
                if any(k in title for k in keywords):
                    content = str(product.get(field) or "")
                    break

        content = (content or "").strip() or _NOTICE_DEFAULT
        built.append({"id": item.get("id"), "content": content[:_NOTICE_MAX_LEN]})
    return built


class TossApiError(Exception):
    """토스 API 에러."""

    pass


class TossClient(BaseProxyClient):
    """토스쇼핑 Open API 클라이언트."""

    base_url = "https://shopping-fep.toss.im"
    token_url = "https://oauth2.cert.toss.im/token"
    scope = "toss-shopping-fep:write"
    api_prefix = "/api/v3/shopping-fep"
    timeout = 30.0
    market_name = "토스"

    def __init__(self, access_key: str, secret_key: str) -> None:
        super().__init__()
        self.access_key = access_key
        self.secret_key = secret_key

    # ------------------------------------------------------------------
    # 인증
    # ------------------------------------------------------------------

    @classmethod
    def clear_token_cache(cls) -> None:
        """토큰 캐시 비우기(테스트/강제 재발급용)."""
        _TOKEN_CACHE.clear()

    async def _get_token(self) -> str:
        """Bearer 토큰 — 만료 전까지 재사용한다."""
        cached = _TOKEN_CACHE.get(self.access_key)
        if cached and cached[1] > time.time():
            return cached[0]

        resp = await self._get_client().post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                # 문서는 clientId/clientSecret 이라고 적혀 있으나 실제 서버는
                # RFC6749 표준 snake_case 만 받는다(camelCase → invalid_client).
                "client_id": self.access_key,
                "client_secret": self.secret_key,
                "scope": self.scope,
            },
        )
        try:
            data = resp.json()
        except Exception:
            data = {}

        token = data.get("access_token")
        if not token:
            raise TossApiError(
                f"토큰 발급 실패 (HTTP {resp.status_code}): {str(data)[:300]}"
            )

        expires_in = float(data.get("expires_in") or 3600)
        _TOKEN_CACHE[self.access_key] = (
            token,
            time.time() + max(expires_in - _TOKEN_MARGIN, 60.0),
        )
        return token

    async def _build_headers(self, method: str, path: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._get_token()}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # 응답 처리
    # ------------------------------------------------------------------

    async def _parse_response(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 204:
            return {}
        return await super()._parse_response(resp)

    async def _check_error(self, resp: httpx.Response, data: dict[str, Any]) -> None:
        """resultType 우선 판정 — HTTP 200 이어도 FAIL 이면 에러다."""
        if data.get("resultType") == "FAIL" or resp.status_code >= 400:
            err = data.get("error") or {}
            code = err.get("errorCode") or f"HTTP {resp.status_code}"
            reason = err.get("reason") or str(data.get("_raw") or data)[:300]
            raise TossApiError(f"[{code}] {reason}")

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """API 호출 후 success 봉투를 벗겨 반환."""
        data = await self._call_api(method, path, body=body, params=params)
        success = data.get("success")
        return success if isinstance(success, dict) else {}

    # ------------------------------------------------------------------
    # 상품 변환
    # ------------------------------------------------------------------

    @staticmethod
    def transform_product(
        product: dict[str, Any],
        category_id: str,
        account_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """수집상품 → 토스쇼핑 등록 페이로드.

        필수 구조를 여기서 고정한다 — 누락되면 토스는 HTTP 200 + FAIL 로
        조용히 거부한다.
        """
        s = account_settings or {}
        name = str(product.get("name") or "")[:100]
        sale_price = int(
            product.get("_final_sale_price") or product.get("sale_price") or 0
        )
        origin_price = int(product.get("origin_price") or 0) or sale_price
        stock_cap = int(s.get("stockQuantity") or 0) or 999

        # ── 옵션(stocks) — 최소 1개는 isMainPrice ──────────────
        stocks: list[dict[str, Any]] = []
        for idx, opt in enumerate(product.get("options") or []):
            raw_name = str(opt.get("name") or opt.get("size") or f"옵션{idx + 1}")
            if ":" in raw_name:
                group_name, value_name = (x.strip() for x in raw_name.split(":", 1))
            else:
                group_name, value_name = "사이즈", raw_name
            sold_out = bool(opt.get("isSoldOut"))
            raw_stock = opt.get("stock")
            stock = stock_cap if raw_stock in (None, "") else int(raw_stock)
            stocks.append(
                {
                    "options": [{"groupName": group_name, "valueName": value_name}],
                    "remainingCount": 0 if sold_out else min(stock, stock_cap),
                    "isHide": False,
                    "isMainPrice": idx == 0,
                    "isSoldOut": sold_out,
                    "originPrice": origin_price,
                    "salePrice": sale_price,
                }
            )
        if not stocks:
            stocks = [
                {
                    "remainingCount": stock_cap,
                    "isHide": False,
                    "isMainPrice": True,
                    "isSoldOut": False,
                    "originPrice": origin_price,
                    "salePrice": sale_price,
                }
            ]

        # ── 이미지 — 대표 1장 + 추가컷 + 상세HTML ──────────────
        images: list[dict[str, Any]] = []
        order = 0
        for raw in product.get("images") or []:
            url = raw if isinstance(raw, str) else (raw.get("url") or raw.get("src"))
            if not url:
                continue
            images.append(
                {
                    "type": "THUMBNAIL" if order == 0 else "DESCRIPTION",
                    "url": url,
                    "order": order,
                }
            )
            order += 1
        detail_html = product.get("detail_html") or f"<p>{name}</p>"
        # ★DESCRIPTION_HTML 은 url 이 아니라 html 필드로 보낸다★
        images.append({"type": "DESCRIPTION_HTML", "html": detail_html, "order": order})

        # ── 검색 키워드 — 키워드당 1~10글자만 허용 ──────────────
        keywords = [
            str(k).strip()
            for k in (product.get("seo_keywords") or [])
            if 1 <= len(str(k).strip()) <= 10
        ][:10]
        if not keywords and name:
            keywords = [str(product.get("brand") or name.split(" ")[0])[:10]]

        # ── 배송 정책 ──────────────
        delivery_fee = int(s.get("deliveryFee") or 0)
        free_over = int(s.get("freeConditionAmount") or 0)
        if delivery_fee <= 0:
            fee_type = "FREE"
        elif free_over > 0:
            fee_type = "CONDITIONALLY_FREE"
        else:
            fee_type = "PAID"
        jeju_fee = int(s.get("jejuFee") or 0)

        return {
            "name": name,
            "brandName": str(product.get("brand") or ""),
            "categoryId": str(category_id),
            "stocks": stocks,
            "images": images,
            "exposure": {
                "searchKeywords": keywords,
                "description": str(s.get("asMessage") or name)[:500],
            },
            "isTaxFree": False,
            "deliveryPolicy": {
                "deliveryMethod": "NORMAL",
                "deliveryLocationId": int(s.get("deliveryLocationId") or 0),
                "deliveryFeeType": fee_type,
                "deliveryFee": delivery_fee,
                "minimumPurchasePrice": free_over,
                "isJejuAndIslandsMountainsDelivery": jeju_fee > 0,
                "jejuDeliveryFee": jeju_fee,
                "islandsMountainsDeliveryFee": jeju_fee,
            },
            "exchangeReturnPolicy": {
                "exchangeRefundLocationId": int(s.get("exchangeRefundLocationId") or 0),
                "refundOneWayDeliveryFee": int(s.get("returnFee") or 0),
                "exchangeRoundTripDeliveryFee": int(s.get("exchangeFee") or 0),
                "applicationMethodDescription": str(
                    s.get("returnMethodText") or "고객센터 문의 후 교환/반품 신청"
                )[:500],
                "applicationTermDescription": str(
                    s.get("returnTermText") or "상품 수령 후 7일 이내"
                )[:500],
            },
            "notice": {
                "categoryCode": str(s.get("noticeCategoryCode") or "CLOTHING"),
                "items": list(s.get("noticeItems") or []),
            },
        }

    # ------------------------------------------------------------------
    # 상품 CRUD
    # ------------------------------------------------------------------

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        """상품 신규 등록 → {"id": productId}."""
        return await self._request(
            "POST", f"{self.api_prefix}/products/v2", body=payload
        )

    async def update_product(
        self, product_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """상품 정보 변경(이미지 변경 시 검수 재진입)."""
        return await self._request(
            "PUT", f"{self.api_prefix}/products/{product_id}/v2", body=payload
        )

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """상품 조회."""
        return await self._request("GET", f"{self.api_prefix}/products/{product_id}/v2")

    async def hide_product(self, product_id: str) -> dict[str, Any]:
        """상품 숨기기(노출 중지)."""
        return await self._request(
            "POST",
            f"{self.api_prefix}/products/hide",
            body={"productId": int(product_id)},
        )

    async def delete_product(self, product_id: str) -> dict[str, Any]:
        """상품 삭제 — 노출중인 상품은 삭제 불가라 숨기기를 먼저 태운다."""
        await self.hide_product(product_id)
        return await self._request(
            "POST",
            f"{self.api_prefix}/products/remove",
            body={"productId": int(product_id)},
        )

    # ------------------------------------------------------------------
    # 오토튠(가격/재고)
    # ------------------------------------------------------------------

    async def update_sale_price(
        self, product_id: str, item_id: str, sale_price: int
    ) -> dict[str, Any]:
        """판매가 수정 — 정상가 이하만 허용된다."""
        return await self._request(
            "PUT",
            f"{self.api_prefix}/product-items/{item_id}/sale-price",
            body={"productId": int(product_id), "salePrice": int(sale_price)},
        )

    async def update_stock(
        self, product_id: str, item_id: str, remaining_count: int
    ) -> dict[str, Any]:
        """재고 수량 변경 — 0 이면 품절, 1 이상이면 품절 해제까지 자동 처리된다."""
        return await self._request(
            "PUT",
            f"{self.api_prefix}/product-items/{item_id}/stocks/normal-stock"
            "/remaining-count",
            body={"productId": int(product_id), "remainingCount": int(remaining_count)},
        )

    async def list_product_items(self, product_id: str) -> dict[str, Any]:
        """상품의 옵션(아이템) 목록 — 가격/재고 수정에 필요한 itemId 획득용."""
        return await self._request(
            "GET", f"{self.api_prefix}/products/{product_id}/product-items"
        )

    # ------------------------------------------------------------------
    # 등록 선행 조회 (카테고리 / 고시 / 출고지)
    # ------------------------------------------------------------------

    async def list_categories(self, category_id: str | None = None) -> dict[str, Any]:
        """카테고리 하위 목록 — id 미지정 시 1차 카테고리."""
        params = {"id": str(category_id)} if category_id else None
        return await self._request(
            "GET", f"{self.api_prefix}/products/categories/children", params=params
        )

    async def list_notice_category_codes(self) -> dict[str, Any]:
        """정보제공 고시 카테고리 코드 목록."""
        return await self._request("GET", f"{self.api_prefix}/notices/category-codes")

    async def list_notice_items(self, category_code: str) -> dict[str, Any]:
        """고시 카테고리의 항목(id/title) 목록."""
        return await self._request(
            "GET", f"{self.api_prefix}/notices", params={"categoryCode": category_code}
        )

    async def list_delivery_locations(self) -> dict[str, Any]:
        """출고지(배송묶음그룹) 목록 — deliveryLocationId 획득용."""
        return await self._request(
            "GET", f"{self.api_prefix}/merchants/group-delivery/delivery-location/v2"
        )

    async def list_exchange_refund_locations(self) -> dict[str, Any]:
        """교환/반품지 목록 — exchangeRefundLocationId 획득용."""
        return await self._request(
            "GET",
            f"{self.api_prefix}/merchants/group-delivery/exchange-refund-location/v2",
        )
