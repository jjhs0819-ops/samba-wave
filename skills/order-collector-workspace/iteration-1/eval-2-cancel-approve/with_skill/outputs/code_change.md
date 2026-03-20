# 취소승인 멀티마켓 확장 — 쿠팡/11번가 지원

## 개요

현재 `POST /orders/{order_id}/approve-cancel` 엔드포인트는 스마트스토어만 지원한다.
쿠팡과 11번가에도 취소승인을 할 수 있도록 프록시 메서드 추가 + 라우터 분기 확장을 진행한다.

---

## 변경 대상 파일 (3개)

| 파일 | 변경 내용 |
|------|----------|
| `backend/backend/domain/samba/proxy/coupang.py` | `approve_cancel()` 메서드 추가 |
| `backend/backend/domain/samba/proxy/elevenst.py` | `approve_cancel()` 메서드 추가 |
| `backend/backend/api/v1/routers/samba/order.py` | `approve_cancel` 엔드포인트에 쿠팡/11번가 분기 추가 |

---

## 1. 쿠팡 프록시 — `approve_cancel()` 메서드 추가

**파일:** `backend/backend/domain/samba/proxy/coupang.py`

**API 사양** (Wing API):
- **엔드포인트:** `PATCH /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/cancellation/{receiptId}/approve`
- **인증:** HMAC-SHA256 (기존 `_call_api` 활용)
- **receiptId:** 취소접수번호 (주문번호가 아닌 취소요청 건의 고유 ID)

**주의사항:**
- 쿠팡은 HTTP 메서드로 `PATCH`를 사용한다. 현재 `_call_api`에 `PATCH` 분기가 없으므로 함께 추가해야 한다.
- `receiptId`는 취소접수번호로, 주문 동기화 시 취소 클레임 정보에서 추출하여 `order_number` 또는 별도 필드에 저장해야 한다. 현재 구조에서는 `order_number`(마켓 주문번호)를 receiptId로 사용한다.

### 코드 변경

`_call_api` 메서드에 PATCH 지원 추가 (기존 elif 체인에 삽입):

```python
# coupang.py — _call_api 메서드 내부, PUT 분기 아래에 추가
elif method == "PATCH":
  resp = await client.patch(url, headers=headers, json=body or {})
```

`approve_cancel` 메서드 추가 (상품 조회 메서드 아래, `transform_product` 위에 삽입):

```python
# ------------------------------------------------------------------
# 주문 취소승인
# ------------------------------------------------------------------

async def approve_cancel(self, receipt_id: str) -> dict[str, Any]:
  """취소요청 승인.

  Wing API: PATCH /v2/providers/seller_api/apis/api/v1/marketplace/
            seller-products/orders/cancellation/{receiptId}/approve
  """
  path = (
    f"/v2/providers/seller_api/apis/api/v1/marketplace/"
    f"seller-products/orders/cancellation/{receipt_id}/approve"
  )
  result = await self._call_api("PATCH", path)
  logger.info(f"[쿠팡] 취소승인 완료: {receipt_id}")
  return result
```

### 전체 diff

```diff
--- a/backend/backend/domain/samba/proxy/coupang.py
+++ b/backend/backend/domain/samba/proxy/coupang.py
@@ -83,6 +83,8 @@
       elif method == "PUT":
         resp = await client.put(url, headers=headers, json=body or {})
+      elif method == "PATCH":
+        resp = await client.patch(url, headers=headers, json=body or {})
       elif method == "DELETE":
         resp = await client.delete(url, headers=headers)
       else:
@@ -153,6 +155,22 @@
       f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}",
     )

+  # ------------------------------------------------------------------
+  # 주문 취소승인
+  # ------------------------------------------------------------------
+
+  async def approve_cancel(self, receipt_id: str) -> dict[str, Any]:
+    """취소요청 승인.
+
+    Wing API: PATCH /v2/providers/seller_api/apis/api/v1/marketplace/
+              seller-products/orders/cancellation/{receiptId}/approve
+    """
+    path = (
+      f"/v2/providers/seller_api/apis/api/v1/marketplace/"
+      f"seller-products/orders/cancellation/{receipt_id}/approve"
+    )
+    result = await self._call_api("PATCH", path)
+    logger.info(f"[쿠팡] 취소승인 완료: {receipt_id}")
+    return result
+
   # ------------------------------------------------------------------
   # 상품 데이터 변환
   # ------------------------------------------------------------------
```

