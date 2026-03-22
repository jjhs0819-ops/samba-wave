# eBay 주문 수집 — 스텁

**구현 상태: 스텁** (상품 등록도 미구현)

---

## eBay Fulfillment API (구현 필요)

### 인증

- OAuth 2.0 (Client Credentials / Authorization Code Grant)
- `Authorization: Bearer {access_token}`

### 주문 조회

- **엔드포인트:** `GET /sell/fulfillment/v1/order`
- **파라미터:** `filter` (orderFulfillmentStatus, creationdate range)
- **응답:** JSON (`orders[]`)

### 주문 상태

| eBay 상태 | SambaOrder status | shipping_status |
|---|---|---|
| `NOT_STARTED` | `pending` | `결제완료` |
| `IN_PROGRESS` | `shipped` | `배송중` |
| `FULFILLED` | `delivered` | `배송완료` |
| `CANCELLED` | `cancelled` | `취소완료` |

### 송장 입력

- **엔드포인트:** `POST /sell/fulfillment/v1/order/{orderId}/shipping_fulfillment`
- **필드:** `trackingNumber`, `shippingCarrierCode`

### 취소/반품

- **취소:** `POST /sell/fulfillment/v1/order/{orderId}/cancel`
- **반품:** eBay Return API 별도

---

## 구현 시 참고

- eBay는 글로벌 플랫폼, 국가별 엔드포인트 다름
- 통화(USD, EUR 등) 변환 고려 필요
- 국제 배송 추적 번호 형식
