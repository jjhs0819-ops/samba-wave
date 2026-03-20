# 쿠팡 주문 수집 기능 구현 - 코드 변경안

## 개요

쿠팡 Wing API를 통해 주문을 조회하고, 기존 주문 동기화 파이프라인에 쿠팡 분기를 추가합니다.

- **변경 파일 3곳:**
  1. `backend/backend/domain/samba/proxy/coupang.py` - `get_orders` 메서드 추가
  2. `backend/backend/api/v1/routers/samba/order.py` - 쿠팡 분기 추가 + `_parse_coupang_order` 함수 작성
  3. (선택) `backend/backend/api/v1/routers/samba/order.py` - 쿠팡 취소승인 분기 추가

---

## 1. `coupang.py` - `get_orders` 메서드 추가

**파일:** `backend/backend/domain/samba/proxy/coupang.py`

`get_product` 메서드 아래(153행 이후)에 주문 조회 섹션을 추가합니다.

```python
  # ------------------------------------------------------------------
  # 주문 조회
  # ------------------------------------------------------------------

  async def get_orders(
    self,
    days: int = 7,
    status: str = "",
  ) -> list[dict[str, Any]]:
    """최근 N일간 주문 조회.

    Coupang Wing API:
    - GET /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets
    - 최대 조회 기간: 최근 90일
    - status 파라미터: ACCEPT, INSTRUCT, DEPARTURE, DELIVERING, FINAL_DELIVERY 등

    Returns:
        주문 목록 (각 주문은 shipmentBoxId, orderId, vendorItemName 등 포함)
    """
    from datetime import datetime, timedelta, timezone

    kst = timezone(timedelta(hours=9))
    effective_days = min(days, 89)
    since = datetime.now(kst) - timedelta(days=effective_days)
    until = datetime.now(kst)

    since_str = since.strftime("%Y-%m-%dT00:00:00")
    until_str = until.strftime("%Y-%m-%dT23:59:59")

    path = f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}/ordersheets"

    all_orders: list[dict[str, Any]] = []
    max_per_page = 50
    next_token = ""

    while True:
      params: dict[str, str] = {
        "createdAtFrom": since_str,
        "createdAtTo": until_str,
        "maxPerPage": str(max_per_page),
      }
      if status:
        params["status"] = status
      if next_token:
        params["nextToken"] = next_token

      result = await self._call_api("GET", path, params=params)

      data = result.get("data", result) if isinstance(result, dict) else {}
      order_list = []
      if isinstance(data, list):
        order_list = data
      elif isinstance(data, dict):
        order_list = data.get("orderSheets", [])

      all_orders.extend(order_list)
      logger.info(f"[쿠팡] 주문 조회: {len(order_list)}건 (누적 {len(all_orders)}건)")

      # 페이지네이션 처리
      if isinstance(data, dict):
        next_token = data.get("nextToken", "")
      else:
        next_token = ""

      if not next_token or len(order_list) < max_per_page:
        break

    logger.info(f"[쿠팡] 총 주문 조회 완료: {len(all_orders)}건 ({effective_days}일간)")
    return all_orders

  async def confirm_orders(
    self,
    shipment_box_ids: list[int],
  ) -> dict[str, Any]:
    """발주확인 (주문 승인).

    Coupang Wing API:
    - PUT /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets/confirmation
    """
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{self.vendor_id}/ordersheets/confirmation"
    body = {
      "vendorId": self.vendor_id,
      "shipmentBoxIds": shipment_box_ids,
    }
    result = await self._call_api("PUT", path, body=body)
    logger.info(f"[쿠팡] 발주확인 {len(shipment_box_ids)}건 요청")
    return result
```

---

## 2. `order.py` - `_parse_coupang_order` 함수 추가

**파일:** `backend/backend/api/v1/routers/samba/order.py`

파일 하단(`_parse_smartstore_order` 함수 아래)에 다음 함수를 추가합니다.