---

## 2. 11번가 프록시 — `approve_cancel()` 메서드 추가

**파일:** `backend/backend/domain/samba/proxy/elevenst.py`

**API 사양** (OpenAPI):
- **엔드포인트:** `PUT /rest/orderservices/order/{ordNo}/cancel/approve`
- **인증:** `openapikey` 헤더 (기존 `_headers()` 활용)
- **응답:** XML

**주의사항:**
- 11번가는 상품 API(`/rest/prodservices`)와 주문 API(`/rest/orderservices`)의 BASE_URL이 다르다. 현재 `BASE_URL`은 `https://api.11st.co.kr/rest/prodservices`이므로, 주문 API 호출 시 별도의 URL을 사용해야 한다.
- `_call_api`에 `url_override` 파라미터를 추가하거나, 주문 전용 BASE_URL 상수를 추가한다.

### 코드 변경

주문 API용 BASE_URL 상수 추가:

```python
class ElevenstClient:
  """11번가 셀러 API 클라이언트."""

  BASE_URL = "https://api.11st.co.kr/rest/prodservices"
  ORDER_BASE_URL = "https://api.11st.co.kr/rest/orderservices"  # 주문 API용
```

주문 API 전용 호출 메서드 추가:

```python
async def _call_order_api(
  self,
  method: str,
  path: str,
  body: Optional[str] = None,
) -> dict[str, Any]:
  """주문 API 호출 (ORDER_BASE_URL 사용)."""
  url = f"{self.ORDER_BASE_URL}{path}"
  headers = self._headers()

  async with httpx.AsyncClient(timeout=30) as client:
    if method == "GET":
      resp = await client.get(url, headers=headers)
    elif method == "POST":
      resp = await client.post(url, headers=headers, content=body)
    elif method == "PUT":
      resp = await client.put(url, headers=headers, content=body)
    else:
      raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

    logger.info(f"[11번가] {method} {url} → {resp.status_code}")
    logger.debug(f"[11번가] 응답 본문: {resp.text[:500]}")

    data = self._parse_xml(resp.text)

    if not resp.is_success:
      msg = data.get("message", "") or data.get("raw", "") or resp.text[:300]
      raise ElevenstApiError(f"HTTP {resp.status_code}: {msg}")

    result_code = data.get("resultCode", "") or data.get("ResultCode", "")
    if result_code and str(result_code) != "200" and str(result_code) != "0":
      msg = data.get("resultMessage", "") or data.get("message", "")
      raise ElevenstApiError(f"API 에러 ({result_code}): {msg}")

    return data
```

`approve_cancel` 메서드 추가 (상품 조회 메서드 아래, `transform_product` 위에 삽입):

```python
# ------------------------------------------------------------------
# 주문 취소승인
# ------------------------------------------------------------------

async def approve_cancel(self, ord_no: str) -> dict[str, Any]:
  """취소요청 승인.

  11번가 OpenAPI: PUT /rest/orderservices/order/{ordNo}/cancel/approve
  """
  result = await self._call_order_api(
    "PUT",
    f"/order/{ord_no}/cancel/approve",
  )
  logger.info(f"[11번가] 취소승인 완료: {ord_no}")
  return result
```

### 전체 diff

