---
name: KREAM 소싱사이트 통합 현황
description: KREAM(kream.co.kr) 크롤링 아키텍처, API 엔드포인트, 데이터 구조 분석 결과
type: project
---

KREAM은 이미 proxy-server.mjs에 REST API 기반 수집이 구현되어 있으며, kream.js(판매 관리)와 collector.js(수집 통합)에도 연결되어 있음.

**Why:** KREAM은 리셀 플랫폼이므로 일반 소싱사이트와 달리 "즉시구매가(ask)/즉시판매가(bid)/최근거래가(last_sale)" 3가지 가격 지표가 핵심이고, 일반 쇼핑몰처럼 정가 → 할인가 구조가 아님.

**How to apply:** 신규 Puppeteer 크롤러 작성 시 아래 분석 내용을 참조하여 기존 구조와 충돌 없이 보완할 것.

## 현재 구현 상태

### 기존 API 방식 (proxy-server.mjs, 2142~2548줄)
- **상품 검색**: `GET https://api.kream.co.kr/api/screens/search/products?keyword=...&per_page=...&page=1`
- **상품 상세**: `GET https://kream.co.kr/api/products/{id}`
- **사이즈별 시세**: `GET https://kream.co.kr/api/products/{id}/prices`
- **로그인**: `POST https://kream.co.kr/api/session` (Bearer 토큰 방식)
- **내 입찰**: `GET https://kream.co.kr/api/asks/me`

### 인증 방식
- Bearer 토큰 (kream.co.kr API 세션에서 access_token 추출)
- 토큰 파일 캐시: `.kream-token.json`
- 비인증으로도 상품 검색/상세 조회는 가능 (시세 API는 인증 필요할 수 있음)

### KREAM 데이터 구조 (transformKreamToProduct 기준)
```
item.id / item.product_id           → siteProductId
item.name / item.translated_name    → name
item.brand?.name / item.brand_name  → brand
item.thumbnail_url / item.image_url → images[0]
item.retail_price                   → originalPrice
item.style_code / item.model_no     → styleCode
item.sizes / item.product_options   → options 배열
  sizes[].size / .name / .option_name → 사이즈명
  sizes[].ask / .immediate_buy_price  → kreamAsk (즉시구매가)
  sizes[].bid / .immediate_sell_price → kreamBid (즉시판매가)
  sizes[].last_sale_price             → kreamLastSale
  sizes[].is_sold_out                 → isSoldOut
item.trade_count / .total_trades    → tradeVolume
item.wish_count / .wishlist_count   → wishCount
item.release_date                   → kreamData.releaseDate
```

## KREAM 사이트 구조 분석

### URL 패턴
- 홈: `https://kream.co.kr`
- 검색: `https://kream.co.kr/search?keyword={keyword}`
- 상품 상세: `https://kream.co.kr/products/{productId}` (숫자 ID)
- 브랜드 페이지: `https://kream.co.kr/brands/{brandSlug}`
- 카테고리: `https://kream.co.kr/category/{categoryId}`

### 프론트엔드 프레임워크
- Next.js 기반 (SSR/CSR 혼합) - `__NEXT_DATA__` JSON 인라인 가능
- 상품 상세 페이지에서 `__NEXT_DATA__` 파싱 시 API 호출 없이 데이터 추출 가능

### 봇 차단 메커니즘
- Cloudflare CDN 사용 (헤더에 cf-ray 등 존재)
- 직접 fetch(User-Agent 없이)는 403/500 반환
- API 엔드포인트는 적절한 헤더(Referer, Origin, Accept) 설정 시 비인증으로도 접근 가능
- 과도한 요청 시 429 반환 (rate limit)

### WebFetch 차단 여부
- WebFetch 도구로 kream.co.kr 접근 시 HTTP 500 반환 (봇 차단)
- Node.js fetch(proxy-server.mjs)에서는 적절한 헤더로 정상 접근 가능

## Puppeteer 도입 필요성 분석

### API 방식으로 해결되는 것 (현재 구현됨)
- 상품 검색 (키워드 기반)
- 상품 상세 (가격, 브랜드, styleCode)
- 사이즈별 ask/bid/lastSale 시세

### Puppeteer가 필요한 경우
- 로그인 세션 획득 (Cloudflare challenge 우회)
- 추가 이미지 목록 (상세 페이지 내 여러 이미지)
- 카테고리 탐색 기반 상품 목록 수집 (API가 없는 경우)
- `__NEXT_DATA__` 파싱으로 구조화된 데이터 추출
- 거래 내역/차트 데이터 (인증 필요)

## 권장 Puppeteer 설정

```javascript
// 스텔스 설정
launch({
  headless: 'new',  // 또는 false (Cloudflare 우회 목적)
  args: [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-blink-features=AutomationControlled',
    '--window-size=1920,1080'
  ]
})

// 필수 헤더
page.setExtraHTTPHeaders({
  'Accept-Language': 'ko-KR,ko;q=0.9',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
})

// navigator.webdriver 숨기기
page.evaluateOnNewDocument(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
})
```

## 딜레이 설정 (KREAM 권장)
- 기본 딜레이: 2000~4000ms
- 페이지 이동 간: 3000~6000ms
- 시세 API 연속 조회: 1500~3000ms
- 버스트 제한: 5건 → 15초 대기
