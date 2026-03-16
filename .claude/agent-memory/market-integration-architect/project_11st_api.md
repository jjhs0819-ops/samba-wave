---
name: 11번가 셀러 Open API 연동
description: 11번가 API 인증방식, 엔드포인트, 구현 파일 위치 및 XML 상품등록 패턴
type: project
---

## API 기본 정보
- Base URL: `https://api.11st.co.kr`
- 인증: 요청 헤더 `openapikey: {API_KEY}` (API Key 방식, 서명 불필요)
- Content-Type: `application/xml;charset=UTF-8`
- Accept: `application/xml`
- 응답 형식: XML (proxy에서 raw text로 반환, 파싱 없음)

## 주요 엔드포인트
- `GET /rest/prodservices/category/list` — 인증 테스트용 (카테고리 조회)
- `POST /rest/prodservices/product` — 상품 등록 (XML body)
- `GET /rest/prodservices/product/{productCode}` — 상품 단건 조회
- `PUT /rest/prodservices/product/{productCode}` — 상품 수정 (XML body)
- `DELETE /rest/prodservices/product/{productCode}` — 상품 삭제

## 구현 파일 위치
- `js/modules/11st-api.js` — 브라우저측 래퍼 (`ElevenStApi` 클래스, 글로벌 `elevenStApi`)
- `proxy-server.mjs` — 11번가 라우트 (쿠팡 섹션 바로 앞에 삽입)
  - `POST /api/11st/test-auth`
  - `POST /api/11st/products`
  - `GET /api/11st/products/:productCode`
  - `PUT /api/11st/products/:productCode`
  - `DELETE /api/11st/products/:productCode`
- `js/ui.js` — `test11stAuth()`, `save11stSettings()`, `load11stSettings()` 함수
- `js/modules/analytics-ui.js` — `switchSettingsTab`에 11번가 분기 추가

## UI 설정 패널 (index.html)
- Panel ID: `stg-11st`
- 필드: `st-business-name`, `st-store-id`, `st-api-key`, `st-max-count`
- 제거됨: `st-account`, `st-password` (API Key만으로 인증)
- 연결 테스트: `id="st-auth-btn"` / `id="st-auth-status"` / `onclick="test11stAuth()"`
- 저장 버튼: `onclick="save11stSettings()"`

## MARKET_FIELD_MAP['11st'] 변경
- 이전: `sellerIdField: 'account'`, fields에 account/password 포함
- 이후: `sellerIdField: 'storeId'`, fields: `{ businessName, storeId, apiKey, maxCount }`

## XML 상품 등록 필수 필드
- `prdNm` (상품명, 최대 100자)
- `dispCtgrNo` (카테고리 코드)
- `sellerPrdCd` (셀러 상품코드)
- `prdStatCd` (상태: new/used)
- `selQty` (판매수량)
- `prdImage01` (대표 이미지 URL)
- `htmlDetail` (CDATA 상세 HTML)
- `selPrc` (판매가)
- `dlvFeeTypCd` (배송비 유형: 01=무료, 02=유료, 03=조건부무료)

**Why:** 11번가는 HMAC 서명 없이 API Key 헤더 하나로 동작하므로 쿠팡보다 단순. proxy에서 XML raw text 반환 후 브라우저에서 필요시 파싱.

**How to apply:** 11번가 상품 등록 시 `elevenStApi.mapProductToElevenStXml()`로 XML 생성 후 `registerProduct({ apiKey, xmlBody })` 호출.
