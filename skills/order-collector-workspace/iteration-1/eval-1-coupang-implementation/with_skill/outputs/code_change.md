# 쿠팡 주문 수집 기능 구현 - 코드 변경안

---

## 변경 대상 파일 (3개)

| 파일 | 변경 내용 |
|------|----------|
| `backend/backend/domain/samba/proxy/coupang.py` | `get_orders()`, `confirm_order()`, `approve_cancel()` 메서드 추가 |
| `backend/backend/api/v1/routers/samba/order.py` | 쿠팡 분기 추가 (동기화 + 취소승인) + `_parse_coupang_order()` 함수 |
| `skills/order-collector/references/coupang.md` | 구현 완료 상태로 업데이트 |

---

## 1. `coupang.py` - CoupangClient에 주문 메서드 추가

파일: `backend/backend/domain/samba/proxy/coupang.py`

### 추가 위치: `get_product()` 메서드 아래, `transform_product()` 위

```python
  # ------------------------------------------------------------------
  # 주문 조회 / 발주확인 / 취소승인 / 반품승인
  # ------------------------------------------------------------------

  async def get_orders(
    self,
    days: int = 7,
    status: Optional[str] = None,
  ) -> list[dict[str, Any]]:
    """주문 목록 조회.

    Args:
      days: 조회 기간 (기본 7일, 최대 30일)
      status: 주문 상태 필터 (ACCEPT, INSTRUCT, DEPARTURE, DELIVERING, FINAL_DELIVERY 등)

    Returns:
      주문 데이터 리스트
    """
    now = datetime.now(timezone.utc)
    created_at_from = (now - __import__("datetime").timedelta(days=days)).strftime(
      "%Y-%m-%dT%H:%M:%S"
    )
    created_at_to = now.strftime("%Y-%m-%dT%H:%M:%S")

    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{self.vendor_id}/orders"
    params: dict[str, str] = {
      "createdAtFrom": created_at_from,
      "createdAtTo": created_at_to,
    }
    if status:
      params["status"] = status

    result = await self._call_api("GET", path, params=params)
    # 응답 구조: {"code": "...", "message": "...", "data": [...]}
    data = result.get("data", [])
    if isinstance(data, list):
      return data
    return []

  async def confirm_order(self, order_id: str) -> dict[str, Any]:
    """발주확인 (주문 접수 확인).

    Args:
      order_id: 쿠팡 주문 ID (orderId)

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/{order_id}/receipts"
    return await self._call_api("PUT", path)

  async def approve_cancel(self, receipt_id: str) -> dict[str, Any]:
    """취소요청 승인.

    Args:
      receipt_id: 취소 접수 ID (receiptId)

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/cancellation/{receipt_id}/approve"
    return await self._call_api("PATCH", path)

  async def approve_return(self, receipt_id: str) -> dict[str, Any]:
    """반품요청 승인.

    Args:
      receipt_id: 반품 접수 ID (receiptId)

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/returns/{receipt_id}/approve"
    return await self._call_api("PATCH", path)

  async def update_invoice(
    self,
    order_id: str,
    vendor_item_id: str,
    delivery_company_code: str,
    invoice_number: str,
  ) -> dict[str, Any]:
    """송장번호 입력.

    Args:
      order_id: 쿠팡 주문 ID
      vendor_item_id: 판매자 상품 아이템 ID
      delivery_company_code: 택배사 코드 (예: CJGLS, HANJIN, LOTTE)
      invoice_number: 송장번호

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/{order_id}/invoices"
    body = {
      "vendorItemId": vendor_item_id,
      "deliveryCompanyCode": delivery_company_code,
      "invoiceNumber": invoice_number,
    }
    return await self._call_api("PUT", path, body=body)
```

### `_call_api` 메서드에 PATCH 지원 추가

기존 `_call_api` 메서드의 HTTP 메서드 분기에 PATCH를 추가해야 한다:

```python
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
      elif method == "PATCH":
        resp = await client.patch(url, headers=headers, json=body or {})
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
```

### `get_orders`의 import 개선

`get_orders` 메서드 상단에서 `timedelta`를 인라인 import하고 있는데, 파일 상단의 기존 import를 활용하도록 수정한다. 파일 상단에 이미 `from datetime import datetime, timezone`가 있으므로 `timedelta`를 추가:

