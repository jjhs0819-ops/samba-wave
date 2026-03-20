# 마켓별 주문상태 → SambaOrder 통합 매핑

---

## 내부 status 필드 (7종, 영문)

| status | 의미 | 대표 마켓 원본 상태 |
|--------|------|-------------------|
| `pending` | 결제 완료, 발송 전 | PAYED, ACCEPT, 결제완료, 102 |
| `shipped` | 발송됨 | DELIVERING, DEPARTURE, 배송중, 104 |
| `delivered` | 배송완료/구매확정 | DELIVERED, PURCHASE_DECIDED, EXCHANGED, 105, 106 |
| `cancelled` | 취소완료 | CANCELED, CANCEL_DONE, 202 |
| `returned` | 반품완료 | RETURNED, RETURN_DONE, 302 |
| `cancel_requested` | 취소요청 중 | CANCEL_REQUEST, CANCELING, 201 |
| `return_requested` | 반품요청 중 | RETURN_REQUEST, COLLECTING, 301 |

---

## shipping_status 필드 (한글, 프론트엔드 표시)

### 일반 주문 흐름
```
발주미확인 → 발송대기 → 배송중 → 배송완료 → 구매확정
```

### CS 흐름
```
취소요청 → 취소처리중 → 취소완료 (또는 취소거부)
반품요청 → 수거중 → 수거완료 → 반품완료 (또는 반품거부)
교환요청 → 교환처리중 → 교환완료 (또는 교환거부)
```

---

## 마켓별 상세 매핑

### 스마트스토어

| 원본 상태 | placeOrderStatus | status | shipping_status |
|---|---|---|---|
| `PAYED` | `NOT_YET` | `pending` | `발주미확인` |
| `PAYED` | `OK` | `pending` | `발송대기` |
| `DELIVERING` | - | `shipped` | `배송중` |
| `DELIVERED` | - | `delivered` | `배송완료` |
| `PURCHASE_DECIDED` | - | `delivered` | `구매확정` |
| `EXCHANGED` | - | `delivered` | `교환완료` |
| `CANCELED` | - | `cancelled` | `취소완료` |
| `CANCEL_DONE` | - | `cancelled` | `취소완료` |
| `RETURNED` | - | `returned` | `반품완료` |
| `RETURN_DONE` | - | `returned` | `반품완료` |

**클레임 상태 (claimType + claimStatus):**

| claimType | claimStatus | shipping_status | status |
|---|---|---|---|
| `CANCEL` | `CANCEL_REQUEST` | `취소요청` | `cancel_requested` |
| `CANCEL` | `CANCELING` | `취소처리중` | `cancel_requested` |
| `CANCEL` | `CANCEL_DONE` | `취소완료` | `cancelled` |
| `CANCEL` | `CANCEL_REJECT` | `취소거부` | `pending` |
| `RETURN` | `RETURN_REQUEST` | `반품요청` | `return_requested` |
| `RETURN` | `COLLECTING` | `수거중` | `return_requested` |
| `RETURN` | `COLLECT_DONE` | `수거완료` | `return_requested` |
| `RETURN` | `RETURN_DONE` | `반품완료` | `returned` |
| `RETURN` | `RETURN_REJECT` | `반품거부` | `pending` |
| `EXCHANGE` | `EXCHANGE_REQUEST` | `교환요청` | `pending` |
| `EXCHANGE` | `EXCHANGING` | `교환처리중` | `pending` |
| `EXCHANGE` | `EXCHANGE_DONE` | `교환완료` | `delivered` |
| `EXCHANGE` | `EXCHANGE_REJECT` | `교환거부` | `pending` |

### 쿠팡 (구현 시)

| 원본 상태 | status | shipping_status |
|---|---|---|
| `ACCEPT` | `pending` | `발송대기` |
| `INSTRUCT` | `pending` | `발송대기` |
| `DEPARTURE` | `shipped` | `배송중` |
| `DELIVERING` | `shipped` | `배송중` |
| `FINAL_DELIVERY` | `delivered` | `배송완료` |
| `NONE_TRACKING` | `shipped` | `배송중` |

### 11번가 (구현 시)

| 상태코드 | status | shipping_status |
|---|---|---|
| `102` | `pending` | `결제완료` |
| `103` | `pending` | `발송대기` |
| `104` | `shipped` | `배송중` |
| `105` | `delivered` | `배송완료` |
| `106` | `delivered` | `구매확정` |
| `201` | `cancel_requested` | `취소요청` |
| `202` | `cancelled` | `취소완료` |
| `301` | `return_requested` | `반품요청` |
| `302` | `returned` | `반품완료` |
| `401` | `pending` | `교환요청` |
| `402` | `delivered` | `교환완료` |

### Shopee (구현 시)

| 원본 상태 | status | shipping_status |
|---|---|---|
| `READY_TO_SHIP` | `pending` | `발송대기` |
| `SHIPPED` | `shipped` | `배송중` |
| `COMPLETED` | `delivered` | `배송완료` |
| `CANCELLED` | `cancelled` | `취소완료` |
| `IN_CANCEL` | `cancel_requested` | `취소요청` |
| `TO_RETURN` | `return_requested` | `반품요청` |

### Shopify (구현 시)

| financial + fulfillment | status | shipping_status |
|---|---|---|
| `paid` + `unfulfilled` | `pending` | `발송대기` |
| `paid` + `fulfilled` | `shipped` | `발송완료` |
| `paid` + `partial` | `pending` | `부분발송` |
| `refunded` | `cancelled` | `환불완료` |
| `voided` | `cancelled` | `취소완료` |

---

## 상태 전환 규칙

### status 변경 시 자동 처리 (service.py)

```python
if new_status == "shipped":
    shipped_at = datetime.now(UTC)    # 발송일 자동 기록

if new_status == "delivered":
    delivered_at = datetime.now(UTC)  # 배송완료일 자동 기록
```

### 클레임 우선순위

동기화 시 일반 상태와 클레임 상태가 동시에 존재하면:
- **클레임 상태가 우선 적용**
- 예: `productOrderStatus=DELIVERING` + `claimType=RETURN` → `shipping_status="반품요청"`
