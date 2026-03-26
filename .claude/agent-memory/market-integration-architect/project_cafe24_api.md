---
name: Cafe24 API 분석
description: Cafe24 쇼핑몰 Admin REST API 인증, 상품등록, 카테고리, 이미지, 옵션/variants, Rate Limit 전체 정리
type: project
---

# Cafe24 Admin REST API 분석 (2026-03-26 기준)

**Why:** 삼바웨이브 상품 대량등록 시스템에서 Cafe24 마켓 연동 모듈 개발을 위한 API 사양 파악
**How to apply:** Cafe24 연동 모듈 구현 시 아래 스펙을 기준으로 개발

---

## 1. 인증 방식 (OAuth 2.0)

- **방식**: OAuth 2.0 Authorization Code Flow
- **적용 API**: Admin API (Full CRUD), Front API는 Basic Auth
- **토큰 유효기간**: Access Token 2시간, Refresh Token 2주
- **Scope 체계**:
  - `mall.read_product` - 상품 읽기
  - `mall.write_product` - 상품 쓰기/생성/수정/삭제
  - `mall.read_store` - 스토어 정보 읽기
  - `mall.write_store` - 스토어 정보 쓰기
- **토큰 갱신**: Refresh Token으로 Access Token 재발급 (만료 전 갱신 가능)
- **토큰 무효화**: 전용 엔드포인트로 revocation 지원
- **Base URL**: `https://{mallid}.cafe24api.com/api/v2/`

---

## 2. 상품 등록 API

### POST /api/v2/admin/products
- **Scope**: `mall.write_product`
- **Rate Limit**: 버킷 당 40회 (아래 Rate Limit 섹션 참조)
- **단일 호출 제한**: 1개 객체

#### 필수 파라미터
| 파라미터 | 타입 | 설명 |
|---------|------|------|
| product_name | String | 상품명 (최대 250자) |
| display | String | 전시 여부 T(전시)/F(미전시) |
| selling | String | 판매 여부 T(판매)/F(미판매) |

#### 주요 선택 파라미터
| 파라미터 | 타입 | 설명 |
|---------|------|------|
| shop_no | Integer | 쇼핑몰 번호 (기본값: 1, 멀티샵 지원) |
| custom_product_code | String | 사용자 정의 상품코드 (최대 40자) |
| eng_product_name | String | 영문 상품명 |
| product_condition | String | 상품 상태 (N:신상품, U:중고 등) |
| summary_description | String | 요약 설명 (255자 이내, HTML 가능) |
| price | Decimal | 판매가 |
| supply_price | Decimal | 공급가 |
| retail_price | Decimal | 정가(비교가) |
| description | Text | 상품 상세 설명 (HTML 가능) |
| has_option | String | 옵션 보유 여부 T/F |
| product_weight | Decimal | 상품 중량 |
| product_code | String | 시스템 자동 부여 상품 코드 |

#### 요청 예시
```json
POST https://{mallid}.cafe24api.com/api/v2/admin/products
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "shop_no": 1,
  "request": {
    "product_name": "테스트 상품",
    "display": "T",
    "selling": "T",
    "price": 29000,
    "supply_price": 15000,
    "description": "<p>상품 상세 설명</p>"
  }
}
```

#### 응답 예시 (201 Created)
```json
{
  "product": {
    "shop_no": 1,
    "product_no": 128,
    "product_code": "P00000AB",
    "product_name": "테스트 상품",
    "display": "T",
    "selling": "T",
    "price": "29000.00"
  }
}
```

### GET /api/v2/admin/products
- **Scope**: `mall.read_product`
- **페이지네이션**: limit(최대 100, 기본 10), offset(최대 8000)
- **특정 필드 조회**: fields 파라미터, embed 파라미터 (하위 리소스 포함)

### PUT /api/v2/admin/products/{product_no}
- **Scope**: `mall.write_product`
- product_no로 특정 상품 수정

### DELETE /api/v2/admin/products/{product_no}
- **Scope**: `mall.write_product`
- 상품 완전 삭제 (판매중지와 다른 개념)

---

## 3. 카테고리 API

### GET /api/v2/admin/categories
- 카테고리 목록 조회
- 파라미터: `shop_no` (기본값: 1)
- 응답: category_no, category_name, parent_category_no

### GET /api/v2/admin/categories/{category_no}
- 특정 카테고리 상세 조회

### POST /api/v2/admin/categories
- **Scope**: `mall.write_store`
- 카테고리 생성

### PUT /api/v2/admin/categories/{category_no}
- 카테고리 수정

### DELETE /api/v2/admin/categories/{category_no}
- 카테고리 삭제

### 상품-카테고리 연결 (별도 API)
```
POST /api/v2/admin/categories-products
```
- 상품을 카테고리에 추가하는 전용 엔드포인트
- 상품 생성 후 별도 호출 필요