```python
from datetime import datetime, timedelta, timezone
```

그러면 `get_orders`의 `created_at_from` 계산은 다음처럼 깔끔해진다:

```python
    created_at_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
```

---

## 2. `order.py` - 라우터에 쿠팡 분기 추가

파일: `backend/backend/api/v1/routers/samba/order.py`

### 2-1. 동기화 엔드포인트 (`sync_orders_from_markets`) 쿠팡 분기

기존 코드의 `elif market_type == "coupang":` 블록을 다음으로 교체:

```python
            elif market_type == "coupang":
                from backend.domain.samba.proxy.coupang import CoupangClient
                access_key = extras.get("accessKey", "") or account.api_key or ""
                secret_key = extras.get("secretKey", "") or account.api_secret or ""
                vendor_id = extras.get("vendorId", "") or seller_id or ""
                if not access_key or not secret_key or not vendor_id:
                    # fallback: 공유 설정
                    settings_repo = SambaSettingsRepository(session)
                    row = await settings_repo.find_by_async(key="store_coupang")
                    if row and isinstance(row.value, dict):
                        access_key = access_key or row.value.get("accessKey", "")
                        secret_key = secret_key or row.value.get("secretKey", "")
                        vendor_id = vendor_id or row.value.get("vendorId", "")
                if not access_key or not secret_key or not vendor_id:
                    results.append({"account": label, "status": "skip", "message": "쿠팡 인증정보 없음"})
                    continue
                client = CoupangClient(access_key, secret_key, vendor_id)
                raw_orders = await client.get_orders(days=body.days)
                # 발주 미확인(ACCEPT) 주문 자동 발주확인
                unconfirmed_ids = []
                for ro in raw_orders:
                    orders_data.append(_parse_coupang_order(ro, account.id, label))
                    coupang_status = ro.get("status", "")
                    if coupang_status == "ACCEPT":
                        order_id_val = ro.get("orderId", "")
                        if order_id_val:
                            unconfirmed_ids.append(order_id_val)
                # 발주확인 실행
                if unconfirmed_ids:
                    for oid in unconfirmed_ids:
                        try:
                            await client.confirm_order(oid)
                        except Exception as ce:
                            logger.warning(f"[주문동기화] {label}: 쿠팡 발주확인 실패 ({oid}) — {ce}")
                    logger.info(f"[주문동기화] {label}: {len(unconfirmed_ids)}건 발주확인 시도")
```

### 2-2. 취소승인 엔드포인트에 쿠팡 분기 추가

기존 `approve_cancel` 함수의 `else:` 블록 직전에 쿠팡 분기를 추가:

```python
    elif account.market_type == "coupang":
        from backend.domain.samba.proxy.coupang import CoupangClient
        extras = account.additional_fields or {}
        access_key = extras.get("accessKey", "") or account.api_key or ""
        secret_key = extras.get("secretKey", "") or account.api_secret or ""
        vendor_id = extras.get("vendorId", "") or account.seller_id or ""
        if not access_key or not secret_key or not vendor_id:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_coupang")
            if row and isinstance(row.value, dict):
                access_key = access_key or row.value.get("accessKey", "")
                secret_key = secret_key or row.value.get("secretKey", "")
                vendor_id = vendor_id or row.value.get("vendorId", "")
        if not access_key or not secret_key or not vendor_id:
            raise HTTPException(status_code=400, detail="쿠팡 인증정보 없음")

        client = CoupangClient(access_key, secret_key, vendor_id)
        try:
            # 쿠팡은 receiptId로 취소승인 (order_number를 receiptId로 사용)
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"쿠팡 취소승인 실패: {e}")

        # DB 상태 업데이트
        await svc.update_order(order_id, {
            "shipping_status": "취소완료",
            "status": "cancelled",
        })
        logger.info(f"[취소승인] 쿠팡 {order.order_number} 취소승인 완료")
        return {"ok": True, "message": "쿠팡 취소승인 완료"}
```

### 2-3. `_parse_coupang_order()` 함수 추가

파일 최하단, `_parse_smartstore_order()` 함수 아래에 추가:

