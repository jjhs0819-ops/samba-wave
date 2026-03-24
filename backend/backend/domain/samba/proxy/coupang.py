"""쿠팡 Wing API 클라이언트 - 상품 등록/수정.

인증 방식: HMAC-SHA256
- method, url, timestamp, accessKey → HMAC 서명 생성
- Authorization: CEA algorithm=HmacSHA256, access-key={accessKey}, signed-date={datetime}, signature={signature}
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


class CoupangClient:
  """쿠팡 Wing API 클라이언트."""

  BASE_URL = "https://api-gateway.coupang.com"

  def __init__(
    self,
    access_key: str,
    secret_key: str,
    vendor_id: str,
  ) -> None:
    self.access_key = access_key
    self.secret_key = secret_key
    self.vendor_id = vendor_id

  # ------------------------------------------------------------------
  # HMAC 서명 생성
  # ------------------------------------------------------------------

  def _generate_signature(self, method: str, path: str, query: str = "") -> tuple[str, str]:
    """HMAC-SHA256 서명 생성. (authorization_header, datetime) 반환."""
    dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    # 메시지: datetime + method + path + query (단순 연결, 구분자 없음)
    message = f"{dt}{method}{path}{query}"
    signature = hmac.new(
      self.secret_key.encode("utf-8"),
      message.encode("utf-8"),
      hashlib.sha256,
    ).hexdigest()

    authorization = (
      f"CEA algorithm=HmacSHA256, access-key={self.access_key}, "
      f"signed-date={dt}, signature={signature}"
    )
    return authorization, dt

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
  ) -> dict[str, Any]:
    """공통 API 호출."""
    query = "&".join(f"{k}={v}" for k, v in (params or {}).items() if v)
    authorization, dt = self._generate_signature(method, path, query)

    url = f"{self.BASE_URL}{path}"
    if query:
      url = f"{url}?{query}"

    headers = {
      "Authorization": authorization,
      "Content-Type": "application/json;charset=UTF-8",
      "X-Requested-By": "samba-wave",
    }

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      if method == "GET":
        resp = await client.get(url, headers=headers)
      elif method == "POST":
        resp = await client.post(url, headers=headers, json=body or {})
      elif method == "PUT":
        resp = await client.put(url, headers=headers, json=body or {})
      elif method == "DELETE":
        resp = await client.delete(url, headers=headers)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      try:
        data = resp.json()
      except Exception:
        data = {"raw": resp.text}

      logger.info(f"[쿠팡] {method} {path} → {resp.status_code}")

      if not resp.is_success:
        msg = data.get("message", "") or data.get("reason", "") or resp.text[:200]
        raise CoupangApiError(f"HTTP {resp.status_code}: {msg}")

      # 쿠팡 API는 HTTP 200이지만 body에 code=ERROR 반환하는 경우 있음
      if isinstance(data, dict) and data.get("code") == "ERROR":
        msg = data.get("message", "") or "알 수 없는 오류"
        raise CoupangApiError(f"API ERROR: {msg}")

      return data

  # ------------------------------------------------------------------
  # 카테고리 조회
  # ------------------------------------------------------------------

  async def get_categories(self) -> dict[str, Any]:
    """전체 카테고리 조회 (display category 기반)."""
    return await self._call_api(
      "GET",
      "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
    )

  async def resolve_category_code(self, category_path: str) -> int:
    """카테고리 경로 문자열 → displayItemCategoryCode 변환.

    카테고리 트리를 조회하여 경로의 마지막 키워드와 가장 잘 매칭되는 리프 노드 반환.
    """
    try:
      result = await self.get_categories()
      root = result.get("data", result) if isinstance(result, dict) else {}
      if not isinstance(root, dict):
        return 0

      # 트리 평탄화: (경로, 코드) 리스트 생성
      def flatten(node: dict, path: str = "") -> list[tuple[str, int]]:
        code = node.get("displayItemCategoryCode", 0)
        name = node.get("name", "")
        current = f"{path} > {name}" if path else name
        entries: list[tuple[str, int]] = []
        children = node.get("child", [])
        if not children and code:
          entries.append((current, code))
        for c in children:
          entries.extend(flatten(c, current))
        return entries

      all_cats = flatten(root)

      # 경로에서 키워드 추출 (예: "패션의류 > 남성의류 > 아우터 > 코트" → ["패션의류", "남성의류", ...])
      keywords = [k.strip() for k in category_path.replace(">", "/").split("/") if k.strip()]

      # 가중치 매칭: 상위 카테고리(성별 등)에 높은 가중치 부여
      # 예: ["패션의류", "남성의류", "아우터", "코트"] → 가중치 [4, 3, 2, 1]
      full_matches: list[tuple[str, int, int]] = []
      partial_matches: list[tuple[str, int, int]] = []
      for cat_path, code in all_cats:
        score = 0
        match_count = 0
        for i, kw in enumerate(keywords):
          if kw in cat_path:
            score += len(keywords) - i  # 상위 키워드일수록 높은 가중치
            match_count += 1
        if match_count == len(keywords):
          full_matches.append((cat_path, code, score))
        elif match_count > 0:
          partial_matches.append((cat_path, code, score))

      # 전체 매칭 → 가중치 합계 높은 순, 동점이면 경로 짧은 순
      best_code = 0
      if full_matches:
        full_matches.sort(key=lambda x: (-x[2], len(x[0])))
        best_code = full_matches[0][1]
        logger.info(f"[쿠팡] 카테고리 전체매칭: '{category_path}' → {best_code} ({full_matches[0][0]})")
      elif partial_matches:
        partial_matches.sort(key=lambda x: (-x[2], len(x[0])))
        best_code = partial_matches[0][1]
        logger.info(f"[쿠팡] 카테고리 부분매칭: '{category_path}' → {best_code} ({partial_matches[0][0]})")

      if best_code:
        logger.info(f"[쿠팡] 카테고리 매핑: '{category_path}' → {best_code}")
      return best_code
    except Exception as exc:
      logger.warning(f"[쿠팡] 카테고리 코드 조회 실패: {exc}")
      return 0

  async def get_category_by_id(self, category_id: str) -> dict[str, Any]:
    """특정 카테고리 상세 조회."""
    return await self._call_api(
      "GET",
      f"/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{category_id}",
    )

  # ------------------------------------------------------------------
  # 상품 등록/수정
  # ------------------------------------------------------------------

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록.

    Coupang Wing API: POST /v2/providers/seller_api/apis/api/v1/marketplace/seller-products
    """
    result = await self._call_api(
      "POST",
      "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
      body=product_data,
    )
    return {"success": True, "data": result}

  async def update_product(
    self, seller_product_id: str, product_data: dict[str, Any]
  ) -> dict[str, Any]:
    """상품 수정."""
    result = await self._call_api(
      "PUT",
      f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}",
      body=product_data,
    )
    return {"success": True, "data": result}

  async def delete_product(self, seller_product_id: str) -> dict[str, Any]:
    """상품 삭제 (리스트에서 완전 제거)."""
    result = await self._call_api(
      "DELETE",
      f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}",
    )
    return {"success": True, "data": result}

  async def get_product(self, seller_product_id: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api(
      "GET",
      f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}",
    )

  # ------------------------------------------------------------------
  # 상품 데이터 변환
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str = "",
    return_center_code: str = "",
    outbound_shipping_place_code: str = "",
  ) -> dict[str, Any]:
    """SambaCollectedProduct → 쿠팡 상품 등록 데이터 변환.

    쿠팡 Wing API 공식 스펙 기준 전체 필수필드 포함.
    """
    from datetime import datetime as dt, timezone as tz

    images_raw = product.get("images") or []
    color = product.get("color", "") or "상세 이미지 참조"
    detail_html = product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>"

    # 카테고리 코드 (숫자만 허용)
    display_category = int(category_id) if category_id and str(category_id).isdigit() else 0

    # 판매기간
    now = dt.now(tz.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # 고시정보 — 카테고리별 동적 생성
    from backend.domain.samba.proxy.notice_utils import build_coupang_notices
    notices = build_coupang_notices(product)

    # 아이템별 공통 필드 생성 함수
    def _build_item(item_name: str, stock: int, size_val: str) -> dict[str, Any]:
      # 아이템별 이미지 (대표 + 상세)
      item_images: list[dict[str, Any]] = []
      if images_raw:
        item_images.append({
          "imageOrder": 0,
          "imageType": "REPRESENTATION",
          "vendorPath": images_raw[0],
        })
        for idx, url in enumerate(images_raw[1:10], start=1):
          item_images.append({
            "imageOrder": idx,
            "imageType": "DETAIL",
            "vendorPath": url,
          })

      return {
        "itemName": item_name,
        "originalPrice": int(product.get("original_price", 0)),
        "salePrice": int(product.get("sale_price", 0)),
        "maximumBuyCount": min(stock, 99999),
        "maximumBuyForPerson": 0,
        "maximumBuyForPersonPeriod": 1,
        "outboundShippingTimeDay": 3,
        "unitCount": 1,
        "adultOnly": "EVERYONE",
        "taxType": "TAX",
        "parallelImported": "NOT_PARALLEL_IMPORTED",
        "overseasPurchased": "NOT_OVERSEAS_PURCHASED",
        "pccNeeded": False,
        "barcode": "",
        "emptyBarcode": True,
        "emptyBarcodeReason": "바코드 없음",
        "offerCondition": "NEW",
        "attributes": [
          {"attributeTypeName": "패션의류/잡화 사이즈", "attributeValueName": size_val},
          {"attributeTypeName": "색상", "attributeValueName": color},
        ],
        "contents": [
          {
            "contentsType": "HTML",
            "contentDetails": [
              {"content": detail_html, "detailType": "TEXT"}
            ],
          }
        ],
        "notices": notices,
        "images": item_images,
        "certifications": [
          {"certificationType": "NOT_REQUIRED", "certificationCode": ""}
        ],
      }

    # 옵션 처리
    options = product.get("options") or []
    items = []
    if options:
      for opt in options:
        opt_name = opt.get("name", "") or opt.get("size", "") or "기본"
        opt_stock = opt.get("stock", 999)
        size_val = opt_name.split("/")[-1] if "/" in opt_name else opt_name
        items.append(_build_item(opt_name, opt_stock, size_val))
    else:
      items.append(_build_item(product.get("name", "기본"), 999, "FREE"))

    return {
      "displayCategoryCode": display_category,
      "sellerProductName": product.get("name", "")[:100],
      "vendorId": "",  # 런타임에 디스패처에서 채움
      "saleStartedAt": now,
      "saleEndedAt": "2099-01-01T23:59:59",
      "displayProductName": product.get("name", "")[:100],
      "brand": product.get("brand", ""),
      "generalProductName": product.get("name", "")[:100],
      "productGroup": "",
      "deliveryMethod": "SEQUENCIAL",
      "deliveryCompanyCode": "CJGLS",
      "deliveryChargeType": "FREE",
      "deliveryCharge": 0,
      "freeShipOverAmount": 0,
      "deliveryChargeOnReturn": 2500,
      "remoteAreaDeliverable": "N",
      "unionDeliveryType": "NOT_UNION_DELIVERY",
      "returnCenterCode": return_center_code or "NO_RETURN_CENTERCODE",
      "returnChargeName": "반품지",
      "companyContactNumber": product.get("_as_phone", "") or "상세페이지 참조",
      "returnZipCode": "00000",
      "returnAddress": "상세페이지 참조",
      "returnAddressDetail": "상세페이지 참조",
      "returnCharge": 2500,
      "outboundShippingPlaceCode": int(outbound_shipping_place_code) if outbound_shipping_place_code else 0,
      "vendorUserId": "",  # 런타임에 디스패처에서 채움
      "requested": True,
      "items": items,
      "requiredDocuments": [],
      "extraInfoMessage": "",
      "manufacture": product.get("manufacturer", "") or product.get("brand", ""),
    }


class CoupangApiError(Exception):
  """쿠팡 API 에러."""
  pass