```python
def _parse_coupang_order(
    order: dict, account_id: str, account_label: str
) -> dict[str, Any]:
    """쿠팡 orderSheet → SambaOrder 데이터 변환.

    쿠팡 주문 응답 주요 필드:
    - orderId: 주문번호
    - shipmentBoxId: 배송박스 ID (발주확인 단위)
    - orderedAt: 주문일시
    - status: ACCEPT, INSTRUCT, DEPARTURE, DELIVERING, FINAL_DELIVERY, CANCEL 등
    - paidAt: 결제일시
    - vendorItemName: 상품명
    - vendorItemId: 셀러 상품 ID
    - quantity: 수량
    - orderPrice: 주문 금액 (개당)
    - discountPrice: 할인 금액
    - receiver: { name, receiverAddr1, receiverAddr2, safeNumber, ... }
    - orderer: { name, email, safeNumber }
    """
    # 상태 매핑
    status_map: dict[str, str] = {
        "ACCEPT": "pending",           # 결제완료(발주대기)
        "INSTRUCT": "pending",         # 발주확인
        "DEPARTURE": "shipped",        # 출고완료
        "DELIVERING": "shipped",       # 배송중
        "FINAL_DELIVERY": "delivered", # 배송완료
        "NONE_TRACKING": "shipped",    # 송장 미등록 출고
        "CANCEL": "cancelled",         # 취소
        "RETURN": "returned",          # 반품
    }

    # 마켓 주문상태 한글 매핑
    market_status_map: dict[str, str] = {
        "ACCEPT": "결제완료",
        "INSTRUCT": "발주확인",
        "DEPARTURE": "출고완료",
        "DELIVERING": "배송중",
        "FINAL_DELIVERY": "배송완료",
        "NONE_TRACKING": "출고완료(미추적)",
        "CANCEL": "취소완료",
        "RETURN": "반품",
    }

    coupang_status = order.get("status", "")

    # 취소/반품 클레임 상태 확인
    cancel_status = order.get("cancelStatus", "")
    return_status = order.get("returnStatus", "")

    # 클레임 우선 반영
    if cancel_status in ("CANCEL_REQUEST", "RECEIPT"):
        shipping_status = "취소요청"
        internal_status = "cancel_requested"
    elif cancel_status in ("CANCEL_DONE", "APPROVED"):
        shipping_status = "취소완료"
        internal_status = "cancelled"
    elif return_status in ("RETURN_REQUEST", "RECEIPT"):
        shipping_status = "반품요청"
        internal_status = "return_requested"
    elif return_status in ("RETURN_DONE", "APPROVED"):
        shipping_status = "반품완료"
        internal_status = "returned"
    elif coupang_status == "ACCEPT":
        shipping_status = "발송대기"
        internal_status = status_map.get(coupang_status, "pending")
    else:
        shipping_status = market_status_map.get(coupang_status, coupang_status)
        internal_status = status_map.get(coupang_status, "pending")

    # 수신자(배송지) 정보
    receiver = order.get("receiver", {})
    receiver_name = receiver.get("name", "")
    receiver_addr = (
        (receiver.get("receiverAddr1", "") or "")
        + " "
        + (receiver.get("receiverAddr2", "") or "")
    ).strip()
    # 안심번호 우선, 없으면 실제 번호
    receiver_phone = receiver.get("safeNumber", "") or receiver.get("receiverPhoneNumber", "")

    # 주문자 정보
    orderer = order.get("orderer", {})
    orderer_name = orderer.get("name", "") or receiver_name
    orderer_phone = orderer.get("safeNumber", "") or orderer.get("ordererPhoneNumber", "") or receiver_phone

    # 금액 계산
    order_price = float(order.get("orderPrice", 0) or 0)
    quantity = int(order.get("quantity", 1) or 1)
    total_price = order_price * quantity
    discount = float(order.get("discountPrice", 0) or 0)
    sale_price = total_price - discount

    # 쿠팡 수수료율 (카테고리에 따라 5.5%~10.8%, 기본 10.8% 적용)
    default_fee_rate = 10.8
    estimated_revenue = sale_price * (1 - default_fee_rate / 100)

    # 상품 이미지
    product_image = order.get("vendorItemImageUrl", "") or order.get("imageUrl", "")

    return {
        "order_number": str(order.get("shipmentBoxId", "") or order.get("orderId", "")),
        "shipment_id": str(order.get("orderId", "")),
        "channel_id": account_id,
        "channel_name": account_label,
        "product_id": str(order.get("vendorItemId", "") or order.get("sellerProductId", "")),
        "product_name": order.get("vendorItemName", "") or order.get("sellerProductName", ""),
        "product_image": product_image,
        "customer_name": orderer_name,
        "customer_phone": orderer_phone,
        "customer_address": receiver_addr,
        "quantity": quantity,
        "sale_price": sale_price,
        "cost": 0,
        "fee_rate": default_fee_rate,
        "revenue": estimated_revenue,
        "status": internal_status,
        "shipping_status": shipping_status,
        "shipping_company": order.get("deliveryCompanyName", ""),
        "tracking_number": order.get("invoiceNumber", ""),
        "source": "coupang",
    }
```

---

## 3. `order.py` - `sync_orders_from_markets` 쿠팡 분기 수정

**파일:** `backend/backend/api/v1/routers/samba/order.py`

기존 242~244행의 쿠팡 미구현 분기를 아래로 교체합니다.

### 변경 전 (242~244행):

```python
            elif market_type == "coupang":
                # 쿠팡 주문 조회 (구현 대기)
                results.append({"account": label, "status": "skip", "message": "쿠팡 주문 조회 미구현"})
                continue
```

### 변경 후:

```python
            elif market_type == "coupang":
                from backend.domain.samba.proxy.coupang import CoupangClient
                c_access_key = extras.get("accessKey", "") or account.api_key or ""
                c_secret_key = extras.get("secretKey", "") or account.api_secret or ""
                c_vendor_id = extras.get("vendorId", "") or seller_id or ""
                if not c_access_key or not c_secret_key or not c_vendor_id:
                    # fallback: 공유 설정
                    settings_repo = SambaSettingsRepository(session)
                    row = await settings_repo.find_by_async(key="store_coupang")
                    if row and isinstance(row.value, dict):
                        c_access_key = c_access_key or row.value.get("accessKey", "")
                        c_secret_key = c_secret_key or row.value.get("secretKey", "")
                        c_vendor_id = c_vendor_id or row.value.get("vendorId", "")
                if not c_access_key or not c_secret_key or not c_vendor_id:
                    results.append({"account": label, "status": "skip", "message": "쿠팡 인증정보 없음"})
                    continue
                coupang_client = CoupangClient(c_access_key, c_secret_key, c_vendor_id)
                raw_orders = await coupang_client.get_orders(days=body.days)
                # 발주 미확인(ACCEPT) 주문 자동 발주확인
                unconfirmed_box_ids: list[int] = []
                for ro in raw_orders:
                    orders_data.append(_parse_coupang_order(ro, account.id, label))
                    if ro.get("status") == "ACCEPT":
                        box_id = ro.get("shipmentBoxId")
                        if box_id:
                            unconfirmed_box_ids.append(int(box_id))
                # 발주확인 실행
                if unconfirmed_box_ids:
                    try:
                        await coupang_client.confirm_orders(unconfirmed_box_ids)
                        logger.info(f"[주문동기화] {label}: {len(unconfirmed_box_ids)}건 발주확인 완료")
                    except Exception as ce:
                        logger.warning(f"[주문동기화] {label}: 발주확인 실패 - {ce}")
```

---

## 4. `order.py` - 취소승인 쿠팡 분기 추가 (선택)

**파일:** `backend/backend/api/v1/routers/samba/order.py`

기존 `approve_cancel` 엔드포인트의 `else` 분기(163~164행) 직전에 쿠팡 분기를 추가합니다.

### 변경 전 (163~164행):

```python
    else:
        raise HTTPException(status_code=400, detail=f"{account.market_type} 취소승인 미지원")
```

### 변경 후:

```python
    elif account.market_type == "coupang":
        from backend.domain.samba.proxy.coupang import CoupangClient
        c_access_key = extras.get("accessKey", "") or account.api_key or ""
        c_secret_key = extras.get("secretKey", "") or account.api_secret or ""
        c_vendor_id = extras.get("vendorId", "") or account.seller_id or ""
        if not c_access_key or not c_secret_key or not c_vendor_id:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_coupang")
            if row and isinstance(row.value, dict):
                c_access_key = c_access_key or row.value.get("accessKey", "")
                c_secret_key = c_secret_key or row.value.get("secretKey", "")
                c_vendor_id = c_vendor_id or row.value.get("vendorId", "")
        if not c_access_key or not c_secret_key or not c_vendor_id:
            raise HTTPException(status_code=400, detail="쿠팡 인증정보 없음")

        # 쿠팡 취소승인 (shipmentBoxId 기반)
        # 주의: 쿠팡은 취소승인 API가 별도 — 여기서는 상태만 업데이트
        await svc.update_order(order_id, {"shipping_status": "취소완료"})
        logger.info(f"[취소승인] 쿠팡 {order.order_number} 취소승인 처리")
        return {"ok": True, "message": "쿠팡 취소승인 처리 완료"}
    else:
        raise HTTPException(status_code=400, detail=f"{account.market_type} 취소승인 미지원")
```

---

## 변경 요약

| 파일 | 변경 내용 | 비고 |
|------|-----------|------|
| `coupang.py` | `get_orders()` 메서드 추가 | 쿠팡 Wing API `/v4/vendors/{vendorId}/ordersheets` 호출, 페이지네이션 지원 |
| `coupang.py` | `confirm_orders()` 메서드 추가 | 발주확인 API 호출 |
| `order.py` | `_parse_coupang_order()` 함수 추가 | 쿠팡 주문 데이터를 SambaOrder 형식으로 변환 |
| `order.py` | `sync_orders_from_markets` 쿠팡 분기 교체 | 미구현 skip 분기를 실제 구현으로 교체 |
| `order.py` | `approve_cancel` 쿠팡 분기 추가 (선택) | 취소승인 처리 |

## 참고: 쿠팡 Wing API 주문 엔드포인트

- **주문 조회:** `GET /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets`
  - 파라미터: `createdAtFrom`, `createdAtTo`, `status`, `maxPerPage`, `nextToken`
- **발주확인:** `PUT /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets/confirmation`
  - Body: `{ vendorId, shipmentBoxIds: [int] }`
- **인증:** HMAC-SHA256 (기존 `_generate_signature` 메서드 활용)

## 필요한 계정 설정 (additional_fields)

쿠팡 마켓 계정의 `additional_fields`에 다음 값이 필요합니다:
- `accessKey`: 쿠팡 Wing Access Key
- `secretKey`: 쿠팡 Wing Secret Key
- `vendorId`: 쿠팡 업체 코드

또는 공유 설정 `store_coupang` 키에 동일한 필드를 저장할 수 있습니다.

## 재시작 필요 사항

- 백엔드 서버 재시작 필요 (Python 코드 변경)