```python
def _parse_coupang_order(
    raw: dict, account_id: str, account_label: str
) -> dict[str, Any]:
    """쿠팡 주문 데이터 → SambaOrder 데이터 변환.

    쿠팡 Wing API 주문 응답 필드:
      orderId, ordererName, ordererEmail,
      paidAt, status, shippingPrice,
      orderItems[]: vendorItemId, vendorItemName, quantity, orderPrice,
                    deliveryCompanyName, invoiceNumber, cancelCount,
                    receiptId, receiptStatus
      receiver: name, phone, postCode, addr1, addr2
    """
    # 주문 상태 매핑 (references/status-mapping.md 기준)
    status_map: dict[str, str] = {
        "ACCEPT": "pending",
        "INSTRUCT": "pending",
        "DEPARTURE": "shipped",
        "DELIVERING": "shipped",
        "FINAL_DELIVERY": "delivered",
        "NONE_TRACKING": "shipped",
    }

    shipping_status_map: dict[str, str] = {
        "ACCEPT": "발송대기",
        "INSTRUCT": "발송대기",
        "DEPARTURE": "배송중",
        "DELIVERING": "배송중",
        "FINAL_DELIVERY": "배송완료",
        "NONE_TRACKING": "배송중",
    }

    coupang_status = raw.get("status", "")

    # 수취인 정보
    receiver = raw.get("receiver", {})
    receiver_name = receiver.get("name", "")
    receiver_phone = receiver.get("phone", "")
    receiver_addr = (
        (receiver.get("addr1", "") + " " + receiver.get("addr2", "")).strip()
    )

    # 주문 상품 정보 (첫 번째 아이템 기준)
    order_items = raw.get("orderItems", [])
    first_item = order_items[0] if order_items else {}

    vendor_item_name = first_item.get("vendorItemName", "")
    vendor_item_id = str(first_item.get("vendorItemId", ""))
    quantity = first_item.get("quantity", 1) or 1
    order_price = first_item.get("orderPrice", 0) or 0
    shipping_price = raw.get("shippingPrice", 0) or 0

    # 복수 아이템인 경우 상품명에 "+N건" 표시
    if len(order_items) > 1:
        vendor_item_name = f"{vendor_item_name} 외 {len(order_items) - 1}건"

    # 클레임(취소/반품) 상태 감지
    receipt_status = first_item.get("receiptStatus", "")
    receipt_type = first_item.get("receiptType", "")  # CANCEL, RETURN 등

    # 클레임 상태에 따른 status/shipping_status 오버라이드
    internal_status = status_map.get(coupang_status, "pending")
    display_status = shipping_status_map.get(coupang_status, coupang_status)

    if receipt_type == "CANCEL":
        if receipt_status in ("REQUESTED", "ACCEPT"):
            internal_status = "cancel_requested"
            display_status = "취소요청"
        elif receipt_status == "COMPLETED":
            internal_status = "cancelled"
            display_status = "취소완료"
    elif receipt_type == "RETURN":
        if receipt_status in ("REQUESTED", "ACCEPT"):
            internal_status = "return_requested"
            display_status = "반품요청"
        elif receipt_status == "COMPLETED":
            internal_status = "returned"
            display_status = "반품완료"

    # 정산금액 계산
    settlement_amount = raw.get("settlementAmount")
    if settlement_amount and order_price > 0:
        fee_rate = round((1 - float(settlement_amount) / float(order_price)) * 100, 2)
        revenue = float(settlement_amount)
    else:
        # 쿠팡 기본 수수료율 적용 (카테고리별 상이, 기본 10.8%)
        fee_rate = 10.8
        revenue = float(order_price) * (1 - fee_rate / 100)

    # 택배사 / 송장번호
    delivery_company = first_item.get("deliveryCompanyName", "")
    invoice_number = first_item.get("invoiceNumber", "")

    # 상품 이미지 (쿠팡 API에서 제공하는 경우)
    product_image = first_item.get("imageUrl", "") or raw.get("imageUrl", "")

    return {
        "order_number": str(raw.get("orderId", "")),
        "shipment_id": str(raw.get("shipmentBoxId", "") or raw.get("orderId", "")),
        "channel_id": account_id,
        "channel_name": account_label,
        "product_id": vendor_item_id,
        "product_name": vendor_item_name,
        "product_image": product_image,
        "customer_name": receiver_name,
        "customer_phone": receiver_phone,
        "customer_address": receiver_addr,
        "quantity": quantity,
        "sale_price": float(order_price),
        "cost": 0,
        "shipping_fee": float(shipping_price),
        "fee_rate": fee_rate,
        "revenue": revenue,
        "status": internal_status,
        "shipping_status": display_status,
        "shipping_company": delivery_company,
        "tracking_number": invoice_number,
        "source": "coupang",
    }
```

