# 11번가 주문 수집 — 미구현

소스: `backend/backend/domain/samba/proxy/elevenst.py`

**구현 상태: 미구현** (상품 등록만 구현, 주문 API 없음)

---

## OpenAPI 주문 엔드포인트 (구현 필요)

### 주문 조회

- **엔드포인트:** `GET /rest/orderservices/order`
- **인증:** `openapikey` 헤더 (32자리 Open API Key)
- **파라미터:** `startDate`, `endDate`, `ordStatus`
- **응답:** XML

### 주문 상태 종류

| 11번가 상태코드 | 의미 | SambaOrder status | shipping_status |
|---|---|---|---|
| `101` | 결제대기 | - | - |
| `102` | 결제완료 | `pending` | `결제완료` |
| `103` | 배송지시 | `pending` | `발송대기` |
| `104` | 배송중 | `shipped` | `배송중` |
| `105` | 배송완료 | `delivered` | `배송완료` |
| `106` | 구매확정 | `delivered` | `구매확정` |
| `201` | 취소요청 | `cancel_requested` | `취소요청` |
| `202` | 취소완료 | `cancelled` | `취소완료` |
| `301` | 반품요청 | `return_requested` | `반품요청` |
| `302` | 반품완료 | `returned` | `반품완료` |
| `401` | 교환요청 | `pending` | `교환요청` |
| `402` | 교환완료 | `delivered` | `교환완료` |

### 발주확인

- **엔드포인트:** `PUT /rest/orderservices/order/{ordNo}/accept`
- **동작:** 주문 접수 확인

### 송장 입력

- **엔드포인트:** `PUT /rest/orderservices/order/{ordNo}/invoice`
- **XML Body:** `<dlvNo>`, `<dlvCmpCd>` (택배사코드)

### 취소/반품

- **취소 승인:** `PUT /rest/orderservices/order/{ordNo}/cancel/approve`
- **반품 승인:** `PUT /rest/orderservices/order/{ordNo}/return/approve`

---

## 구현 시 참고

- XML 응답 파싱 필요 (`_parse_xml` 기존 메서드 활용)
- `ElevenstClient`에 주문 메서드 추가
- 11번가 날짜 형식: `yyyyMMdd`
- 정산금액: `selPrc × quantity - dlvCst` 수동 계산 필요
