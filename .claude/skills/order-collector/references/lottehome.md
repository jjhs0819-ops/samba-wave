# 롯데홈쇼핑 주문 수집 — 미구현

소스: `backend/backend/domain/samba/proxy/lottehome.py`

**구현 상태: 미구현** (상품/재고 관리만 구현, 주문 API 없음)

---

## API 주문 엔드포인트 (구현 필요)

### 인증

- userId/password 기반 인증
- agncNo (대행사번호) 필요
- env: "test" / "prod" 환경 구분

### 주문 조회

- **엔드포인트:** 주문 목록 조회 API
- **파라미터:** 기간, 상태
- **응답:** JSON

### 주문 상태 종류

| 상태코드 | 의미 | SambaOrder status |
|---|---|---|
| `01` | 결제완료 | `pending` |
| `02` | 발송완료 | `shipped` |
| `03` | 배송완료 | `delivered` |
| `04` | 구매확정 | `delivered` |
| `10` | 취소요청 | `cancel_requested` |
| `11` | 취소완료 | `cancelled` |
| `20` | 반품요청 | `return_requested` |
| `21` | 반품완료 | `returned` |

### 판매중지 (구현됨)

- `update_sale_status(product_no, "02")` — 판매중지 (MARKET_DELETE_HANDLERS에 등록)

---

## 구현 시 참고

- `LotteHomeClient`에 주문 메서드 추가
- 설정 키: `lottehome_credentials` 또는 `store_lottehome`
- 기존 `register_goods`, `update_sale_status` 패턴 참조
