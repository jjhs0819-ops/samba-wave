# Qoo10 주문 수집 — 스텁

**구현 상태: 스텁** (상품 등록도 미구현)

---

## Qoo10 API (구현 필요)

### 인증

- API Key 기반
- `api_key` 파라미터

### 주문 조회

- **엔드포인트:** `ShippingBasic.GetShippingInfo_v2`
- **파라미터:** `ShippingStat` (배송상태), 기간
- **응답:** XML 또는 JSON

### 주문 상태

| Qoo10 상태 | SambaOrder status | shipping_status |
|---|---|---|
| `1` (발송대기) | `pending` | `발송대기` |
| `2` (배송중) | `shipped` | `배송중` |
| `3` (배송완료) | `delivered` | `배송완료` |
| `4` (구매확정) | `delivered` | `구매확정` |
| `5` (취소) | `cancelled` | `취소완료` |
| `6` (반품) | `returned` | `반품완료` |

### 송장 입력

- **엔드포인트:** `ShippingBasic.SetSendingInfo`
- **필드:** 택배사코드, 송장번호

### 취소/반품

- **취소:** `ClaimBasic.SetCancelProcess`
- **반품:** `ClaimBasic.SetReturnProcess`

---

## 구현 시 참고

- Qoo10은 일본/싱가포르/말레이시아 등 아시아 마켓
- 큐텐재팬(Qoo10.jp) = 위시(Wish) 계열
- 통화: JPY, SGD 등