```diff
--- a/backend/backend/domain/samba/proxy/elevenst.py
+++ b/backend/backend/domain/samba/proxy/elevenst.py
@@ -22,6 +22,7 @@

   BASE_URL = "https://api.11st.co.kr/rest/prodservices"
+  ORDER_BASE_URL = "https://api.11st.co.kr/rest/orderservices"  # 주문 API용

   def __init__(self, api_key: str) -> None:
     self.api_key = api_key
@@ -92,6 +93,40 @@

       return data

+  async def _call_order_api(
+    self,
+    method: str,
+    path: str,
+    body: Optional[str] = None,
+  ) -> dict[str, Any]:
+    """주문 API 호출 (ORDER_BASE_URL 사용)."""
+    url = f"{self.ORDER_BASE_URL}{path}"
+    headers = self._headers()
+
+    async with httpx.AsyncClient(timeout=30) as client:
+      if method == "GET":
+        resp = await client.get(url, headers=headers)
+      elif method == "POST":
+        resp = await client.post(url, headers=headers, content=body)
+      elif method == "PUT":
+        resp = await client.put(url, headers=headers, content=body)
+      else:
+        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")
+
+      logger.info(f"[11번가] {method} {url} → {resp.status_code}")
+      logger.debug(f"[11번가] 응답 본문: {resp.text[:500]}")
+
+      data = self._parse_xml(resp.text)
+
+      if not resp.is_success:
+        msg = data.get("message", "") or data.get("raw", "") or resp.text[:300]
+        raise ElevenstApiError(f"HTTP {resp.status_code}: {msg}")
+
+      result_code = data.get("resultCode", "") or data.get("ResultCode", "")
+      if result_code and str(result_code) != "200" and str(result_code) != "0":
+        msg = data.get("resultMessage", "") or data.get("message", "")
+        raise ElevenstApiError(f"API 에러 ({result_code}): {msg}")
+
+      return data
+
   # ------------------------------------------------------------------
   # 카테고리 조회
   # ------------------------------------------------------------------
@@ -125,6 +160,20 @@
     """상품 조회."""
     return await self._call_api("GET", f"/product/{prd_no}")

+  # ------------------------------------------------------------------
+  # 주문 취소승인
+  # ------------------------------------------------------------------
+
+  async def approve_cancel(self, ord_no: str) -> dict[str, Any]:
+    """취소요청 승인.
+
+    11번가 OpenAPI: PUT /rest/orderservices/order/{ordNo}/cancel/approve
+    """
+    result = await self._call_order_api(
+      "PUT",
+      f"/order/{ord_no}/cancel/approve",
+    )
+    logger.info(f"[11번가] 취소승인 완료: {ord_no}")
+    return result
+
   # ------------------------------------------------------------------
   # 상품 데이터 변환 (수집 상품 → 11번가 XML 형식)
   # ------------------------------------------------------------------
```

---

## 3. 라우터 — `approve_cancel` 엔드포인트 멀티마켓 분기 추가

**파일:** `backend/backend/api/v1/routers/samba/order.py`

현재 `approve_cancel` 엔드포인트는 `account.market_type == "smartstore"` 일 때만 동작하고,
나머지는 `"{market_type} 취소승인 미지원"` 에러를 반환한다.

쿠팡과 11번가 분기를 추가한다.

### 변경 전 (현재 코드)

```python
@router.post("/{order_id}/approve-cancel")
async def approve_cancel(
    order_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """취소요청 주문에 대해 마켓 취소승인 실행."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")

    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")

    # 마켓 계정 조회
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    if account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient
        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증정보 없음")

        client = SmartStoreClient(client_id, client_secret)
        try:
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

        # DB 상태 업데이트
        await svc.update_order(order_id, {
            "shipping_status": "취소완료",
        })
        logger.info(f"[취소승인] {order.order_number} 취소승인 완료")
        return {"ok": True, "message": "취소승인 완료"}
    else:
        raise HTTPException(status_code=400, detail=f"{account.market_type} 취소승인 미지원")
```

### 변경 후 (전체 교체)

