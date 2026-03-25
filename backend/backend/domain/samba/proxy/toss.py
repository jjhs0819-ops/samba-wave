"""토스 커머스 API 클라이언트 - 상품 등록/수정.

인증 방식: HMAC-SHA256
- timestamp + method + path → SecretKey로 HMAC-SHA256 서명
- Authorization: TOSS-HMAC-SHA256 AccessKey={accessKey}, Signature={signature}, Timestamp={timestamp}
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Optional

import httpx

from backend.utils.logger import logger


class TossClient:
  """토스 커머스 API 클라이언트."""

  BASE_URL = "https://api-shopping.toss.im"

  def __init__(self, access_key: str, secret_key: str) -> None:
    self.access_key = access_key
    self.secret_key = secret_key

  # ------------------------------------------------------------------
  # 인증
  # ------------------------------------------------------------------

  def _generate_signature(self, method: str, path: str, timestamp: str) -> str:
    """HMAC-SHA256 서명 생성."""
    message = f"{timestamp}\n{method.upper()}\n{path}"
    signature = hmac.new(
      self.secret_key.encode("utf-8"),
      message.encode("utf-8"),
      hashlib.sha256,
    ).hexdigest()
    return signature

  def _headers(self, method: str, path: str) -> dict[str, str]:
    """인증 헤더 생성."""
    timestamp = str(int(time.time() * 1000))
    signature = self._generate_signature(method, path, timestamp)
    return {
      "Authorization": (
        f"TOSS-HMAC-SHA256 "
        f"AccessKey={self.access_key}, "
        f"Signature={signature}, "
        f"Timestamp={timestamp}"
      ),
      "Content-Type": "application/json",
    }

  # ------------------------------------------------------------------
  # 공통 API 호출
  # ------------------------------------------------------------------

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
  ) -> dict[str, Any]:
    """공통 API 호출."""
    url = f"{self.BASE_URL}{path}"
    headers = self._headers(method, path)

    async with httpx.AsyncClient(timeout=30) as client:
      if method.upper() == "GET":
        resp = await client.get(url, headers=headers, params=params)
      elif method.upper() == "POST":
        resp = await client.post(url, headers=headers, json=body or {})
      elif method.upper() == "PUT":
        resp = await client.put(url, headers=headers, json=body or {})
      elif method.upper() == "PATCH":
        resp = await client.patch(url, headers=headers, json=body or {})
      elif method.upper() == "DELETE":
        resp = await client.delete(url, headers=headers)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      logger.info(f"[토스] {method.upper()} {path} → {resp.status_code}")

      if resp.status_code >= 400:
        text = resp.text[:500]
        raise TossApiError(f"HTTP {resp.status_code}: {text}")

      if resp.status_code == 204:
        return {}
      return resp.json()

  # ------------------------------------------------------------------
  # 상품 변환
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str,
    account_settings: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    """CollectedProduct → 토스 API 상품 등록 페이로드 변환."""
    settings = account_settings or {}
    name = product.get("name") or ""
    sale_price = int(product.get("_final_sale_price") or product.get("sale_price") or 0)
    images = product.get("images") or []
    detail_html = product.get("detail_html") or f"<p>{name}</p>"
    brand = product.get("brand") or ""

    # 이미지 구조
    image_list = []
    for i, url in enumerate(images[:10]):
      image_list.append({
        "url": url,
        "representative": i == 0,
      })

    # 배송 정보
    delivery_fee = int(settings.get("deliveryFee", 0))
    free_condition = int(settings.get("freeConditionAmount", 50000))

    payload: dict[str, Any] = {
      "productName": name[:100],
      "salePrice": sale_price,
      "categoryId": category_id,
      "brandName": brand,
      "images": image_list,
      "stockQuantity": int(product.get("_max_stock") or 999),
      "deliveryInfo": {
        "deliveryMethod": "DELIVERY",
        "deliveryFee": delivery_fee,
        "freeConditionAmount": free_condition,
      },
      "productDescription": detail_html,
      "saleStatus": "ON_SALE",
    }

    # 옵션
    options = product.get("options") or []
    if len(options) >= 2:
      option_list = []
      for opt in options:
        opt_name = opt.get("name") or opt.get("size") or ""
        is_sold_out = opt.get("isSoldOut", False)
        stock = 0 if is_sold_out else int(opt.get("stock") or product.get("_max_stock") or 999)
        option_list.append({
          "optionName": opt_name,
          "stockQuantity": stock,
          "price": sale_price,
        })
      if option_list:
        payload["options"] = option_list

    return payload

  # ------------------------------------------------------------------
  # 상품 CRUD
  # ------------------------------------------------------------------

  async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
    """상품 신규 등록."""
    return await self._call_api("POST", "/v1/products", body=payload)

  async def update_product(
    self, product_no: str, payload: dict[str, Any]
  ) -> dict[str, Any]:
    """상품 수정."""
    return await self._call_api("PUT", f"/v1/products/{product_no}", body=payload)

  async def delete_product(self, product_no: str) -> dict[str, Any]:
    """상품 삭제/판매중지."""
    return await self._call_api("DELETE", f"/v1/products/{product_no}")

  async def get_product(self, product_no: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api("GET", f"/v1/products/{product_no}")


class TossApiError(Exception):
  """토스 API 에러."""
  pass
