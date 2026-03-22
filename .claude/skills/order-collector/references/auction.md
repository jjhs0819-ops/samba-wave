# 옥션 주문 수집 — 미지원

**구현 상태: 미지원** (공개 API 없음, 파트너 계약 또는 연동솔루션 필요)

---

## 현황

- 옥션은 eBay Korea 계열 (G마켓과 동일 그룹)
- ESM Plus (통합판매자센터)를 통해 G마켓과 함께 관리
- 공개 API가 없어 직접 연동 불가
- **대안:** 플레이오토, 사방넷 등 연동솔루션 경유

## G마켓과의 관계

- 옥션과 G마켓은 ESM Plus에서 통합 관리
- 연동솔루션 경유 시 동일한 API로 양쪽 주문 수집 가능
- `source` 필드로 "auction" / "gmarket" 구분

---

## UNSUPPORTED_MARKETS에 등록됨

`dispatcher.py`의 `UNSUPPORTED_MARKETS = ["gmarket", "auction", "homeand", "hmall"]`
