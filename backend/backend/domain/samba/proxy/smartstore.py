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
        # 네이버 API는 invalidInputs 배열로 상세 에러 제공
        msg = data.get("message", "") or data.get("reason", "") or text[:200]
        invalid_inputs = data.get("invalidInputs") or []
        if invalid_inputs:
          details = "; ".join(
            f"{iv.get('field', '?')}: {iv.get('message', '')}" for iv in invalid_inputs if isinstance(iv, dict)
          )
          msg = f"{msg} [{details}]"
        raise SmartStoreApiError(f"HTTP {resp.status_code}: {msg}")

      return data

  # ------------------------------------------------------------------
  # 채널(스토어) 정보 조회
  # ------------------------------------------------------------------

  async def get_channel_info(self) -> dict[str, Any]:
    """채널(스토어) 정보를 조회하여 스토어 슬러그 등 반환."""
    result = await self._call_api("GET", "/v1/seller/channels")
    logger.info(f"[스마트스토어] 채널 조회 raw: {result}")

    # 다양한 응답 구조 대응
    channels: list[Any] = []
    if isinstance(result, list):
      channels = result
    elif isinstance(result, dict):
      for key in ("contents", "channels", "data", "result"):
        val = result.get(key)
        if isinstance(val, list) and val:
          channels = val
          break
      # 단일 객체 응답 (channelNo가 최상위에 있는 경우)
      if not channels and result.get("channelNo"):
        channels = [result]

    if not channels:
      logger.warning("[스마트스토어] 채널 목록이 비어있음")
      return {}

    ch = channels[0]
    # channel이 nested일 수 있음
    if isinstance(ch.get("channel"), dict):
      ch = ch["channel"]

    # URL 필드 다양한 키 시도
    url = ch.get("url") or ch.get("channelUrl") or ch.get("storeUrl") or ""
    slug = url.rstrip("/").split("/")[-1] if url else ""

    logger.info(f"[스마트스토어] 채널 파싱 결과 — url={url}, slug={slug}")

    return {
      "channelNo": ch.get("channelNo", ""),
      "channelName": ch.get("name", ch.get("channelName", "")),
      "storeSlug": slug,
      "url": url,
    }

  async def get_store_slug_fallback(self) -> str:
    """채널 API 실패 시 — 등록된 상품에서 스토어 슬러그 추출."""
    try:
      result = await self._call_api("POST", "/v1/products/search", body={
        "page": 1, "size": 1,
      })
      logger.info(f"[스마트스토어] 슬러그 fallback 상품검색 raw: {result}")

      # 응답에서 상품 목록 추출
      contents = []
      if isinstance(result, dict):
        contents = result.get("contents", result.get("data", []))
      if isinstance(result, list):
        contents = result

      if not contents:
        return ""

      product = contents[0]
      # 상품의 smartStoreUrl 또는 channelProducts에서 URL 추출
      store_url = product.get("smartStoreUrl", "")
      if not store_url:
        channel_products = product.get("channelProducts", [])
        for cp in channel_products:
          cp_url = cp.get("url") or cp.get("channelProductUrl") or ""
          if "smartstore.naver.com" in cp_url:
            store_url = cp_url
            break

      if store_url and "smartstore.naver.com" in store_url:
        # https://smartstore.naver.com/슬러그/products/... → 슬러그 추출
        parts = store_url.split("smartstore.naver.com/")
        if len(parts) > 1:
          slug = parts[1].split("/")[0]
          logger.info(f"[스마트스토어] fallback 슬러그 추출: {slug}")
          return slug

      return ""
    except Exception as e:
      logger.warning(f"[스마트스토어] 슬러그 fallback 실패: {e}")
      return ""

  # ------------------------------------------------------------------
  # 카테고리 조회
  # ------------------------------------------------------------------

  async def get_categories(self, last_only: bool = True) -> list[dict[str, Any]]:
    """네이버 커머스 카테고리 전체 조회.

    GET /v1/categories?last={true|false}
    응답: [{wholeCategoryName, id, name, last}, ...]
    """
    params = {"last": str(last_only).lower()}
    return await self._call_api("GET", "/v1/categories", params=params)

  # ------------------------------------------------------------------
  # 상품 등록
  # ------------------------------------------------------------------

  async def upload_image_from_url(self, image_url: str) -> str:
    """외부 이미지 URL을 네이버 커머스에 업로드하고 네이버 URL을 반환."""
    token = await self._ensure_token()
    # 이미지 다운로드
    # 이미지 원본 도메인을 Referer로 사용 (CDN 핫링크 방지 우회)
    from urllib.parse import urlparse
    parsed = urlparse(image_url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    # 무신사 CDN은 musinsa.com Referer가 필요
    if "msscdn.net" in (parsed.netloc or ""):
      referer = "https://www.musinsa.com/"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
      img_resp = await client.get(image_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
      })
      if not img_resp.is_success:
        raise SmartStoreApiError(f"이미지 다운로드 실패: {img_resp.status_code}")
      img_bytes = img_resp.content
      content_type = img_resp.headers.get("content-type", "image/jpeg")
      # CDN 경고 이미지 감지 (너무 작으면 핫링크 차단 이미지일 가능성)
      if len(img_bytes) < 1000:
        raise SmartStoreApiError(f"이미지가 비정상적으로 작음({len(img_bytes)}B) — CDN 차단 가능성")

    # 네이버 이미지 업로드 API
    ext = "jpg"
    if "png" in content_type:
      ext = "png"
    elif "webp" in content_type:
      ext = "webp"

    async with httpx.AsyncClient(timeout=30) as client:
      resp = await client.post(
        f"{self.BASE_URL}/v1/product-images/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"imageFiles": (f"image.{ext}", img_bytes, content_type)},
      )
      if not resp.is_success:
        raise SmartStoreApiError(f"이미지 업로드 실패: {resp.status_code} {resp.text[:200]}")
      data = resp.json()
      images = data.get("images", [])
      if not images:
        raise SmartStoreApiError("이미지 업로드 응답에 URL 없음")
      return images[0].get("url", "")

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
          "afterServiceInfo": {"afterServiceTelephoneNumber": "02-0000-0000", "afterServiceGuideContent": "A/S 안내"},
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
  # 주문 조회
  # ------------------------------------------------------------------

  async def get_orders(
    self,
    days: int = 7,
    order_status: str = "",
  ) -> list[dict[str, Any]]:
    """최근 N일간 주문 조회.

    Commerce API: GET /v1/pay-order/seller/product-orders/last-changed-statuses
    """
    from datetime import datetime, timedelta, timezone

    # KST 기준으로 시작 시간 계산 (스마트스토어 API 최대 90일 제한)
    kst = timezone(timedelta(hours=9))
    effective_days = min(days, 89)
    since = datetime.now(kst) - timedelta(days=effective_days)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")

    params: dict[str, Any] = {
      "lastChangedFrom": since_str,
    }
    if order_status:
      params["lastChangedType"] = order_status

    # 1단계: 변경된 주문 ID 목록 조회 (여러 구간으로 분할하여 누락 방지)
    logger.info(f"[스마트스토어] 주문 조회 시작 lastChangedFrom={since_str}")

    all_statuses: list[dict[str, Any]] = []
    seen_po_ids: set[str] = set()

    # 요청 기간 + 최근 1일 병행 조회 (API 시크릿 재발급 등으로 과거 데이터 조회 불가 대비)
    query_dates = [since_str]
    recent = datetime.now(kst) - timedelta(days=1)
    recent_str = recent.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")
    if recent_str != since_str:
      query_dates.append(recent_str)

    for qdate in query_dates:
      qparams = dict(params)
      qparams["lastChangedFrom"] = qdate
      result = await self._call_api(
        "GET",
        "/v1/pay-order/seller/product-orders/last-changed-statuses",
        params=qparams,
      )
      data = result.get("data", result) if isinstance(result, dict) else {}
      statuses = data.get("lastChangeStatuses", []) if isinstance(data, dict) else []
      for s in statuses:
        pid = s.get("productOrderId", "")
        if pid and pid not in seen_po_ids:
          seen_po_ids.add(pid)
          all_statuses.append(s)

    logger.info(f"[스마트스토어] 변경된 주문 수: {len(all_statuses)}")

    if not all_statuses:
      return []

    statuses = all_statuses

    # 2단계: 주문 상세 조회
    po_ids = [s.get("productOrderId") for s in statuses if s.get("productOrderId")]
    if not po_ids:
      return []

    logger.info(f"[스마트스토어] 상세 조회 대상: {len(po_ids)}건")
    details_result = await self._call_api(
      "POST",
      "/v1/pay-order/seller/product-orders/query",
      body={"productOrderIds": po_ids[:300]},
    )

    details_data = details_result.get("data", details_result) if isinstance(details_result, dict) else details_result
    # data가 리스트이면 그대로 사용, 딕셔너리면 productOrders 키에서 추출
    if isinstance(details_data, list):
      orders_data = details_data
    elif isinstance(details_data, dict):
      orders_data = details_data.get("productOrders", [])
    else:
      orders_data = []
    logger.info(f"[스마트스토어] 주문 상세 결과: {len(orders_data)}건")
    return orders_data

  async def confirm_product_orders(
    self, product_order_ids: list[str]
  ) -> dict[str, Any]:
    """발주확인 (placeOrderStatus: NOT_YET → OK).

    Commerce API: POST /v1/pay-order/seller/product-orders/confirm
    """
    result = await self._call_api(
      "POST",
      "/v1/pay-order/seller/product-orders/confirm",
      body={"productOrderIds": product_order_ids},
    )
    logger.info(f"[스마트스토어] 발주확인 {len(product_order_ids)}건 요청")
    return result

  async def approve_cancel(self, product_order_id: str) -> dict[str, Any]:
    """취소요청 승인.

    Commerce API: POST /v1/pay-order/seller/product-orders/{id}/claim/cancel/approve
    """
    result = await self._call_api(
      "POST",
      f"/v1/pay-order/seller/product-orders/{product_order_id}/claim/cancel/approve",
    )
    logger.info(f"[스마트스토어] 취소승인 완료: {product_order_id}")
    return result

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

    sale_price = int(product.get("sale_price", 0))
    if sale_price <= 0:
      sale_price = int(product.get("original_price", 0)) or 10000

    brand = product.get("brand", "") or "상세설명 참조"
    # 제조사 정보 (manufacturer 필드에 "제조사: Nike inc. / 수입처: 나이키코리아" 형태로 저장)
    mfr = product.get("manufacturer", "") or brand

    # 옵션에서 사이즈 정보 추출
    options = product.get("options") or []
    sizes = [o.get("size", "") or o.get("name", "") for o in options if o.get("size") or o.get("name")]
    size_text = ", ".join(sorted(set(s for s in sizes if s)))[:200] or "상세설명 참조"

    # 카테고리에서 상품 유형 판단
    category = product.get("category", "") or ""
    name_lower = product.get("name", "").lower()

    # 색상: 상품명에서 추출 시도
    color_part = ""
    if " - " in product.get("name", ""):
      color_part = product["name"].split(" - ", 1)[1].split("/")[0].strip()
    # DB color 필드 우선, 없으면 상품명에서 추출
    db_color = product.get("color", "")
    color_text = db_color or (color_part[:200] if color_part else "상세 이미지 참조")

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
        "salePrice": sale_price,
        "stockQuantity": 999,
        "deliveryInfo": {
          "deliveryType": "DELIVERY",
          "deliveryAttributeType": "NORMAL",
          "deliveryCompany": "CJGLS",
          "deliveryFee": {
            "deliveryFeeType": delivery_fee_type,
            "baseFee": 0,
          },
          "claimDeliveryInfo": {
            "returnDeliveryFee": 3000,
            "exchangeDeliveryFee": 6000,
          },
        },
        "detailAttribute": {
          "afterServiceInfo": {
            "afterServiceTelephoneNumber": "02-1234-5678",
            "afterServiceGuideContent": "상세페이지 참조",
          },
          "originAreaInfo": {
            "originAreaCode": "03",
            "content": product.get("origin", "") or "해외",
          },
          "minorPurchasable": False,
          "productInfoProvidedNotice": {
            "productInfoProvidedNoticeType": "WEAR",
            "wear": {
              "material": product.get("material", "") or "상세 이미지 참조",
              "color": color_text,
              "size": f"발길이(mm): {size_text}" if sizes else "FREE (상세 이미지 참조)",
              "manufacturer": mfr,
              "caution": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 사용 금지",
              "packDateText": "주문 후 개별포장 발송",
              "warrantyPolicy": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
              "afterServiceDirector": f"{brand} 고객센터",
            },
          },
        },
      },
      "smartstoreChannelProduct": {
        "channelProductName": product.get("name", ""),
        "storeKeepExclusiveProduct": False,
        "naverShoppingRegistration": False,
        "channelProductDisplayStatusType": "ON",
      },
    }


class SmartStoreApiError(Exception):
  """스마트스토어 API 에러."""
  pass
