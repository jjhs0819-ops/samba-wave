# 서버 주도 수집 레시피 엔진 설계

**작성일**: 2026-05-03  
**목표**: 소싱처 구조 변경 시 확장앱 리로드 없이 서버 수정만으로 대응 가능하도록 전환

---

## 배경 및 문제

현재 소싱처 수집 로직(셀렉터, 클릭 순서, 데이터 파싱)이 `background-sourcing.js`에 하드코딩되어 있다. 소싱처가 DOM 구조를 변경할 때마다 JS 파일을 수정하고, 사용자들이 chrome://extensions에서 수동 리로드해야 한다.

경쟁사는 수집 로직을 서버에 두어 소싱처 변경 시 확장앱 리로드 없이 대응한다.

---

## 목표

- 소싱처 셀렉터/스텝 변경 → 서버 DB 수정만으로 반영 (확장앱 리로드 없음)
- KREAM (CDP 클릭 필요)은 기존 방식 유지
- 점진적 마이그레이션 (기존 코드와 공존 가능)

---

## 아키텍처

```
서버 DB (sourcing_recipes)
    ↓  GET /api/v1/samba/recipes
확장앱 recipe-cache.js (chrome.storage.local)
    ↓  레시피 실행 요청
확장앱 recipe-executor.js
    ↓  DOM 조작 (tabs API, scripting API)
소싱처 웹페이지
    ↓  수집 결과
서버 수집 결과 API
```

---

## 1. 레시피 포맷

```json
{
  "site": "musinsa",
  "version": "1.0.3",
  "steps": [
    { "type": "goto",    "url": "{{productUrl}}" },
    { "type": "wait",    "selector": ".goods_title", "timeout": 5000 },
    { "type": "extract", "fields": {
        "name":   { "selector": ".goods_title",     "attr": "text" },
        "price":  { "selector": ".price-original",  "attr": "text", "transform": "parseInt" },
        "images": { "selector": ".product-img img", "attr": "src",  "multiple": true }
    }},
    { "type": "click",   "selector": ".option_select" },
    { "type": "wait",    "selector": ".option_item" },
    { "type": "extract", "fields": {
        "options": { "selector": ".option_item", "attr": "text", "multiple": true }
    }}
  ]
}
```

### 스텝 타입 (v1 범위)

| type | 역할 | 주요 파라미터 |
|------|------|--------------|
| `goto` | URL 이동 | `url` (변수 `{{productUrl}}` 지원) |
| `wait` | 셀렉터 등장 대기 | `selector`, `timeout` (ms, 기본 5000) |
| `extract` | DOM 데이터 추출 | `fields`: `{key: {selector, attr, multiple, transform}}` |
| `click` | 요소 클릭 | `selector` |
| `scroll` | 스크롤 | `target`: `"bottom"` 또는 셀렉터 |
| `loop` | 셀렉터 목록 순회 | `selector`, `steps` (중첩 스텝) |
| `evaluate` | 페이지 내 JS 실행 | `expression` (window.__data 등 추출용) |

### `extract` 변환 옵션 (`transform`)

| 값 | 동작 |
|----|------|
| `parseInt` | 텍스트 → 정수 |
| `parseFloat` | 텍스트 → 부동소수 |
| `trim` | 공백 제거 |
| `removeComma` | 콤마 제거 후 parseInt |

---

## 2. 서버 DB

### `sourcing_recipes` 테이블

```sql
id          SERIAL PRIMARY KEY
site_name   VARCHAR(50) NOT NULL UNIQUE  -- 'musinsa', 'gsshop', 'abcmart'
version     VARCHAR(20) NOT NULL         -- semver '1.0.3'
steps       JSONB       NOT NULL         -- 레시피 스텝 배열
is_active   BOOLEAN     DEFAULT true
updated_at  TIMESTAMP   NOT NULL DEFAULT now()
```

---

## 3. 서버 API

### `GET /api/v1/samba/recipes`
전체 활성 레시피의 버전 목록만 반환 (확장앱 캐시 비교용, 용량 최소화)

**응답:**
```json
{
  "recipes": [
    { "site": "musinsa", "version": "1.0.3" },
    { "site": "gsshop",  "version": "1.1.0" }
  ]
}
```

### `GET /api/v1/samba/recipes/{site}`
특정 소싱처 레시피 풀 내용 반환

**응답:**
```json
{
  "site": "musinsa",
  "version": "1.0.3",
  "steps": [ ... ]
}
```

### `PUT /api/v1/samba/recipes/{site}`
레시피 수정 (관리자 전용, JWT 인증 필수)

---

## 4. 확장앱 구조 변경

### 신규 파일

**`extension/recipe-cache.js`**
- 서버에서 버전 목록 조회
- 로컬 캐시(chrome.storage.local)와 비교
- 변경된 사이트만 풀 레시피 다운로드 및 캐시 갱신
- 폴링 주기: 5분 (기존 `cookieSync` 알람과 동일)

**`extension/recipe-executor.js`**
- 레시피 스텝 순서대로 실행
- 각 스텝 타입별 핸들러 구현
- 변수 치환 (`{{productUrl}}` 등) 처리
- 결과 객체 누적 후 반환

### 수정 파일

**`extension/background-sourcing.js`**
- 소싱처별 하드코딩 로직 제거 (마이그레이션 완료 시)
- `executeRecipe(recipe, { productUrl })` 호출로 대체

**`extension/background.js`**
- `recipe-cache.js` import 추가
- 5분 주기 알람에 버전 체크 연결

**`extension/manifest.json`**
- `recipe-cache.js`, `recipe-executor.js` 백그라운드 import 추가

---

## 5. 마이그레이션 순서

| 단계 | 소싱처 | 우선 이유 |
|------|--------|---------|
| 1차 | 무신사, GSShop, ABCmart | 변경 빈도 높음, ROI 최대 |
| 2차 | 롯데ON, SSG, 나이키 | 중간 복잡도 |
| 3차 | 나머지 소싱처 | 점진적 전환 |
| 유지 | KREAM | CDP 클릭 필요, 기존 코드 유지 |

---

## 6. 비이행 범위

- KREAM: CDP(DevTools Protocol) 클릭 기반, 레시피 엔진으로 추상화 어려움 → 기존 유지
- 확장앱 엔진 자체(executor 버그 수정, 새 스텝 타입 추가): 드문 경우 리로드 여전히 필요

---

## 7. 확장앱 버전업 정책

레시피 엔진 도입 시 `manifest.json` 버전 bump 필수 (사용자 리로드 1회로 이후 리로드 불필요 상태 진입).
