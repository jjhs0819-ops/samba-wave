---
name: KREAM 소싱사이트 통합 현황
description: KREAM 소싱사이트의 파이프라인 연결 상태 및 발견된 단절 지점 이력
type: project
---

## KREAM 파이프라인 연결 상태 (2026-03-14 점검)

KREAM은 소싱처 + 판매처 이중 역할을 하는 리셀 플랫폼이다.

### 구현 완료된 부분
- `js/modules/collector.js`: `supportedSites` 배열에 `{ id: 'kream', name: 'KREAM', domain: 'kream.co.kr' }` 포함 (라인 22)
- `js/modules/collector.js`: `_isKreamUrl()`, `_extractKreamProductId()`, `_collectKreamSingle()`, `_collectKreamBulk()` 메서드 구현 완료
- `js/modules/kream.js`: `KreamManager` 클래스 - 소싱(검색/시세조회) + 판매(매도 입찰 등록/수정/취소) 기능 구현
- `js/app.js`: `SITE_LIST` 배열에 'KREAM' 포함 (라인 288)
- `js/app.js`: `MARKET_LIST`에도 'KREAM' 포함 (라인 284) - 판매처로도 활용
- `js/ui.js`: `apply-group-site-filter` 드롭다운은 `SITE_LIST`를 동적으로 채우므로 KREAM 자동 포함
- `js/ui.js`: 수집 탭 소싱사이트 카드는 `collectorManager.supportedSites`를 동적으로 순회하므로 KREAM 자동 포함
- `js/ui.js`: `showKreamSizePriceTable()` 메서드 구현 (사이즈별 시세 팝업)
- `js/ui.js`: KREAM 전용 kreamAsk/kreamBid/kreamLastSale 렌더링 로직 구현
- `proxy-server.mjs`: KREAM 수집 엔드포인트 (`/api/kream/products/:id`, `/api/kream/search`) 구현

### 발견 및 수정된 단절 지점
- `index.html` 라인 2095: `#product-source-site` select 옵션이 하드코딩되어 있었고 KREAM 누락
  - 수정: `<option value="KREAM">KREAM</option>` GSShop 뒤, LOTTEON 앞에 추가

### 구조적 취약점 (향후 주의)
- 상품관리 탭의 소싱사이트 필터(`#product-source-site`)는 `index.html`에 하드코딩되어 있음
- 신규 소싱사이트 추가 시 반드시 이 select에 option을 수동으로 추가해야 함
- 나머지 드롭다운들(apply-group-site-filter, 수집탭 카드)은 동적으로 생성되어 문제 없음

**Why:** KREAM은 `collector.js`와 `app.js`에는 올바르게 등록되어 있었으나, `index.html`의 하드코딩된 select 옵션에서만 누락되어 UI에 표시되지 않았다.

**How to apply:** 향후 소싱사이트 추가 시 `index.html`의 `#product-source-site` select를 반드시 함께 수정해야 함.
