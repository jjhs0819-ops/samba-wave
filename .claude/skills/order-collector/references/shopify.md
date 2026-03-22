# Shopify 주문 수집 — 스텁

**구현 상태: 스텁** (상품 등록도 미구현)

---

## Shopify Admin API (구현 필요)

### 인증

- API Key + Password (Private App) 또는
- Access Token (OAuth Custom App)
- `X-Shopify-Access-Token: {token}`

### 주문 조회

- **엔드포인트:** `GET /admin/api/2024-01/orders.json`
- **파라미터:** `created_at_min`, `created_at_max`, `status`, `financial_status`, `fulfillment_status`
- **응답:** JSON (`orders[]`)

### 주문 상태

| Shopify 상태 | SambaOrder status | shipping_status |
|---|---|---|
| `open` + `unfulfilled` | `pending` | `결제완료` |
| `open` + `partial` | `pending` | `부분발송` |
| `open` + `fulfilled` | `shipped` | `배송중` |
| `closed` | `delivered` | `배송완료` |
| `cancelled` | `cancelled` | `취소완료` |

| fulfillment_status | shipping_status |
|---|---|
| `unfulfilled` | `발송대기` |
| `fulfilled` | `발송완료` |
| `partial` | `부분발송` |
| `restocked` | `반품완료` |

### 송장 입력

- **엔드포인트:** `POST /admin/api/2024-01/orders/{id}/fulfillments.json`
- **필드:** `tracking_number`, `tracking_company`, `tracking_url`

### 취소/환불

- **취소:** `POST /admin/api/2024-01/orders/{id}/cancel.json`
- **환불:** `POST /admin/api/2024-01/orders/{id}/refunds.json`

---

## 구현 시 참고

- Shopify는 자사몰 플랫폼 (마켓플레이스가 아님)
- GraphQL Admin API도 사용 가능 (REST 대안)
- 통화: 스토어 설정에 따라 다양
- Webhook으로 실시간 주문 수신 가능 (`orders/create`, `orders/updated`)
