# 스마트스토어 주문 수집 — 구현 완료

소스: `backend/backend/domain/samba/proxy/smartstore.py`
라우터: `backend/backend/api/v1/routers/samba/order.py` (177~319)

**구현 상태: 완전 구현** (주문조회 + 발주확인 + 취소승인)

---

## 인증

OAuth2 + bcrypt 서명. product-upload 스킬의 `references/smartstore.md` 참조.
계정 객체 → `samba_settings.store_smartstore` 폴백.

---

## 주문 API 메서드

### get_orders(days, order_status)

- **엔드포인트:** `GET /v1/pay-order/seller/product-orders/last-changed-statuses`
- **제한:** 최대 90일 (`effective_days = min(days, 89)`)
- **시간대:** KST (UTC+9)
- **2단계 조회:**
  1. 변경된 주문 ID 목록 조회 (`lastChangedFrom`)
  2. `POST /v1/pay-order/seller/product-orders/query` 로 상세 조회 (최대 300건)
- **중복 방지:** `seen_po_ids` set으로 dedup
- **병행 조회:** 전체 기간 + 최근 1일 동시 조회 (누락 방지)

### confirm_product_orders(product_order_ids)

- **엔드포인트:** `POST /v1/pay-order/seller/product-orders/confirm`
- **동작:** `placeOrderStatus: NOT_YET → OK`
- **자동 호출:** 동기화 시 `PAYED + NOT_YET` 주문 자동 발주확인

### approve_cancel(product_order_id)

- **엔드포인트:** `POST /v1/pay-order/seller/product-orders/{id}/claim/cancel/approve`
- **동작:** 취소요청 승인
- **호출:** `POST /orders/{id}/approve-cancel` API에서 호출

---

## _parse_smartstore_order() 매핑

라우터 `order.py` 322~433행.

| 스마트스토어 API 필드 | SambaOrder 필드 | 변환 로직 |
|---|---|---|
| `productOrder.productOrderId` | `order_number` | 그대로 |
| `order.orderId` | `shipment_id` | 묶음 주문번호 |
| `productOrder.productName` | `product_name` | 그대로 |
| `productOrder.productOption` | `product_name`에 추가 | `" ({option})"` 형태 |
| `productOrder.imageUrl` | `product_image` | 그대로 |
| `productOrder.quantity` | `quantity` | int 변환 |
| `productOrder.totalPaymentAmount` | `sale_price` | 기본값 |
| `productOrder.unitPrice × quantity` | `sale_price` 대체 | totalPaymentAmount 없을 때 |
| `order.paymentDate` | `created_at` | ISO 파싱, 없으면 now() |
| `shippingAddress.name` | `customer_name` | 수취인명 |
| `shippingAddress.tel1` | `customer_phone` | 연락처 |
| `shippingAddress.(baseAddress + detailAddress)` | `customer_address` | 합산 |
| `productOrder.expectedSettlementAmount` | `revenue` | 정산금액 (있으면 직접 사용) |
| (역산) | `fee_rate` | `(1 - revenue / sale_price) × 100` |
| `productOrder.shippingFeeAmount` | `shipping_fee` | 배송비 |
| `productOrder.deliveryMethod` | 참고 | DELIVERY/VISIT 등 |

### 주문 상태 매핑

```python
status_map = {
  "PAYED": "pending",
  "DELIVERING": "shipped",
  "DELIVERED": "delivered",
  "PURCHASE_DECIDED": "delivered",
  "EXCHANGED": "delivered",
  "CANCELED": "cancelled",
  "CANCEL_DONE": "cancelled",
  "RETURNED": "returned",
  "RETURN_DONE": "returned",
  "CANCEL_REQUEST": "cancel_requested",
  "CANCELING": "cancel_requested",
  "RETURN_REQUEST": "return_requested",
  "COLLECTING": "return_requested",
  "COLLECT_DONE": "return_requested",
}

shipping_status_map = {
  "PAYED": "발송대기",          # NOT_YET이면 "발주미확인"
  "DELIVERING": "배송중",
  "DELIVERED": "배송완료",
  "PURCHASE_DECIDED": "구매확정",
  "EXCHANGED": "교환완료",
  "CANCELED": "취소완료",
  "CANCEL_DONE": "취소완료",
  "RETURNED": "반품완료",
  "RETURN_DONE": "반품완료",
}
```

### 클레임 상태 매핑

```python
claim_status_map = {
  ("CANCEL", "CANCEL_REQUEST"): ("취소요청", "cancel_requested"),
  ("CANCEL", "CANCELING"):      ("취소처리중", "cancel_requested"),
  ("CANCEL", "CANCEL_DONE"):    ("취소완료", "cancelled"),
  ("CANCEL", "CANCEL_REJECT"):  ("취소거부", "pending"),
  ("RETURN", "RETURN_REQUEST"): ("반품요청", "return_requested"),
  ("RETURN", "COLLECTING"):     ("수거중", "return_requested"),
  ("RETURN", "COLLECT_DONE"):   ("수거완료", "return_requested"),
  ("RETURN", "RETURN_DONE"):    ("반품완료", "returned"),
  ("RETURN", "RETURN_REJECT"):  ("반품거부", "pending"),
  ("EXCHANGE", "EXCHANGE_REQUEST"): ("교환요청", "pending"),
  ("EXCHANGE", "EXCHANGING"):       ("교환처리중", "pending"),
  ("EXCHANGE", "EXCHANGE_DONE"):    ("교환완료", "delivered"),
  ("EXCHANGE", "EXCHANGE_REJECT"):  ("교환거부", "pending"),
}
```

---

## 알려진 이슈

1. **발주확인 자동 처리:** 품절 확인 없이 자동 발주확인
2. **90일 제한:** API가 90일 넘는 주문 조회 불가
3. **반품/교환 승인 API 미구현:** approve_cancel만 있고 approve_return/approve_exchange 없음
