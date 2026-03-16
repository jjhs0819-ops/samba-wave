---
name: 쿠팡 WING API 연동 구현 현황
description: 쿠팡 셀러 API(WING) 인증방식, 엔드포인트, 삼바웨이브 구현 파일 위치 및 주요 사항
type: project
---

## 구현 완료 (2026-03-15)

쿠팡 WING(셀러) API를 스마트스토어와 동일한 패턴으로 구현 완료.

### 인증 방식
- HMAC-SHA256 서명 방식 (OAuth 아님)
- `method + "\n" + datetime + "\n" + pathOnly + queryString` 메시지 서명
- datetime 형식: `yyMMddTHHmmssZ` (예: 260315T120000Z)
- Authorization 헤더: `CEA algorithm=HmacSHA256, access-key={accessKey}, signed-date={datetime}, signature={signature}`
- 자격증명 3종: `accessKey`, `secretKey`, `vendorId` (업체코드, 예: A00012345)
- 발급처: 쿠팡 WING (wing.coupang.com) > 판매자 정보 > API 관리

### API Base URL
- `https://api-gateway.coupang.com`

### 주요 엔드포인트
- 상품 등록: `POST /v2/providers/seller_api/apis/api/v1/marketplace/seller-products`
- 상품 목록: `GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products`
- 상품 단건: `GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}`
- 상품 수정: `PUT /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}`
- 상품 삭제: `DELETE /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}`
- 인증 테스트: `GET /v2/providers/seller_api/apis/api/v1/vendor` (벤더 정보 조회)

### 구현 파일 위치
- 브라우저 래퍼: `js/modules/coupang-api.js` (CoupangApi 클래스 + 글로벌 `coupangApi` 인스턴스)
- 프록시 라우트: `proxy-server.mjs` 3207번 줄 이후 (쿠팡 섹션)
- 설정 패널 HTML: `index.html` `id="stg-coupang"` 패널
- UI 함수: `js/ui.js` — `testCoupangAuth()`, `saveCoupangSettings()`, `loadCoupangSettings()`

### 프록시 라우트 (localhost:3001)
- `POST /api/coupang/test-auth` — 인증 테스트
- `POST /api/coupang/products` — 상품 등록
- `GET /api/coupang/products` — 목록 조회
- `GET /api/coupang/products/:sellerProductId` — 단건 조회
- `PUT /api/coupang/products/:sellerProductId` — 수정
- `DELETE /api/coupang/products/:sellerProductId` — 삭제

### 상품 등록 파라미터 주요 구조
```json
{
  "displayCategoryCode": 56137,
  "sellerProductName": "상품명",
  "vendorId": "A00012345",
  "deliveryChargeType": "FREE",
  "items": [
    {
      "itemName": "상품명",
      "originalPrice": 50000,
      "salePrice": 50000,
      "attributes": [{"attributeTypeName": "색상", "attributeValueName": "블랙"}],
      "images": [{"imageOrder": 0, "imageType": "REPRESENTATION", "vendorPath": "https://..."}],
      "stockQuantity": 999
    }
  ]
}
```

### settings 스토어 저장 키
- `coupang_credentials` — { account, vendorId, accessKey, secretKey, businessName, maxCount, storeId }

**Why:** 쿠팡은 스마트스토어와 달리 OAuth 토큰 없이 매 요청마다 HMAC 서명을 생성해야 함. 토큰 캐시 불필요.

**How to apply:** shipment-manager에서 쿠팡 전송 시 `coupangApi.mapProductToCoupangParams()` 후 `registerProduct()` 호출. `defaults`는 settings 스토어 `coupang_credentials` 및 카테고리 맵핑에서 가져옴.