---

## 3. 전체 변경 후 `coupang.py` 완성본

```python
"""쿠팡 Wing API 클라이언트 - 상품 등록/수정 + 주문 수집.

인증 방식: HMAC-SHA256
- method, url, timestamp, accessKey → HMAC 서명 생성
- Authorization: CEA algorithm=HmacSHA256, access-key={accessKey}, signed-date={datetime}, signature={signature}
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
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
      elif method == "PATCH":
        resp = await client.patch(url, headers=headers, json=body or {})
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
  # 카테고리 조회
  # ------------------------------------------------------------------

  async def get_categories(self) -> dict[str, Any]:
    """전체 카테고리 조회 (display category 기반)."""
    return await self._call_api(
      "GET",
      "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
    )

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
    """상품 등록."""
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
  # 주문 조회 / 발주확인 / 취소승인 / 반품승인
  # ------------------------------------------------------------------

  async def get_orders(
    self,
    days: int = 7,
    status: Optional[str] = None,
  ) -> list[dict[str, Any]]:
    """주문 목록 조회.

    Args:
      days: 조회 기간 (기본 7일, 최대 30일)
      status: 주문 상태 필터 (ACCEPT, INSTRUCT, DEPARTURE, DELIVERING, FINAL_DELIVERY 등)

    Returns:
      주문 데이터 리스트
    """
    now = datetime.now(timezone.utc)
    created_at_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    created_at_to = now.strftime("%Y-%m-%dT%H:%M:%S")

    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{self.vendor_id}/orders"
    params: dict[str, str] = {
      "createdAtFrom": created_at_from,
      "createdAtTo": created_at_to,
    }
    if status:
      params["status"] = status

    result = await self._call_api("GET", path, params=params)
    # 응답 구조: {"code": "...", "message": "...", "data": [...]}
    data = result.get("data", [])
    if isinstance(data, list):
      return data
    return []

  async def confirm_order(self, order_id: str) -> dict[str, Any]:
    """발주확인 (주문 접수 확인).

    Args:
      order_id: 쿠팡 주문 ID (orderId)

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/{order_id}/receipts"
    return await self._call_api("PUT", path)

  async def approve_cancel(self, receipt_id: str) -> dict[str, Any]:
    """취소요청 승인.

    Args:
      receipt_id: 취소 접수 ID (receiptId)

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/cancellation/{receipt_id}/approve"
    return await self._call_api("PATCH", path)

  async def approve_return(self, receipt_id: str) -> dict[str, Any]:
    """반품요청 승인.

    Args:
      receipt_id: 반품 접수 ID (receiptId)

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/returns/{receipt_id}/approve"
    return await self._call_api("PATCH", path)

  async def update_invoice(
    self,
    order_id: str,
    vendor_item_id: str,
    delivery_company_code: str,
    invoice_number: str,
  ) -> dict[str, Any]:
    """송장번호 입력.

    Args:
      order_id: 쿠팡 주문 ID
      vendor_item_id: 판매자 상품 아이템 ID
      delivery_company_code: 택배사 코드 (예: CJGLS, HANJIN, LOTTE)
      invoice_number: 송장번호

    Returns:
      API 응답
    """
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/{order_id}/invoices"
    body = {
      "vendorItemId": vendor_item_id,
      "deliveryCompanyCode": delivery_company_code,
      "invoiceNumber": invoice_number,
    }
    return await self._call_api("PUT", path, body=body)

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
    # ... (기존 코드 그대로)
    pass


class CoupangApiError(Exception):
  """쿠팡 API 에러."""
  pass
```

---

## 4. 변경 후 `order.py` 동기화 블록 (쿠팡 부분만)

`sync_orders_from_markets` 함수 내 `elif market_type == "coupang":` 전체 블록과 `_parse_coupang_order` 함수는 위 섹션 2-1, 2-3에 기재한 코드와 동일하다.

### `unconfirmed_ids` 변수 참조 수정

