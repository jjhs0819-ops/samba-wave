# 롯데ON 주문 수집 — 미구현

소스: `backend/backend/domain/samba/proxy/lotteon.py`

**구현 상태: 미구현** (상품 등록만 구현, 주문 API 없음)

---

## Open API 주문 엔드포인트 (구현 필요)

### 주문 조회

- **엔드포인트:** `GET /api/order/list`
- **인증:** API Key 헤더
- **파라미터:** `startDt`, `endDt`, `orderStatus`
- **응답:** JSON

### 주문 상태 종류

| 롯데ON 상태 | SambaOrder status | shipping_status |
|---|---|---|
| `10` (결제완료) | `pending` | `결제완료` |
| `20` (상품준비중) | `pending` | `발송대기` |
| `30` (배송중) | `shipped` | `배송중` |
| `40` (배송완료) | `delivered` | `배송완료` |
| `50` (구매확정) | `delivered` | `구매확정` |
| `60` (취소요청) | `cancel_requested` | `취소요청` |
| `70` (취소완료) | `cancelled` | `취소완료` |
| `80` (반품요청) | `return_requested` | `반품요청` |
| `90` (반품완료) | `returned` | `반품완료` |

### 발주확인 / 송장입력

- **발주확인:** `PUT /api/order/{orderNo}/accept`
- **송장입력:** `PUT /api/order/{orderNo}/invoice`
- **필드:** 택배사코드, 송장번호

### 취소/반품

- **취소 승인:** `PUT /api/order/{orderNo}/cancel/approve`
- **반품 승인:** `PUT /api/order/{orderNo}/return/approve`

---

## 구현 시 참고

- `LotteonClient`에 주문 메서드 추가
- `_parse_lotteon_order()` 작성 필요
- 거래처 정보(`tr_grp_cd`, `tr_no`)가 필요할 수 있음
- `test_auth()` 호출 시 자동 획득되는 거래처 정보 활용
