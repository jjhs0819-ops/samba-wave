---
name: 네이버 스마트스토어 API 분석 및 구현 계획
description: 네이버 커머스 API(스마트스토어) 상품등록 연동 - 인증방식, 엔드포인트, 필수파라미터, 접근권한 신청절차
type: project
---

## 네이버 커머스 API (스마트스토어) 현황

### API 포털
- 문서: https://apicenter.commerce.naver.com/docs/commerce-api/current
- SPA 구조라 직접 fetch 불가 — 브라우저 접속 필요
- API 호스트: https://api.commerce.naver.com

### 인증 방식: OAuth 2.0 (Client Credentials)
- 발급: 네이버 커머스 API 센터에서 Application 등록 → Client ID + Client Secret 발급
- 토큰 엔드포인트: POST https://api.commerce.naver.com/external/v1/oauth2/token
- 요청 방식: Authorization: Basic base64(clientId:clientSecret), Content-Type: application/x-www-form-urlencoded, grant_type=client_credentials
- 토큰 유효기간: 1시간 (3600초), 만료 전 갱신 필요
- 토큰 사용: Authorization: Bearer {access_token}

### 주요 API 엔드포인트 (상품)
- 상품 등록: POST /external/v1/products/origin-products
- 상품 조회(단건): GET /external/v1/products/origin-products/{originProductNo}
- 상품 수정: PUT /external/v1/products/origin-products/{originProductNo}
- 상품 삭제: DELETE /external/v1/products/origin-products/{originProductNo}
- 상품 목록 조회: GET /external/v1/products/origin-products
- 판매 상태 변경: PUT /external/v1/products/channel-products/{channelProductNo}/sale-status
- 카테고리 조회: GET /external/v1/categories/{categoryId}
- 카테고리 속성 조회: GET /external/v1/categories/{categoryId}/attributes

### Rate Limit
- 기본: 초당 10 req / 계정, 분당 100 req
- 대량 등록 시: 배치 50개 단위, 요청 간 100ms 이상 간격 권장

### 상품 등록 필수 파라미터 (originProduct)
```json
{
  "originProduct": {
    "statusType": "SALE",
    "saleType": "일반상품",
    "leafCategoryId": "카테고리ID(필수)",
    "name": "상품명(최대100자)",
    "detailContent": "상품 상세 HTML",
    "images": {
      "representativeImage": { "url": "대표이미지URL" },
      "optionalImages": [{ "url": "추가이미지URL" }]
    },
    "salePrice": 10000,
    "stockQuantity": 100,
    "deliveryInfo": {
      "deliveryType": "DELIVERY",
      "deliveryAttributeType": "NORMAL",
      "deliveryFee": {
        "deliveryFeeType": "FREE",
        "baseFee": 0
      },
      "returnDeliveryFee": 3000,
      "exchangeDeliveryFee": 3000
    },
    "returnExchangePolicy": {
      "returnFeeType": "PAID",
      "returnFee": 3000,
      "exchangeFeeType": "PAID",
      "exchangeFee": 3000
    }
  },
  "smartstoreChannelProduct": {
    "naverShoppingRegistration": true,
    "channelProductDisplayStatusType": "ON"
  }
}
```

### 옵션 상품 추가 파라미터
```json
{
  "optionInfo": {
    "optionCombinationGroupNames": {
      "optionGroupName1": "색상",
      "optionGroupName2": "사이즈"
    },
    "optionCombinations": [
      {
        "optionName1": "블랙",
        "optionName2": "M",
        "stockQuantity": 10,
        "price": 0,
        "usable": true
      }
    ]
  }
}
```

### API 접근 권한 신청 절차
1. 네이버 비즈니스 계정 생성 (필수)
2. 스마트스토어 센터 입점 (사업자등록증, 통신판매업신고증)
3. 네이버 커머스 API 센터 접속 (https://apicenter.commerce.naver.com)
4. 애플리케이션 등록 → Client ID / Client Secret 발급 (즉시)
5. 개발 테스트 후 운영 전환 (리뷰 없음, 자동 발급)
- 소요기간: 입점 완료 후 당일 발급 가능

### 삼바웨이브 구현 계획
- 모듈 위치: js/modules/smartstore-api.js (신규)
- proxy-server 경유: localhost:3001/api/smartstore/* (CORS 우회)
- ShipmentManager 연동: _transmitToSmartstore() 메서드 추가
- 계정 관리: AccountManager의 smartstore 항목 apiFields 확인 필요 (clientId, clientSecret)

**Why:** 스마트스토어는 국내 최대 오픈마켓으로 삼바웨이브 위탁판매 핵심 채널
**How to apply:** smartstore-api.js 구현 시 이 스펙을 기준으로 작업. proxy-server.mjs에 /api/smartstore/* 라우트 추가 필요
