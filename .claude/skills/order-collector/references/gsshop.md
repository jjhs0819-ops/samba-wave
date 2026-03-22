# GS샵 주문 수집 — 미구현

소스: `backend/backend/domain/samba/proxy/gsshop.py`

**구현 상태: 미구현** (상품/프로모션 관리만 구현, 주문 API 없음)

---

## API 주문 엔드포인트 (구현 필요)

### 인증

- supCd (공급사코드) + aesKey (AES 암호키)
- subSupCd (부공급사코드)
- env: "dev" / "prod" 환경 구분

### 주문 조회

- **파라미터:** 기간, 상태
- **응답:** JSON

### 주문 상태 종류

| 상태 | SambaOrder status | shipping_status |
|---|---|---|
| 결제완료 | `pending` | `결제완료` |
| 상품준비 | `pending` | `발송대기` |
| 배송중 | `shipped` | `배송중` |
| 배송완료 | `delivered` | `배송완료` |
| 취소요청 | `cancel_requested` | `취소요청` |
| 취소완료 | `cancelled` | `취소완료` |
| 반품요청 | `return_requested` | `반품요청` |
| 반품완료 | `returned` | `반품완료` |

### 판매중지 (구현됨)

- `update_sale_status(product_no, "02")` — 판매중지 (MARKET_DELETE_HANDLERS에 등록)

---

## 구현 시 참고

- `GsShopClient`에 주문 메서드 추가
- 설정 키: `gsshop_credentials` 또는 `store_gsshop`
- MDID(담당MD) 조회 등 기초정보 API 활용 가능
