---
name: order-collector
description: >
  마켓 주문을 수집·동기화·처리하는 모든 작업에 사용.
  18개 마켓(스마트스토어/쿠팡/11번가/롯데ON/SSG/롯데홈쇼핑/GS샵/KREAM/eBay/Lazada/Shopee 등)의
  주문 데이터를 SambaOrder 30필드 스키마로 정규화하고 CS를 일원화 처리한다.
  포함 범위: 주문 동기화(sync-from-markets, _parse_{market}_order),
  발주확인(confirm_product_orders), 취소승인(approve_cancel),
  반품승인(approve_return), 교환 처리, 클레임 상태 감지(claimType/claimStatus),
  정산금액 계산(expectedSettlementAmount, fee_rate 역산),
  주문상태 매핑(PAYED→pending, DELIVERING→shipped, CANCEL_REQUEST→cancel_requested),
  송장번호 입력, 배송추적, 판매중지 연동.
  대상 파일: order.py(라우터), order/service.py, order/model.py, dtos/samba/order.py,
  smartstore.py·coupang.py·elevenst.py 등 각 프록시의 주문 메서드.
  제외: 상품 수집·파싱(→ product-parser), 상품 등록(→ product-upload), 대시보드 UI.
---

# Order Collector — 마켓 주문 수집 & CS 일원화

## 이 스킬의 목적

18개 판매 마켓에서 주문 데이터를 수집하여 **SambaOrder 통합 스키마**로 정규화하고,
취소/반품/교환 등 CS 처리를 일원화한다.

- **product-parser** = 소싱처 → CollectedProduct (수집 품질)
- **product-upload** = CollectedProduct → 마켓 등록 (등록 품질)
- **order-collector** = 마켓 주문 → SambaOrder (주문 수집 + CS 처리)

## 자기 진화 규칙

**사용자가 주문 관련 수정을 요구하면, 수정 내용을 이 스킬 파일에도 반영해야 한다.**
- 새 마켓 주문 수집 구현 → `references/{market}.md` 업데이트
- 주문 상태 매핑 변경 → `references/status-mapping.md` 업데이트
- CS 처리 로직 변경 → `references/cs-guide.md` 업데이트
- 에러 해결 → 해당 마켓 레퍼런스에 기록

---

## 주문 수집 파이프라인

`POST /api/v1/samba/orders/sync-from-markets` 호출 시 동작하는 전체 흐름:

```
[1] 활성 마켓 계정 조회
    → SambaMarketAccountRepository.list_active()
    → 특정 account_id가 있으면 해당 계정만, 없으면 전체

[2] 마켓별 주문 API 호출
    → market_type에 따라 분기 (현재 smartstore만 구현)
    → {Market}Client.get_orders(days) 호출

[3] 발주확인 자동 처리
    → 발주 미확인(PAYED + NOT_YET) 주문 감지
    → confirm_product_orders() 자동 호출

[4] 마켓 응답 → SambaOrder 정규화
    → _parse_{market}_order() 함수
    → 마켓별 필드를 SambaOrder 30개 필드로 매핑

[5] 클레임(CS) 상태 감지
    → claimType/claimStatus 필드 읽기
    → 취소요청/반품요청/교환요청 등 자동 반영

[6] 중복 확인 + 저장
    → order_number 기준 중복 체크
    → 기존 주문: 가격/상태/이미지 업데이트
    → 신규 주문: create_order로 생성

[7] 정산금액 계산
    → revenue = expectedSettlementAmount (API) 또는 sale_price × (1 - fee_rate/100)
    → profit = revenue - cost - shipping_fee
```

---

## SambaOrder 통합 스키마 (30필드)

소스: `backend/backend/domain/samba/order/model.py`

### 식별 정보

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | str (PK) | `ord_{ULID}` |
| `order_number` | str (indexed) | 주문번호 (마켓 productOrderId) |
| `channel_id` | str | 마켓 계정 ID |
| `channel_name` | str | 마켓 계정 표시명 |
| `shipment_id` | str | 마켓 orderId (묶음 주문번호) |

### 상품 정보

| 필드 | 타입 | 설명 |
|------|------|------|
| `product_id` | str | 마켓 상품번호 |
| `product_name` | str | 상품명 |
| `product_image` | str | 상품 이미지 URL |
| `source_site` | str | 소싱처 (MUSINSA, KREAM 등) |

### 고객 정보

| 필드 | 타입 | 설명 |
|------|------|------|
| `customer_name` | str | 주문자/수취인 이름 |
| `customer_phone` | str | 연락처 |
| `customer_address` | str | 배송지 주소 |

### 금액

