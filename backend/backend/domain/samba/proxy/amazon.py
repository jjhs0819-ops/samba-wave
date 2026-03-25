"""아마존 SP-API 클라이언트 - 상품 등록/수정.

인증 방식: LWA OAuth (Login with Amazon)
- Refresh Token → Access Token 발급 (1시간 유효)
- x-amz-access-token 헤더로 API 호출
- 참고: 실제 프로덕션에서는 AWS Signature V4가 추가로 필요할 수 있음
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from backend.utils.logger import logger

# 리전별 SP-API 엔드포인트
_REGION_ENDPOINTS: dict[str, str] = {
  "fe": "https://sellingpartnerapi-fe.amazon.com",   # 일본 (극동)
  "na": "https://sellingpartnerapi-na.amazon.com",   # 북미
  "eu": "https://sellingpartnerapi-eu.amazon.com",   # 유럽
}

# LWA 토큰 발급 엔드포인트
_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


class AmazonClient:
  """아마존 SP-API 클라이언트."""

  def __init__(
    self,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    seller_id: str,
    region: str = "fe",
  ) -> None:
    self.refresh_token = refresh_token
    self.client_id = client_id
    self.client_secret = client_secret
    self.seller_id = seller_id
    self.region = region

    # SP-API 베이스 URL (리전별)
    self.base_url = _REGION_ENDPOINTS.get(region, _REGION_ENDPOINTS["fe"])

    # 토큰 캐싱
    self._access_token: str = ""
    self._token_expires_at: float = 0.0

  # ------------------------------------------------------------------
  # LWA 토큰 발급/갱신
  # ------------------------------------------------------------------

  async def _ensure_token(self) -> None:
    """Access Token 발급 (Refresh Token 기반).

    1시간 유효, 만료 5분 전에 자동 갱신.
    """
    # 유효한 토큰이 있으면 스킵
    if self._access_token and time.time() < self._token_expires_at - 300:
      return

    logger.info("[아마존] LWA Access Token 발급 요청")

    async with httpx.AsyncClient(timeout=15) as client:
      resp = await client.post(
        _LWA_TOKEN_URL,
        data={
          "grant_type": "refresh_token",
          "refresh_token": self.refresh_token,
          "client_id": self.client_id,
          "client_secret": self.client_secret,
        },
      )

      if not resp.is_success:
        try:
          err = resp.json()
          msg = err.get("error_description", "") or err.get("error", "")
        except Exception:
          msg = resp.text[:300]
        raise AmazonApiError(f"LWA 토큰 발급 실패 HTTP {resp.status_code}: {msg}")

      data = resp.json()
      self._access_token = data["access_token"]
      # expires_in은 초 단위 (보통 3600)
      self._token_expires_at = time.time() + data.get("expires_in", 3600)

    logger.info("[아마존] LWA Access Token 발급 성공")

  # ------------------------------------------------------------------
  # 인증 헤더
  # ------------------------------------------------------------------

  def _headers(self) -> dict[str, str]:
    """SP-API 호출용 헤더.

    x-amz-access-token 으로 인증.
    """
    return {
      "x-amz-access-token": self._access_token,
      "Content-Type": "application/json",
      "User-Agent": "samba-wave/1.0",
    }

  # ------------------------------------------------------------------
  # 공통 API 호출
  # ------------------------------------------------------------------

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
  ) -> dict[str, Any]:
    """공통 SP-API 호출.

    참고: 실제로는 AWS Signature V4가 필요할 수 있음.
    Access Token만으로 호출 시도 후 실패하면 안내 메시지 포함.
    """
    await self._ensure_token()

    url = f"{self.base_url}{path}"
    headers = self._headers()

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
        resp = await client.delete(url, headers=headers, params=params)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      # 응답 파싱
      try:
        data = resp.json()
      except Exception:
        data = {"raw": resp.text}

      logger.info(f"[아마존] {method} {path} → {resp.status_code}")

      if not resp.is_success:
        msg = ""
        if isinstance(data, dict):
          # SP-API 에러 구조
          errors = data.get("errors", [])
          if errors:
            msg = "; ".join(
              f"{e.get('code', '')}: {e.get('message', '')}"
              for e in errors
            )
          else:
            msg = data.get("message", "") or data.get("error", "")

        if not msg:
          msg = resp.text[:300]

        # AWS Signature V4 필요 안내
        if resp.status_code == 403:
          msg += (
            " | 참고: AWS Signature V4 서명이 필요할 수 있습니다. "
            "현재는 LWA Access Token만으로 호출합니다."
          )

        raise AmazonApiError(f"HTTP {resp.status_code}: {msg}")

      return data

  # ------------------------------------------------------------------
  # 상품 데이터 변환
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str = "",
    account_settings: Optional[dict[str, Any]] = None,
  ) -> dict[str, Any]:
    """SambaCollectedProduct → 아마존 Listings API 형식 변환.

    SP-API Listings Items 2021-08-01 스펙 기준.
    """
    # SKU: 상품 고유 ID
    sku = str(
      product.get("id", "")
      or product.get("site_product_id", "")
    )[:40]

    # 상품명
    item_name = (product.get("name", "") or "")[:500]

    # 브랜드
    brand_name = product.get("brand", "") or ""

    # 판매가격
    sale_price = product.get("sale_price", 0)

    # 이미지 (최대 9장)
    images_raw = product.get("images") or []
    main_image = images_raw[0] if images_raw else ""
    other_images = images_raw[1:9] if len(images_raw) > 1 else []

    # 상세 설명
    description = product.get("detail_html", "") or product.get("name", "")
    # HTML 태그 제거 (아마존은 일부 카테고리에서 HTML 미지원)
    import re
    description_text = re.sub(r"<[^>]+>", "", description)[:2000]

    # 마켓플레이스 ID (리전별 기본값)
    marketplace_id = ""
    if account_settings:
      marketplace_id = account_settings.get("marketplace_id", "")
    if not marketplace_id:
      # 기본 마켓플레이스: 일본
      marketplace_id = "A1VC38T7YXB528"

    # 속성 구성
    attributes: dict[str, Any] = {
      "item_name": [{"value": item_name, "marketplace_id": marketplace_id}],
      "condition_type": [{"value": "new_new", "marketplace_id": marketplace_id}],
    }

    # 브랜드 (있을 경우)
    if brand_name:
      attributes["brand_name"] = [{"value": brand_name, "marketplace_id": marketplace_id}]

    # 가격
    if sale_price:
      currency = "JPY"  # 기본 엔화 (리전별 정책에서 변환)
      if account_settings:
        currency = account_settings.get("currency", "JPY")
      attributes["list_price"] = [{
        "value": sale_price,
        "currency": currency,
        "marketplace_id": marketplace_id,
      }]

    # 대표 이미지
    if main_image:
      attributes["main_product_image_locator"] = [{
        "value": main_image,
        "marketplace_id": marketplace_id,
      }]

    # 추가 이미지
    for idx, img_url in enumerate(other_images, start=1):
      attributes[f"other_product_image_locator_{idx}"] = [{
        "value": img_url,
        "marketplace_id": marketplace_id,
      }]

    # 설명
    if description_text:
      attributes["product_description"] = [{
        "value": description_text,
        "marketplace_id": marketplace_id,
      }]

    # 재고/풀필먼트
    attributes["fulfillment_availability"] = [{
      "fulfillment_channel_code": "DEFAULT",
      "quantity": 999,
      "marketplace_id": marketplace_id,
    }]

    # 카테고리 (product_type)
    product_type = category_id or "PRODUCT"

    payload: dict[str, Any] = {
      "productType": product_type,
      "requirements": "LISTING",
      "attributes": attributes,
    }

    # 계정별 추가 설정
    if account_settings:
      if account_settings.get("fulfillment_channel"):
        attributes["fulfillment_availability"] = [{
          "fulfillment_channel_code": account_settings["fulfillment_channel"],
          "quantity": 999,
          "marketplace_id": marketplace_id,
        }]

    return payload

  # ------------------------------------------------------------------
  # 상품 등록
  # ------------------------------------------------------------------

  async def register_product(
    self, payload: dict[str, Any], sku: str
  ) -> dict[str, Any]:
    """상품 등록 (Listings API PUT).

    PUT /listings/2021-08-01/items/{sellerId}/{sku}
    """
    if not sku:
      raise AmazonApiError("SKU가 필요합니다")

    result = await self._call_api(
      "PUT",
      f"/listings/2021-08-01/items/{self.seller_id}/{sku}",
      body=payload,
      params={"marketplaceIds": self._default_marketplace_id()},
    )
    logger.info(f"[아마존] 상품 등록 성공: {sku}")
    return {"success": True, "data": result}

  # ------------------------------------------------------------------
  # 상품 수정
  # ------------------------------------------------------------------

  async def update_product(
    self, sku: str, payload: dict[str, Any]
  ) -> dict[str, Any]:
    """상품 수정 (Listings API PATCH).

    PATCH /listings/2021-08-01/items/{sellerId}/{sku}
    """
    result = await self._call_api(
      "PATCH",
      f"/listings/2021-08-01/items/{self.seller_id}/{sku}",
      body=payload,
      params={"marketplaceIds": self._default_marketplace_id()},
    )
    logger.info(f"[아마존] 상품 수정 성공: {sku}")
    return {"success": True, "data": result}

  # ------------------------------------------------------------------
  # 상품 삭제
  # ------------------------------------------------------------------

  async def delete_product(self, sku: str) -> dict[str, Any]:
    """상품 삭제 (Listings API DELETE).

    DELETE /listings/2021-08-01/items/{sellerId}/{sku}
    """
    result = await self._call_api(
      "DELETE",
      f"/listings/2021-08-01/items/{self.seller_id}/{sku}",
      params={"marketplaceIds": self._default_marketplace_id()},
    )
    logger.info(f"[아마존] 상품 삭제 성공: {sku}")
    return {"success": True, "data": result}

  # ------------------------------------------------------------------
  # 상품 조회
  # ------------------------------------------------------------------

  async def get_product(self, sku: str) -> dict[str, Any]:
    """상품 조회 (Listings API GET)."""
    return await self._call_api(
      "GET",
      f"/listings/2021-08-01/items/{self.seller_id}/{sku}",
      params={"marketplaceIds": self._default_marketplace_id()},
    )

  # ------------------------------------------------------------------
  # 유틸리티
  # ------------------------------------------------------------------

  def _default_marketplace_id(self) -> str:
    """리전별 기본 마켓플레이스 ID 반환."""
    marketplace_map: dict[str, str] = {
      "fe": "A1VC38T7YXB528",   # 일본 (Amazon.co.jp)
      "na": "ATVPDKIKX0DER",    # 미국 (Amazon.com)
      "eu": "A1PA6795UKMFR9",   # 독일 (Amazon.de)
    }
    return marketplace_map.get(self.region, marketplace_map["fe"])


class AmazonApiError(Exception):
  """아마존 SP-API 에러."""
  pass
