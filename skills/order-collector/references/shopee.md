# Shopee 주문 수집 — 스텁

**구현 상태: 스텁** (상품 등록도 미구현)

---

## Shopee Open Platform API (구현 필요)

### 인증

- Partner ID + Partner Key
- Shop ID + Access Token
- HMAC-SHA256 서명

### 주문 조회

- **엔드포인트:** `/api/v2/order/get_order_list`
- **파라미터:** `time_range_field`, `time_from`, `time_to`, `order_status`
- **응답:** JSON (`order_list[]`)

### 주문 상태

| Shopee 상태 | SambaOrder status | shipping_status |
|---|---|---|
| `READY_TO_SHIP` | `pending` | `발송대기` |
| `SHIPPED` | `shipped` | `배송중` |
| `COMPLETED` | `delivered` | `배송완료` |
| `CANCELLED` | `cancelled` | `취소완료` |
| `IN_CANCEL` | `cancel_requested` | `취소요청` |
| `TO_RETURN` | `return_requested` | `반품요청` |

### 송장 입력

- **엔드포인트:** `/api/v2/logistics/ship_order`
- **필드:** `tracking_number`

### 취소/반품

- **취소 응답:** `/api/v2/order/handle_buyer_cancellation` (accept/reject)
- **반품 응답:** `/api/v2/returns/confirm` (accept/reject)

---

## 구현 시 참고

- Shopee는 동남아시아 최대 마켓 (SG, MY, TH, ID, PH, VN, TW, BR, MX)
- 국가별 도메인 분리
- SIP(Shopee International Platform) 활용 시 글로벌 계정 통합 가능
- 통화: 현지 통화
