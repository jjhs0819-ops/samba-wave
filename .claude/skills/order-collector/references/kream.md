# KREAM 주문 수집 — 특수 구조

소스: `backend/backend/domain/samba/proxy/kream.py`

**구현 상태: 매도입찰만 구현** (일반 마켓과 주문 구조가 다름)

---

## KREAM 특수성

KREAM은 리셀 플랫폼으로 일반 마켓의 "주문" 개념과 다르다:
- **판매자** = 매도 입찰(ask) 등록
- **구매자** = 즉시 구매 또는 매수 입찰(bid)
- **체결** = 매도가와 매수가가 일치하면 거래 성사
- **검수** = KREAM이 상품 검수 후 구매자에게 배송

### 현재 구현된 메서드

| 메서드 | 동작 |
|--------|------|
| `create_ask(product_id, size, price, sale_type)` | 매도 입찰 등록 |
| `update_ask(ask_id, price)` | 매도가 변경 |
| `cancel_ask(ask_id)` | 매도 입찰 취소 |
| `get_my_asks()` | 내 매도 입찰 목록 |

### 주문(거래) 조회 — 미구현

- **체결 목록:** 거래가 성사된 건 조회 필요
- **검수 상태:** 검수중/검수완료/배송중/배송완료
- **정산:** 거래 수수료 차감 후 정산

### KREAM → SambaOrder 매핑 (구현 시)

| KREAM | SambaOrder | 비고 |
|---|---|---|
| 거래번호 | `order_number` | 체결 ID |
| 상품명 | `product_name` | 모델명 + 사이즈 |
| 체결가 | `sale_price` | 거래 성사 가격 |
| 수수료 | `fee_rate` | KREAM 수수료율 |
| 정산가 | `revenue` | 체결가 - 수수료 |
| 검수상태 | `shipping_status` | 검수중/배송중/완료 |

---

## 구현 시 참고

- KREAM은 token/cookie 기반 인증 (비공식 API)
- 거래 조회 API가 공식 제공되지 않아 웹 스크래핑 필요 가능
- 사이즈별 매도입찰이므로 options 단위로 주문이 생성됨
- `dispatcher.py`의 `_handle_kream`에서 사이즈별 `create_ask` 호출 패턴 참조
