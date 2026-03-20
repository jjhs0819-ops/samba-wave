# CS 처리 가이드 — 취소/반품/교환

---

## 현재 구현 현황

| CS 유형 | 스마트스토어 | 쿠팡 | 11번가 | 기타 |
|---------|-----------|------|--------|------|
| 취소승인 | `approve_cancel` 구현 | 미구현 | 미구현 | 미구현 |
| 반품승인 | 미구현 | 미구현 | 미구현 | 미구현 |
| 교환승인 | 미구현 | 미구현 | 미구현 | 미구현 |
| 클레임 감지 | 동기화 시 자동 | 미구현 | 미구현 | 미구현 |

---

## 취소 처리

### 전체 흐름

```
[1] 구매자가 마켓에서 취소 요청
         ↓
[2] 동기화 시 claimType="CANCEL" 감지
    → shipping_status = "취소요청"
    → status = "cancel_requested"
         ↓
[3] 관리자 확인
    → 재고/발송 상태 확인
         ↓
[4] 취소 승인 (POST /orders/{id}/approve-cancel)
    → {Market}Client.approve_cancel(order_number)
    → shipping_status = "취소완료"
    → status = "cancelled"
```

### 스마트스토어 취소승인 (구현됨)

```python
# order.py 라우터
@router.post("/{order_id}/approve-cancel")
async def approve_cancel(order_id: str):
    # 1. 주문 조회
    order = await service.get_order(order_id)
    # 2. 마켓 계정에서 인증정보 추출
    client = SmartStoreClient(client_id, client_secret)
    # 3. 스마트스토어 API 호출
    await client.approve_cancel(order.order_number)
    # 4. 상태 업데이트
    await service.update_order(order_id, {"shipping_status": "취소완료"})
```

### 쿠팡 취소승인 (구현 필요)

```
PATCH /v2/providers/seller_api/apis/api/v1/marketplace/
      seller-products/orders/cancellation/{receiptId}/approve
```

### 11번가 취소승인 (구현 필요)

```
PUT /rest/orderservices/order/{ordNo}/cancel/approve
```

---

## 반품 처리

### 전체 흐름

```
[1] 구매자가 마켓에서 반품 요청
         ↓
[2] 동기화 시 claimType="RETURN" 감지
    → shipping_status = "반품요청"
    → status = "return_requested"
         ↓
[3] 수거 진행
    → shipping_status = "수거중" → "수거완료"
         ↓
[4] 반품 승인 (현재 미구현)
    → {Market}Client.approve_return(order_number)
    → shipping_status = "반품완료"
    → status = "returned"
```

### 스마트스토어 반품승인 (구현 필요)

```
POST /v1/pay-order/seller/product-orders/{id}/claim/return/approve
```

### 쿠팡 반품승인 (구현 필요)

```
PATCH /v2/providers/seller_api/apis/api/v1/marketplace/
      seller-products/orders/returns/{receiptId}/approve
```

---

## 교환 처리

### 전체 흐름

```
[1] 구매자가 마켓에서 교환 요청
         ↓
[2] 동기화 시 claimType="EXCHANGE" 감지
    → shipping_status = "교환요청"
         ↓
[3] 교환 처리 (현재 미구현)
    → 새 상품 발송 + 기존 상품 수거
         ↓
[4] 교환 완료
    → shipping_status = "교환완료"
    → status = "delivered" (교환 완료 = 배송완료 취급)
```

---

## 프론트엔드 CS 관련 페이지

### orders/page.tsx — 주문 목록

- 취소/반품/교환 요청 건수 우측 상단 알림
- 상태별 색상 뱃지 (cancel_requested=노랑, return_requested=주황)
- `handleApproveCancel()` → `orderApi.approveCancel(id)`

### returns/page.tsx — 반품/교환 관리

- 유형: return(반품), exchange(교환), cancel(취소)
- 사유 11개 드롭다운 + 직접입력
- 승인/거절/완료/취소 버튼
- 거절 사유 입력 모달
- 타임라인 이력 (생성→승인→완료)
- 통계 카드 (전체/요청/승인/완료/거절/환불총액)

### cs/page.tsx — CS 관리 (빈 스텁)

- "CS 관리 기능 준비중입니다" 27줄 스텁
- 취소/반품/교환 통합 관리 UI 구현 필요

---

## 새 마켓 CS 구현 체크리스트

1. **프록시에 주문 조회 메서드 추가** — `get_orders(days)`
2. **프록시에 발주확인 메서드 추가** — `confirm_order(order_id)`
3. **프록시에 취소승인 메서드 추가** — `approve_cancel(order_id)`
4. **프록시에 반품승인 메서드 추가** — `approve_return(order_id)`
5. **라우터에 마켓 분기 추가** — `sync-from-markets`에서 해당 마켓 처리
6. **파서 함수 작성** — `_parse_{market}_order()` 매핑 함수
7. **상태 매핑 추가** — `status-mapping.md`에 해당 마켓 상태 추가
8. **취소승인 분기 추가** — `approve-cancel` 엔드포인트에서 source별 분기
9. **프론트엔드 마켓 필터 추가** — `orders/page.tsx` 마켓 드롭다운
10. **테스트** — eval 추가 + autoresearch

---

## 정산금액 계산 주의사항

### 계산식 불일치 (알려진 버그)

| 경로 | 계산식 | 비고 |
|------|--------|------|
| `service.create_order()` | `profit = revenue - cost` | shipping_fee **미차감** |
| `sync 업데이트` (라우터) | `profit = revenue - cost - shipping_fee` | shipping_fee **차감** (올바름) |

### 정산금액 결정 우선순위

1. **마켓 API의 정산금액** (`expectedSettlementAmount` 등) → 가장 정확
2. **역산:** `revenue = sale_price × (1 - fee_rate / 100)`
3. **수동 입력:** 관리자가 fee_rate 직접 설정
