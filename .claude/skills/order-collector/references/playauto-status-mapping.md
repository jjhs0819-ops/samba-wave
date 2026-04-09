# 플레이오토 주문상태 매핑 가이드

## 핵심 원칙

사용자는 항상 **삼바웨이브 내부 상태명**(주문접수, 배송대기중 등)으로 대화한다.
플레이오토 원본 상태명(신규주문, 송장출력 등)은 코드 내부에서만 사용되며 사용자에게 노출되지 않는다.

사용자가 "주문접수"라고 말하면 코드에서는 `pending` + `new_order` + `invoice_printed` 모두를 의미할 수 있다.
**필터링/조건문 작성 시 반드시 이 매핑표를 확인**하여 누락되는 상태가 없는지 체크할 것.

---

## 상태 매핑표

### 1. status (내부 주문상태) — `_parse_playauto_order()` status_map

| 플레이오토 OrderState | → status (DB) | → UI 표시명 | 비고 |
|---|---|---|---|
| 신규주문 | `new_order` | 주문접수 | UI에서 pending과 동일 취급 |
| 송장출력 | `invoice_printed` | 주문접수 | UI에서 pending과 동일 취급 |
| 주문확인 | `pending` | 주문접수 | |
| 보류 | `pending` | 주문접수 | |
| 송장입력 | `processing` | - | |
| 출고 | `shipped` | - | |
| 배송중 | `shipped` | 배송중 | |
| 수취확인 | `delivered` | 배송완료 | |
| 정산완료 | `delivered` | 배송완료 | |
| 취소 | `cancelled` | 취소완료 | |
| 취소마감 | `cancelled` | 취소완료 | |
| 반품요청 | `return_requested` | 반품요청 | |
| 반품마감 | `returned` | 반품완료 | |
| 교환요청 | `exchange_requested` | 교환요청 | |
| 교환마감 | `exchanged` | 교환완료 | |

### 2. shipping_status (마켓상태 표시) — 인라인 매핑

| 플레이오토 OrderState | → shipping_status | 비고 |
|---|---|---|
| 신규주문 | 주문접수 | |
| 송장출력 | 배송대기중 | |
| 주문확인 | 취소중 | |
| 수취확인 | 배송완료 | |
| (기타) | OrderState 그대로 | 배송중, 출고 등 원문 유지 |

---

## UI 표시 그룹 — STATUS_MAP (프론트)

프론트엔드 `STATUS_MAP`에서 `new_order`와 `invoice_printed`는 드롭박스 옵션에서 **제외**된다.
따라서 이 두 상태의 주문은 드롭박스에 첫 번째 옵션인 "주문접수(pending)"로 표시된다.

### "주문접수" 필터 시 포함해야 할 status 값

```
['pending', 'new_order', 'invoice_printed']
```

이 세 값 모두 UI에서 "주문접수"로 보이므로, 필터/통계에서 "주문접수"를 언급하면 세 값 모두 포함해야 한다.

### "접수/대기/사무실" (active) 필터 포함 status 값

```
['new_order', 'invoice_printed', 'pending', 'wait_ship', 'arrived']
```

추가로 shipping_status가 CS 관련(취소중/취소요청/반품요청 등)이면 active에서 제외.

---

## 이행매출 대상 상태 (매출통계/대시보드)

```
['pending', 'wait_ship', 'arrived', 'shipping', 'delivered', 'exchanged']
```

이 6개 상태의 `sale_price` 합산 = 이행매출.
`new_order`, `invoice_printed`는 여기 포함되지 않음 (아직 주문 확인 전).

---

## 자주 발생하는 실수

1. **"주문접수" = `pending`만 매칭** → `new_order`, `invoice_printed` 누락
2. **"배송완료" = `delivered`만 매칭** → 플레이오토 "수취확인"이 `delivered`로 매핑되는 것 확인
3. **"취소" vs "취소완료"** → 플레이오토 "취소"/"취소마감" 둘 다 `cancelled`(취소완료)
4. **shipping_status 미매핑** → `status`는 매핑하고 `shipping_status`는 빠뜨리는 경우
5. **필터 vs 통계 불일치** → 필터에서는 보이는데 통계에서 안 잡히는 경우 (status 값 그룹 차이)

---

## 코드 위치

- `status` 매핑: `backend/api/v1/routers/samba/order.py` → `_parse_playauto_order()` 내 `status_map`
- `shipping_status` 매핑: 같은 함수 내 인라인 dict
- 프론트 STATUS_MAP: `frontend/src/app/samba/orders/page.tsx` 상단
- 프론트 필터 로직: 같은 파일 `filteredOrders` 내 `statusFilter` 분기
- 매출통계 상태 목록: `frontend/src/app/samba/analytics/page.tsx` → `ORDER_STATUSES`
- 대시보드 이행매출: `backend/api/v1/routers/samba/order.py` → `dashboard_stats()` 내 `FULFILLMENT_STATUSES`
