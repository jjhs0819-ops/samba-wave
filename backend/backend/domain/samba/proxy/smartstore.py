"""스마트스토어(네이버 커머스) API 클라이언트 - 상품 등록/수정.

인증 방식: OAuth2 (bcrypt 서명)
- client_id + timestamp → bcrypt hash → Base64 = client_secret_sign
- POST /external/v1/oauth2/token → access_token 발급
- 이후 Bearer 토큰으로 API 호출
"""

from __future__ import annotations

import base64
import time
from typing import Any, Optional

import bcrypt
import httpx

from backend.utils.logger import logger


class SmartStoreClient:
  """네이버 커머스 API 클라이언트."""

  BASE_URL = "https://api.commerce.naver.com/external"

  def __init__(self, client_id: str, client_secret: str) -> None:
    self.client_id = client_id
    self.client_secret = client_secret
    self._access_token: str = ""
    self._token_expires_at: float = 0

  # ------------------------------------------------------------------
  # 인증
  # ------------------------------------------------------------------

  async def _ensure_token(self) -> str:
    """유효한 토큰이 없으면 새로 발급."""
    if self._access_token and time.time() < self._token_expires_at - 60:
      return self._access_token

    timestamp = int(time.time() * 1000)
    password = f"{self.client_id}_{timestamp}"
    hashed = bcrypt.hashpw(
      password.encode("utf-8"),
      self.client_secret.encode("utf-8"),
    )
    client_secret_sign = base64.standard_b64encode(hashed).decode("utf-8")

    async with httpx.AsyncClient(timeout=15) as client:
      resp = await client.post(
        f"{self.BASE_URL}/v1/oauth2/token",
        data={
          "client_id": self.client_id,
          "timestamp": timestamp,
          "client_secret_sign": client_secret_sign,
          "grant_type": "client_credentials",
          "type": "SELF",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
      )
      if resp.status_code != 200:
        err = resp.json() if "json" in resp.headers.get("content-type", "") else {}
        raise SmartStoreApiError(
          f"토큰 발급 실패: {err.get('message', resp.status_code)}"
        )
      data = resp.json()
      self._access_token = data["access_token"]
      self._token_expires_at = time.time() + data.get("expires_in", 3600)
      return self._access_token

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
  ) -> dict[str, Any]:
    """공통 API 호출."""
    token = await self._ensure_token()
    url = f"{self.BASE_URL}{path}"
    headers = {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
      if method == "GET":
        resp = await client.get(url, headers=headers, params=params)
      elif method == "POST":
        resp = await client.post(url, headers=headers, json=body or {})
      elif method == "PUT":
        resp = await client.put(url, headers=headers, json=body or {})
      elif method == "PATCH":
        resp = await client.patch(url, headers=headers, json=body or {})
      elif method == "DELETE":
        resp = await client.delete(url, headers=headers)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      text = resp.text
      try:
        data = resp.json()
      except Exception:
        data = {"raw": text}

      logger.info(f"[스마트스토어] {method} {path} → {resp.status_code}")

      if not resp.is_success:
        msg = data.get("message", "") or data.get("reason", "") or text[:200]
        raise SmartStoreApiError(f"HTTP {resp.status_code}: {msg}")

      return data

  # ------------------------------------------------------------------
  # 상품 등록
  # ------------------------------------------------------------------

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록.

    product_data 예시:
    {
      "originProduct": {
        "statusType": "SALE",
        "saleType": "NEW",
        "leafCategoryId": "50000803",
        "name": "상품명",
        "detailContent": "<p>상세설명 HTML</p>",
        "images": {
          "representativeImage": {"url": "https://..."},
          "optionalImages": [{"url": "https://..."}]
        },
        "salePrice": 29900,
        "stockQuantity": 999,
        "deliveryInfo": {
          "deliveryType": "DELIVERY",
          "deliveryAttributeType": "NORMAL",
          "deliveryFee": {"deliveryFeeType": "FREE"}
        },
        "detailAttribute": {
          "afterServiceInfo": {"afterServiceTelNumber": "02-0000-0000", "afterServiceGuideContent": "A/S 안내"},
          "originAreaInfo": {"originAreaCode": "03", "content": "상세설명에 표기"}
        }
      },
      "smartstoreChannelProduct": {
        "channelProductName": "스마트스토어 노출 상품명",
        "storeKeepExclusiveProduct": false
      }
    }
    """
    result = await self._call_api("POST", "/v2/products", body=product_data)
    return {"success": True, "data": result}

  async def update_product(
    self, product_no: str, product_data: dict[str, Any]
  ) -> dict[str, Any]:
    """상품 수정."""
    result = await self._call_api("PATCH", f"/v2/products/{product_no}", body=product_data)
    return {"success": True, "data": result}

  async def get_product(self, product_no: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api("GET", f"/v2/products/{product_no}")

  # ------------------------------------------------------------------
  # 상품 데이터 변환 (수집 상품 → 스마트스토어 형식)
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str = "",
    delivery_fee_type: str = "FREE",
  ) -> dict[str, Any]:
    """SambaCollectedProduct → 스마트스토어 상품 등록 데이터 변환."""
    images_raw = product.get("images") or []
    representative = {"url": images_raw[0]} if images_raw else {}
    optional = [{"url": u} for u in images_raw[1:5]] if len(images_raw) > 1 else []

    return {
      "originProduct": {
        "statusType": "SALE",
        "saleType": "NEW",
        "leafCategoryId": category_id or "50000803",
        "name": product.get("name", ""),
        "detailContent": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
        "images": {
          "representativeImage": representative,
          "optionalImages": optional,
        },
        "salePrice": int(product.get("sale_price", 0)),
        "stockQuantity": 999,
        "deliveryInfo": {
          "deliveryType": "DELIVERY",
          "deliveryAttributeType": "NORMAL",
          "deliveryFee": {"deliveryFeeType": delivery_fee_type},
        },
        "detailAttribute": {
          "afterServiceInfo": {
            "afterServiceTelNumber": "02-0000-0000",
            "afterServiceGuideContent": "상세페이지 참조",
          },
          "originAreaInfo": {
            "originAreaCode": "03",
            "content": "상세설명에 표기",
          },
        },
      },
      "smartstoreChannelProduct": {
        "channelProductName": product.get("name", ""),
        "storeKeepExclusiveProduct": False,
      },
    }


class SmartStoreApiError(Exception):
  """스마트스토어 API 에러."""
  pass
