# HMALL(현대홈쇼핑) 주문 수집 — 미지원

**구현 상태: 미지원** (공개 API 없음)

---

## 현황

- HMALL은 현대홈쇼핑 온라인몰
- 셀러 전용 API가 공개되어 있지 않음
- **대안:** 판매자센터 웹 UI에서 수동 관리 또는 연동솔루션 경유

## 연동솔루션 경유 시

- 플레이오토, 사방넷 등을 통해 주문 수집 가능
- CSV/Excel 다운로드 후 수동 업로드도 가능

---

## UNSUPPORTED_MARKETS에 등록됨

`dispatcher.py`의 `UNSUPPORTED_MARKETS = ["gmarket", "auction", "homeand", "hmall"]`
