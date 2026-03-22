# SSG(신세계몰) 주문 수집 — 미구현

소스: `backend/backend/domain/samba/proxy/ssg.py`

**구현 상태: 미구현** (상품 등록만 구현, 주문 API 없음)

---

## API 주문 엔드포인트 (구현 필요)

### 주문 조회

- **인증:** API Key
- **storeId:** 기본 "6004"
- **파라미터:** 기간, 상태 필터
- **응답:** JSON

### 주문 상태 종류

| SSG 상태 | SambaOrder status | shipping_status |
|---|---|---|
| 결제완료 | `pending` | `결제완료` |
| 상품준비 | `pending` | `발송대기` |
| 배송중 | `shipped` | `배송중` |
| 배송완료 | `delivered` | `배송완료` |
| 구매확정 | `delivered` | `구매확정` |
| 취소요청 | `cancel_requested` | `취소요청` |
| 취소완료 | `cancelled` | `취소완료` |
| 반품요청 | `return_requested` | `반품요청` |
| 반품완료 | `returned` | `반품완료` |

---

## 구현 시 참고

- `SSGClient`에 주문 메서드 추가
- `_parse_ssg_order()` 작성 필요
- SSG는 신세계/이마트 통합 플랫폼, storeId로 구분