### 관련 API
- `/api/v2/admin/categories/{category_no}/seo` - SEO 설정
- `/api/v2/admin/categories/{category_no}/decorationimages` - 카테고리 이미지
- `/api/v2/admin/categories/products` - 카테고리 내 상품 목록
- `/api/v2/admin/categories/properties` - 카테고리 표시 필드

---

## 4. 이미지 API

### POST /api/v2/admin/products/{product_no}/images
- **Scope**: `mall.write_product`
- 상품 메인/상세 이미지 업로드
- 업로드 방식: URL 기반 또는 Base64 인코딩 추정 (multipart 여부 미확인)

### POST /api/v2/admin/products/{product_no}/additionalimages
- 추가(서브) 이미지 생성/수정

### DELETE /api/v2/admin/products/{product_no}/images
- 상품 이미지 삭제

---

## 5. 옵션/Variants API

### 옵션 개념
- **옵션(Options)**: 색상, 사이즈 등 옵션명(option_name) + 옵션값(option_value)
- **품목(Variants)**: 옵션 조합으로 자동 생성되는 재고 단위 (SKU)
- 상품 생성 시 `has_option: T` 설정 후 옵션 별도 등록 → 자동으로 variants 생성

### Products Options API
```
GET  /api/v2/admin/products/{product_no}/options
POST /api/v2/admin/products/{product_no}/options
PUT  /api/v2/admin/products/{product_no}/options
DELETE /api/v2/admin/products/{product_no}/options
```

### Products Variants API
```
GET /api/v2/admin/products/{product_no}/variants
PUT /api/v2/admin/products/{product_no}/variants
PUT /api/v2/admin/products/{product_no}/variants/{variant_no}
```
- Variants는 조회와 수정만 가능 (생성은 옵션 등록 시 자동 생성)
- variant_code로 개별 SKU 관리

---

## 6. Rate Limit (호출 제한)

### Leaky Bucket 알고리즘
- **버킷 크기**: 40회 (엔드포인트별 동일)
- **소진율**: 초당 2회 감소 (2 requests/sec 기준 사용 시 제한 없음)
- **초당 동일 IP 동일 쇼핑몰**: 10회 초과 시 비정상 처리 가능
- **429 에러**: Too Many Requests (버킷 초과 시)

### 모니터링 헤더
| 헤더 | 설명 |
|------|------|
| `X-Api-Call-Limit` | 현재 사용량/버킷 크기 (e.g., `10/40`) |
| `X-RateLimit-Burst-Capacity` | 버킷 최대 크기 (40) |
| `X-RateLimit-Replenish-Rate` | 초당 감소율 (2) |
| `x-ratelimit-remaining` | 잔여 토큰 수 |

### 배치 처리 권장값
- 안전 호출 속도: 1~2회/초
- 버킷 40회 → 20초에 걸쳐 40회 호출 가능
- 429 수신 시 지수 백오프 후 재시도

---

## 7. API 버전 관리

- **버전 방식**: 날짜 기반 (`?version=2022-09-01` 쿼리 파라미터)
- **최신 버전**: 2024-12-01 (Front API 기준)
- **API Changelog**: https://developers.cafe24.com/api/changelog/front/list

---

## 8. 페이지네이션

- **방식**: offset 기반
- `limit`: 1~100, 기본 10
- `offset`: 최대 8000 (8,000개 이후 상품은 별도 방법 필요)
- **X-Pagination-Total-Count** 헤더로 전체 건수 확인

---

## 9. 멀티샵 지원

- `shop_no` 파라미터로 멀티샵(sub-mall) 구분
- 기본값: 1 (메인 쇼핑몰)

---

## 10. 접근 권한 획득

### 앱 개발자 계정 필요
1. https://developers.cafe24.com 에서 앱 개발자 가입
2. 앱 생성 → client_id, client_secret 발급
3. OAuth 2.0 redirect_uri 설정
4. 사용할 Scope 명시 (`mall.read_product`, `mall.write_product` 등)
5. 쇼핑몰 관리자가 앱 설치 → Authorization Code 발급 → Access/Refresh Token 교환

### 파트너 API (별도 계약)
- D.Collection API: 마케팅/프로모션 데이터 (파트너 계약 필요)
- Analytics API: 사용자 행동 분석 (Beta)

---

## 구현 관련 주의사항

1. 상품 생성 후 카테고리 연결은 `/api/v2/admin/categories-products` 별도 호출 필요
2. 이미지는 상품 생성 후 product_no를 받아 별도 업로드
3. 옵션 있는 상품: 상품 생성(has_option:T) → 옵션 POST → variants 자동 생성 순서
4. offset 최대 8000 제한으로 대량 조회 시 created_date 기반 커서 방식 병행 권장
5. API 버전 명시 안 하면 최신 버전 사용 (breaking change 주의)
