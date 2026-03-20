# G마켓 주문 수집 — 미지원

**구현 상태: 미지원** (공개 API 없음, 파트너 계약 또는 연동솔루션 필요)

---

## 현황

- G마켓은 eBay Korea 계열 (현 Gmarket Global)
- ESM Plus (통합판매자센터)를 통해 관리
- 공개 API가 없어 직접 연동 불가
- **대안:** 플레이오토, 사방넷 등 연동솔루션 경유

## 연동솔루션 경유 시

| 솔루션 | 방식 | 주문 수집 |
|--------|------|----------|
| 플레이오토 | API 중개 | 플레이오토 API로 G마켓 주문 조회 |
| 사방넷 | API 중개 | 사방넷 API로 G마켓 주문 조회 |
| 셀러허브 | 웹 UI | 수동 다운로드 (CSV/Excel) |

## SambaOrder 매핑 (연동솔루션 경유 시)

| 연동솔루션 필드 | SambaOrder |
|---|---|
| 주문번호 | `order_number` |
| 상품명 | `product_name` |
| 결제금액 | `sale_price` |
| 수수료 | `fee_rate` |
| 주문상태 | `status` + `shipping_status` |

---

## UNSUPPORTED_MARKETS에 등록됨

`dispatcher.py`의 `UNSUPPORTED_MARKETS = ["gmarket", "auction", "homeand", "hmall"]`