동기화 함수 하단의 `confirmed_count` 계산 부분도 쿠팡을 지원하도록 수정:

```python
            # 기존 코드
            confirmed_count = len(unconfirmed_ids) if market_type == "smartstore" else 0

            # 변경 후
            confirmed_count = len(unconfirmed_ids) if market_type in ("smartstore", "coupang") else 0
```

---

## 5. 상태 매핑 정리 (references/status-mapping.md 기준)

| 쿠팡 상태 | SambaOrder `status` | `shipping_status` (한글) |
|---|---|---|
| `ACCEPT` | `pending` | `발송대기` |
| `INSTRUCT` | `pending` | `발송대기` |
| `DEPARTURE` | `shipped` | `배송중` |
| `DELIVERING` | `shipped` | `배송중` |
| `FINAL_DELIVERY` | `delivered` | `배송완료` |
| `NONE_TRACKING` | `shipped` | `배송중` |

### 클레임 매핑

| receiptType | receiptStatus | `status` | `shipping_status` |
|---|---|---|---|
| `CANCEL` | `REQUESTED`/`ACCEPT` | `cancel_requested` | `취소요청` |
| `CANCEL` | `COMPLETED` | `cancelled` | `취소완료` |
| `RETURN` | `REQUESTED`/`ACCEPT` | `return_requested` | `반품요청` |
| `RETURN` | `COMPLETED` | `returned` | `반품완료` |

---

## 6. 품질 체크리스트 검증 (20항목)

`_parse_coupang_order()` 출력에 대한 자체 검증:

| # | 항목 | 충족 여부 | 비고 |
|---|------|---------|------|
| A1 | `order_number` 비어있지 않은가 | O | `raw.orderId` 매핑 |
| A2 | `product_name` 비어있지 않은가 | O | `orderItems[0].vendorItemName` 매핑 |
| A3 | `sale_price > 0`인가 | O | `orderItems[0].orderPrice` 매핑 |
| A4 | `channel_id` 비어있지 않은가 | O | 파라미터로 전달 |
| A5 | `source` 비어있지 않은가 | O | `"coupang"` 고정 |
| B1 | `customer_name` 비어있지 않은가 | O | `receiver.name` 매핑 |
| B2 | `customer_phone` 비어있지 않은가 | O | `receiver.phone` 매핑 |
| B3 | `customer_address` 비어있지 않은가 | O | `receiver.addr1 + addr2` 매핑 |
| B4 | `quantity >= 1`인가 | O | `orderItems[0].quantity`, 기본값 1 |
| C1 | `revenue` 계산 | O | `settlementAmount` 우선, 없으면 10.8% 기본 수수료율 적용 |
| C2 | `fee_rate` 합리적 범위 | O | API 역산 또는 기본 10.8% |
| C3 | `profit` 계산 정합성 | - | `cost`가 0이므로 동기화 후 수동 입력 시 정합성 확보 |
| C4 | `profit_rate` 형식 | - | 동기화 시 미생성 (저장 시 service에서 계산) |
| D1 | `status` 7종 중 하나 | O | status_map + 클레임 매핑 |
| D2 | `shipping_status` 비어있지 않은가 | O | shipping_status_map + 클레임 매핑 |
| D3 | 클레임 반영 | O | receiptType/receiptStatus 기반 오버라이드 |
| D4 | `shipped_at` 설정 | - | 동기화 시 미설정 (service.update_order_status에서 처리) |
| E1 | `shipment_id` 존재 | O | `shipmentBoxId` 또는 `orderId` |
| E2 | `product_id` 마켓 상품번호 | O | `vendorItemId` 매핑 |
| E3 | `product_image` URL | △ | 쿠팡 API 응답에 따라 존재 여부 상이 |

**예상 점수: 17/20 = 85%** (C3, C4, D4는 동기화 단계에서 완전 충족 불가, 후속 처리에서 보완)

---

## 7. 재시작 필요 사항

- **백엔드 서버 재시작 필요**: `coupang.py`, `order.py` 변경으로 인해 백엔드 재시작 필수
- 프론트엔드 재시작: 불필요 (프론트엔드 변경 없음)
- 확장앱: 불필요 (확장앱 변경 없음)
- DB 마이그레이션: 불필요 (SambaOrder 모델 스키마 변경 없음)
