# Lazada 주문 수집 — 스텁

**구현 상태: 스텁** (상품 등록도 미구현)

---

## Lazada Open Platform API (구현 필요)

### 인증

- App Key + App Secret
- Access Token (OAuth 2.0)
- `Authorization: Bearer {access_token}`

### 주문 조회

- **엔드포인트:** `/orders/get`
- **파라미터:** `created_after`, `created_before`, `status`, `sort_by`
- **응답:** JSON

### 주문 상태

| Lazada 상태 | SambaOrder status | shipping_status |
|---|---|---|
| `pending` | `pending` | `결제완료` |
| `ready_to_ship` | `pending` | `발송대기` |
| `shipped` | `shipped` | `배송중` |
| `delivered` | `delivered` | `배송완료` |
| `canceled` | `cancelled` | `취소완료` |
| `returned` | `returned` | `반품완료` |

### 송장 입력

- **엔드포인트:** `/order/pack`
- **필드:** `shipping_provider`, `tracking_number`

### 취소/반품

- **취소:** `/order/cancel`
- **반품:** `/order/return/initiate`

---

## 구현 시 참고

- Lazada는 동남아시아 마켓 (SG, MY, TH, ID, PH, VN)
- 국가별 API 도메인 다름
- 통화: SGD, MYR, THB 등 현지 통화
- 상품명 영어/현지어 번역 필요