| 필드 | 타입 | 설명 |
|------|------|------|
| `quantity` | int | 수량 (기본 1) |
| `sale_price` | float | 판매가 |
| `cost` | float | 원가 (소싱 가격) |
| `shipping_fee` | float | 배송비 |
| `fee_rate` | float | 수수료율 (%) |
| `revenue` | float | 정산금액 |
| `profit` | float | 수익 |
| `profit_rate` | str | 수익률 (%) |

### 상태

| 필드 | 타입 | 설명 |
|------|------|------|
| `status` | str (indexed) | 내부 상태 (pending/shipped/delivered/cancelled/returned/cancel_requested/return_requested) |
| `payment_status` | str | 결제 상태 (기본 "completed") |
| `shipping_status` | str | 마켓 주문상태 한글 (발주미확인/발송대기/배송중 등) |
| `return_status` | str | 반품 상태 (현재 미사용, shipping_status로 대체) |

### 배송

| 필드 | 타입 | 설명 |
|------|------|------|
| `shipping_company` | str | 택배사 |
| `tracking_number` | str | 송장번호 |
| `source` | str | 출처 마켓 (예: "smartstore") |

### 메타

| 필드 | 타입 | 설명 |
|------|------|------|
| `notes` | str | 메모 |
| `created_at` | datetime | 주문 생성일 |
| `updated_at` | datetime | 수정일 |
| `shipped_at` | datetime | 발송일 |
| `delivered_at` | datetime | 배송완료일 |

---

## 주문 상태 통합 매핑

상세는 `references/status-mapping.md` 참조.

### 내부 status (7종)

| status | 의미 | 매핑 조건 |
|--------|------|----------|
| `pending` | 결제 완료, 발송 전 | PAYED, CANCEL_REQUESTED 포함 |
| `shipped` | 발송됨 | DELIVERING |
| `delivered` | 배송완료 | DELIVERED, PURCHASE_DECIDED, EXCHANGED |
| `cancelled` | 취소완료 | CANCELED, CANCEL_DONE |
| `returned` | 반품완료 | RETURNED, RETURN_DONE |
| `cancel_requested` | 취소요청 중 | CANCEL_REQUEST, CANCELING |
| `return_requested` | 반품요청 중 | RETURN_REQUEST, COLLECTING, COLLECT_DONE |

### shipping_status (한글, 프론트엔드 표시용)

```
발주미확인 → 발송대기 → 배송중 → 배송완료 → 구매확정
                                      ↗ 취소요청 → 취소완료
                                      ↗ 반품요청 → 수거중 → 수거완료 → 반품완료
                                      ↗ 교환요청 → 교환처리중 → 교환완료
```

---

## 마켓 구현 현황 (18개)

### 주문 수집 구현 완료 (1개)

| 마켓 | 코드 | 주문조회 | 발주확인 | 취소승인 | 레퍼런스 |
|------|------|---------|---------|---------|---------|
| 스마트스토어 | `smartstore` | `get_orders` | `confirm_product_orders` | `approve_cancel` | → `references/smartstore.md` |

### 상품 등록 구현됨, 주문 미구현 (7개)

| 마켓 | 코드 | 상태 | 레퍼런스 |
|------|------|------|---------|
| 쿠팡 | `coupang` | 주문 API 미구현 | → `references/coupang.md` |
| 11번가 | `11st` | 주문 API 미구현 | → `references/elevenst.md` |
| 롯데ON | `lotteon` | 주문 API 미구현 | → `references/lotteon.md` |
| SSG(신세계) | `ssg` | 주문 API 미구현 | → `references/ssg.md` |
| 롯데홈쇼핑 | `lottehome` | 주문 API 미구현 | → `references/lottehome.md` |
| GS샵 | `gsshop` | 주문 API 미구현 | → `references/gsshop.md` |
| KREAM | `kream` | 매도입찰만 (주문 구조 다름) | → `references/kream.md` |

### 스텁 (6개, 상품 등록도 미구현)

| 마켓 | 코드 | 레퍼런스 |
|------|------|---------|
| eBay | `ebay` | → `references/ebay.md` |
| Lazada | `lazada` | → `references/lazada.md` |
| Qoo10 | `qoo10` | → `references/qoo10.md` |
| Shopee | `shopee` | → `references/shopee.md` |
| Shopify | `shopify` | → `references/shopify.md` |
| Zum(줌) | `zoom` | → `references/zoom.md` |

### 미지원 (4개, 공개 API 없음)

