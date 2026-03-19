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
    # 메시지: datetime\nmethod\npath\nquery (줄바꿈 구분)
    message = f"{dt}\n{method}\n{path}\n{query}"
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

    async with httpx.AsyncClient(timeout=30) as client:
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

      return data

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
    """SambaCollectedProduct → 쿠팡 상품 등록 데이터 변환."""
    images_raw = product.get("images") or []
    vendor_image_urls = [
      {"imageOrder": i, "imageUrl": url}
      for i, url in enumerate(images_raw[:10])
    ]

    # 옵션 처리
    options = product.get("options") or []
    items = []
    if options:
      for opt in options:
        opt_name = opt.get("name", "") or opt.get("size", "") or "기본"
        opt_stock = opt.get("stock", 999)
        items.append({
          "itemName": opt_name,
          "originalPrice": int(product.get("original_price", 0)),
          "salePrice": int(product.get("sale_price", 0)),
          "maximumBuyCount": 999,
          "maximumBuyForPerson": 0,
          "outboundShippingTimeDay": 3,
          "unitCount": 1,
          "adultOnly": "EVERYONE",
          "taxType": "TAX",
          "vendorInventoryItemList": [
            {"quantity": opt_stock}
          ],
        })
    else:
      items.append({
        "itemName": product.get("name", "기본"),
        "originalPrice": int(product.get("original_price", 0)),
        "salePrice": int(product.get("sale_price", 0)),
        "maximumBuyCount": 999,
        "maximumBuyForPerson": 0,
        "outboundShippingTimeDay": 3,
        "unitCount": 1,
        "adultOnly": "EVERYONE",
        "taxType": "TAX",
        "vendorInventoryItemList": [
          {"quantity": 999}
        ],
      })

    return {
      "displayCategoryCode": category_id or 0,
      "sellerProductName": product.get("name", ""),
      "vendorId": "",  # 런타임에 채움
      "saleStartedAt": "",
      "saleEndedAt": "",
      "displayProductName": product.get("name", ""),
      "brand": product.get("brand", ""),
      "generalProductName": product.get("name", ""),
      "productGroup": "",
      "deliveryMethod": "PARCEL",
      "deliveryCompanyCode": "CJGLS",
      "deliveryChargeType": "FREE",
      "deliveryCharge": 0,
      "freeShipOverAmount": 0,
      "deliveryChargeOnReturn": 5000,
      "remoteAreaDeliverable": "N",
      "unionDeliveryType": "NOT_UNION_DELIVERY",
      "returnCenterCode": return_center_code,
      "returnChargeName": "반품배송비",
      "companyContactNumber": "02-0000-0000",
      "returnChargeVendor": "VENDOR",
      "afterServiceContactNumber": "02-0000-0000",
      "afterServiceGuideContent": "상세페이지 참조",
      "outboundShippingPlaceCode": outbound_shipping_place_code,
      "vendorUserId": "",
      "requested": False,
      "items": items,
      "requiredDocuments": [],
      "extraInfoMessage": "",
      "manufacture": product.get("manufacturer", ""),
      "vendorImageUrls": vendor_image_urls,
      "contentDetails": [
        {
          "content": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
          "detailType": "HTML",
        }
      ],
    }


class CoupangApiError(Exception):
  """쿠팡 API 에러."""
  pass