```python
@router.post("/{order_id}/approve-cancel")
async def approve_cancel(
    order_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """취소요청 주문에 대해 마켓 취소승인 실행 (스마트스토어/쿠팡/11번가 지원)."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")

    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")

    # 마켓 계정 조회
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    extras = account.additional_fields or {}

    # ── 스마트스토어 ──
    if account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증정보 없음")

        client = SmartStoreClient(client_id, client_secret)
        try:
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

    # ── 쿠팡 ──
    elif account.market_type == "coupang":
        from backend.domain.samba.proxy.coupang import CoupangClient

        access_key = extras.get("accessKey", "") or account.api_key or ""
        secret_key = extras.get("secretKey", "") or account.api_secret or ""
        vendor_id = extras.get("vendorId", "") or account.seller_id or ""
        if not access_key or not secret_key:
            raise HTTPException(status_code=400, detail="쿠팡 인증정보 없음 (accessKey/secretKey)")

        client = CoupangClient(access_key, secret_key, vendor_id)
        try:
            # order_number를 receiptId(취소접수번호)로 사용
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

    # ── 11번가 ──
    elif account.market_type == "11st":
        from backend.domain.samba.proxy.elevenst import ElevenstClient

        api_key = extras.get("apiKey", "") or account.api_key or ""
        if not api_key:
            raise HTTPException(status_code=400, detail="11번가 인증정보 없음 (apiKey)")

        client = ElevenstClient(api_key)
        try:
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

    else:
        raise HTTPException(status_code=400, detail=f"{account.market_type} 취소승인 미지원")

    # DB 상태 업데이트 (공통)
    await svc.update_order(order_id, {
        "shipping_status": "취소완료",
    })
    logger.info(f"[취소승인] {order.order_number} ({account.market_type}) 취소승인 완료")
    return {"ok": True, "message": "취소승인 완료"}
```

### 주요 변경점

1. **공통 로직 추출**: DB 상태 업데이트(`shipping_status = "취소완료"`)를 각 마켓 분기 밖으로 꺼내어 중복 제거
2. **쿠팡 분기 추가**: `CoupangClient`의 인증정보(accessKey, secretKey, vendorId)를 계정에서 추출하여 `approve_cancel` 호출
3. **11번가 분기 추가**: `ElevenstClient`의 인증정보(apiKey)를 계정에서 추출하여 `approve_cancel` 호출
4. **로그 메시지에 마켓 타입 추가**: 어느 마켓의 취소승인인지 식별 가능

---

## 마켓별 취소승인 API 요약

| 마켓 | HTTP 메서드 | 엔드포인트 | 식별자 | 인증 |
|------|-----------|-----------|--------|------|
| 스마트스토어 | `POST` | `/v1/pay-order/seller/product-orders/{productOrderId}/claim/cancel/approve` | productOrderId | OAuth2 Bearer |
| 쿠팡 | `PATCH` | `/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/cancellation/{receiptId}/approve` | receiptId (취소접수번호) | HMAC-SHA256 |
| 11번가 | `PUT` | `/rest/orderservices/order/{ordNo}/cancel/approve` | ordNo (주문번호) | openapikey 헤더 |

---

## 재시작 필요 항목

- **백엔드 서버 재시작 필요** (라우터 코드 변경)
- 프론트엔드 변경 없음 (기존 `handleApproveCancel()` → `orderApi.approveCancel(id)` 그대로 사용)
- 확장앱 변경 없음

---

## 후속 작업 (이 변경에 포함되지 않음)

1. **쿠팡 주문 동기화** 구현 — `sync-from-markets`에서 쿠팡 주문 조회 + `_parse_coupang_order()` 작성 (취소승인할 주문이 DB에 들어와야 사용 가능)
2. **11번가 주문 동기화** 구현 — 동일
3. **receiptId 별도 저장** — 쿠팡의 취소접수번호가 주문번호와 다를 경우를 대비하여 `SambaOrder`에 `claim_id` 필드 추가 검토
4. **반품승인 확장** — 동일한 패턴으로 `approve_return` 메서드 및 엔드포인트 추가