| 마켓 | 코드 | 레퍼런스 |
|------|------|---------|
| G마켓 | `gmarket` | → `references/gmarket.md` |
| 옥션 | `auction` | → `references/auction.md` |
| 홈앤쇼핑 | `homeand` | → `references/homeand.md` |
| HMALL | `hmall` | → `references/hmall.md` |

---

## CS 처리 체계

상세는 `references/cs-guide.md` 참조.

### 취소 처리 흐름

```
[1] 동기화 시 claimType="CANCEL" 감지
    → shipping_status = "취소요청"
    → status = "cancel_requested"

[2] 관리자가 취소승인 (POST /orders/{id}/approve-cancel)
    → {Market}Client.approve_cancel(order_number)
    → shipping_status = "취소완료"
    → status = "cancelled"
```

### 반품 처리 흐름

```
[1] 동기화 시 claimType="RETURN" 감지
    → shipping_status = "반품요청" / "수거중" / "수거완료"
    → status = "return_requested"

[2] 반품 완료 감지
    → shipping_status = "반품완료"
    → status = "returned"
```

### 교환 처리 흐름

```
[1] 동기화 시 claimType="EXCHANGE" 감지
    → shipping_status = "교환요청" / "교환처리중"

[2] 교환 완료 감지
    → shipping_status = "교환완료"
    → status = "delivered" (교환 완료 = 배송완료 취급)
```

---

## 주문 품질 체크리스트 (20항목, 100점 만점)

`_parse_{market}_order()` 출력 1건에 대해 채점.

### A. 필수필드 (5항목)

| # | 항목 | 검증 |
|---|------|------|
| A1 | `order_number` 비어있지 않은가 | 마켓 주문번호 필수 |
| A2 | `product_name` 비어있지 않은가 | 상품명 필수 |
| A3 | `sale_price > 0`인가 | 판매가 필수 |
| A4 | `channel_id` 비어있지 않은가 | 마켓 계정 식별 필수 |
| A5 | `source` 비어있지 않은가 | 출처 마켓 식별 필수 |

### B. 고객/배송 정보 (4항목)

| # | 항목 | 검증 |
|---|------|------|
| B1 | `customer_name` 비어있지 않은가 | 수취인명 |
| B2 | `customer_phone` 비어있지 않은가 | 연락처 |
| B3 | `customer_address` 비어있지 않은가 | 배송지 |
| B4 | `quantity >= 1`인가 | 수량 |

### C. 금액 정합성 (4항목)

| # | 항목 | 검증 |
|---|------|------|
| C1 | `revenue`가 계산되었는가 | `> 0` 또는 API 정산금액 |
| C2 | `fee_rate`가 합리적 범위인가 | `0 <= fee_rate <= 50` |
| C3 | `profit` = `revenue - cost - shipping_fee`인가 | 계산 정합성 |
| C4 | `profit_rate`가 문자열 %인가 | 형식 검증 |

### D. 상태 정합성 (4항목)

| # | 항목 | 검증 |
|---|------|------|
| D1 | `status`가 7종 중 하나인가 | pending/shipped/delivered/cancelled/returned/cancel_requested/return_requested |
| D2 | `shipping_status`가 비어있지 않은가 | 한글 상태 필수 |
| D3 | 클레임 존재 시 상태 반영되었는가 | claimType → status 매핑 |
| D4 | `shipped_at`이 shipped 상태일 때 설정되었는가 | 시간 정합성 |

### E. 마켓 호환 (3항목)

| # | 항목 | 검증 |
|---|------|------|
| E1 | `shipment_id`(orderId)가 존재하는가 | 묶음 주문 추적 |
| E2 | `product_id`가 마켓 상품번호인가 | 마켓 연동 추적 |
| E3 | `product_image` URL이 유효한가 | 이미지 표시용 |

```
점수 계산: score = (통과항목수 / 20) × 100

해석:
  95~100%  → 정상 동기화 가능
  80~94%   → 고객정보 또는 금액 누락
  60~79%   → 필수필드 또는 상태 매핑 오류
  < 60%    → parse 함수 기본 동작 불량
```

---

## 트러블슈팅 의사결정 트리

### 주문이 안 들어올 때

```
주문 동기화 후 0건
├─ 해당 마켓이 구현되었는가?
│  └─ NO → 현재 스마트스토어만 구현. references/{market}.md 참조
├─ API 인증 성공했는가?
│  └─ NO → 계정의 clientId/clientSecret 확인
│     └─ 계정 객체 우선 → samba_settings 테이블 폴백
├─ days 파라미터가 충분한가?
│  └─ 기본 7일, 최대 89일 (스마트스토어 90일 제한)
├─ 주문 상태 필터가 걸려있는가?
│  └─ order_status 파라미터 확인
└─ 이미 동기화된 주문인가?
   └─ order_number 기준 중복 → 업데이트만 수행 (신규 생성 안 함)
```

