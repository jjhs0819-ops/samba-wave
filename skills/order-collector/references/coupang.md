# 쿠팡 주문 수집 — 미구현

소스: `backend/backend/domain/samba/proxy/coupang.py`

**구현 상태: 미구현** (상품 등록만 구현, 주문 API 없음)

---

## Wing API 주문 엔드포인트 (구현 필요)

### 주문 조회

- **엔드포인트:** `GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{vendorId}/orders`
- **인증:** HMAC-SHA256 (product-upload 스킬 `references/coupang.md` 참조)
- **파라미터:** `createdAtFrom`, `createdAtTo`, `status`
- **응답:** JSON 배열

### 주문 상태 종류

| 쿠팡 상태 | SambaOrder status | shipping_status |
|---|---|---|
| `ACCEPT` | `pending` | `발송대기` |
| `INSTRUCT` | `pending` | `발송대기` |
| `DEPARTURE` | `shipped` | `배송중` |
| `DELIVERING` | `shipped` | `배송중` |
| `FINAL_DELIVERY` | `delivered` | `배송완료` |
| `NONE_TRACKING` | `shipped` | `배송중` |

### 발주확인

- **엔드포인트:** `PUT /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/{orderId}/receipts`
- **동작:** 주문 접수 확인

### 송장 입력

- **엔드포인트:** `PUT /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/{orderId}/invoices`
- **필드:** `vendorItemId`, `deliveryCompanyCode`, `invoiceNumber`

### 취소/반품 처리

- **취소 승인:** `PATCH /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/cancellation/{receiptId}/approve`
- **반품 승인:** `PATCH /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/orders/returns/{receiptId}/approve`

---

## 구현 시 참고

- `CoupangClient` 클래스에 `get_orders()`, `confirm_order()`, `approve_cancel()`, `approve_return()` 메서드 추가 필요
- `order.py` 라우터에서 `market_type == "coupang"` 분기 추가
- `_parse_coupang_order()` 함수 작성 필요
- 정산금액: 쿠팡 API의 `settlementAmount` 필드 사용