### CS 상태가 안 바뀔 때

```
취소요청인데 shipping_status가 안 바뀜
├─ 동기화를 실행했는가?
│  └─ CS 상태는 동기화 시에만 반영됨 (실시간 아님)
├─ claimType/claimStatus가 API 응답에 있는가?
│  └─ _parse_smartstore_order의 클레임 매핑 확인
├─ 취소승인 API를 호출했는가?
│  └─ POST /orders/{id}/approve-cancel
│     └─ 현재 스마트스토어만 지원
└─ 반품/교환 승인은?
   └─ 현재 API 엔드포인트 없음 (미구현)
```

### 정산금액이 맞지 않을 때

```
profit 계산 불일치
├─ create_order와 sync의 계산식이 다르다 (알려진 버그)
│  └─ create_order: profit = revenue - cost (shipping_fee 미차감)
│  └─ sync 업데이트: profit = revenue - cost - shipping_fee (올바름)
├─ fee_rate 역산이 정확한가?
│  └─ fee_rate = (1 - expectedSettlement / sale_price) × 100
│  └─ sale_price가 0이면 division by zero
└─ expectedSettlementAmount가 API에서 오는가?
   └─ 없으면 sale_price × (1 - fee_rate/100)으로 계산
```

---

## 실전 함정

### 1. 발주확인 자동 처리의 부작용

동기화 시 `PAYED + NOT_YET` 주문이 자동으로 발주확인 된다. 재고가 없는 상품도 자동 발주확인되므로, **품절 상품의 주문을 취소하지 못하고 발주확인해버리는 문제**가 있다. 발주확인 전에 재고 확인 로직이 없다.

### 2. order_number의 이중 사용

`order_number`는 수동 생성 시 `YYMMDDHHmm + 3자리 랜덤`이고, 동기화 시 `productOrderId`로 대체된다. 동일 필드에 형식이 다른 값이 들어가므로 검색/정렬 시 주의.

### 3. profit 계산 불일치 (알려진 버그)

`create_order()`는 `profit = revenue - cost`로 shipping_fee를 빼지 않지만, 동기화 업데이트는 `profit = revenue - cost - shipping_fee`로 계산한다. 수동 생성 주문과 동기화 주문의 profit이 다르게 계산된다.

### 4. return_status 필드의 사장

모델에 `return_status` 필드가 있지만, 실제로는 `shipping_status`(한글)로 반품/교환 상태를 관리한다. `return_status`는 사실상 사용되지 않는다.

### 5. 클레임 상태 우선순위

동기화 시 일반 주문상태와 클레임 상태가 동시에 존재하면, **클레임 상태가 우선 적용**된다. 예: 주문이 DELIVERING(배송중)이지만 claimType=RETURN이면 "반품요청"으로 표시된다.

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/orders` | 주문 목록 (skip, limit, status 필터) |
| `GET` | `/orders/search?q=` | 검색 (주문번호, 고객명, 전화번호, 상품명) |
| `GET` | `/orders/{id}` | 단건 조회 |
| `POST` | `/orders` | 수동 생성 |
| `PUT` | `/orders/{id}` | 수정 |
| `PUT` | `/orders/{id}/status` | 상태 변경 |
| `DELETE` | `/orders/{id}` | 삭제 |
| `POST` | `/orders/{id}/approve-cancel` | 취소승인 (스마트스토어만) |
| `POST` | `/orders/sync-from-markets` | 마켓 주문 동기화 |

---

## 주요 참조 파일

| 파일 | 역할 |
|------|------|
| `backend/.../api/v1/routers/samba/order.py` | 주문 라우터 (동기화, 취소승인) |
| `backend/.../domain/samba/order/model.py` | SambaOrder 모델 |
| `backend/.../domain/samba/order/service.py` | 주문 CRUD + 상태 변경 |
| `backend/.../dtos/samba/order.py` | 주문 DTO |
| `backend/.../proxy/smartstore.py` | 스마트스토어 주문 API |
| `frontend/.../orders/page.tsx` | 주문 프론트엔드 |
| `frontend/.../returns/page.tsx` | 반품/교환 프론트엔드 |

---

## 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-03-20 | 초안 작성. 스마트스토어 기준 파이프라인 + 20항목 체크리스트 + 18개 마켓 레퍼런스 |
| 2026-03-20 | 벤치마크 실행 (eval-2 취소승인에서 with_skill 우위 확인). description 최적화 — 마켓명 + 상태코드 키워드 추가 |
