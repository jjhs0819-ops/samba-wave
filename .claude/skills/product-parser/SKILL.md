---
name: product-parser
description: 소싱처 상품 수집·파싱·정규화 스킬. 쇼핑몰(무신사/KREAM/ABCmart/이랜드몰/올리브영 등)에서 상품 정보를 긁어오거나, 긁어온 데이터의 품질 문제를 다룰 때 사용. 핵심 트리거: ① 소싱사이트 이름 + 수집/이미지/옵션/재고/가격 관련 문제 ② 고시정보 빈값·기본값('상세 이미지 참조') 문제 — 스마트스토어 등록 중 발견되더라도 수집 데이터 문제면 이 스킬 사용 ③ 새 소싱처 수집기 개발 ④ 상세페이지 이미지 미수집 ⑤ background.js·refresher 수집 로직 수정. 제외: API 인증, 대시보드, 주문관리, DB 스키마, 카테고리 맵핑 UI.
---

# Product Parser — 소싱처 상품 수집 & 마켓 등록 포맷 정돈

## 이 스킬의 목적

소싱처에서 상품 정보를 수집하여 **마켓 등록에 바로 사용할 수 있는 형태**로 정돈한다.
핵심은 "수집한 데이터가 마켓 고시정보 입력 형태에 정확히 맞는가"이다.

## 스키마 일관성 원칙 (테스트 검증 완료)

스킬 없이 파싱하면 에이전트마다 brand=object, images={thumbnail,product,detail}, saleStatus=object 등
제각각 nested 구조를 만든다. 이 스킬의 가장 큰 가치는 **CollectedProduct flat 스키마를 일관되게 강제하는 것**이다.

반드시 지켜야 할 스키마 규칙:
- `brand`: string (브랜드명 한글). object 아님
- `images`: string[] (flat URL 배열). nested {thumbnail, product, detail} 아님
- `options[].no`: number. `optionNo` 아님
- `options[].price`: base_price + option_price 합산값. `additionalPrice` 별도 아님
- `saleStatus`: enum string ("in_stock"|"sold_out"|"preorder"). object 아님
- `season`: string (빈값 허용). object {year, season} 아님
- `material`: string. array 아님
- `bestBenefitPrice`: goodsPrice 기반 5단계 계산. 쿠폰 API 사용 금지, goodsPrice.couponPrice만 사용
- `detailHtml`: 내부 img src도 URL 정규화 적용해야 함

## 자기 진화 규칙

**사용자가 수집 관련 수정을 요구하면, 수정 내용을 이 스킬 파일에도 반영해야 한다.**
- 새로운 소싱처 패턴 → `소싱처별 수집 패턴` 섹션에 추가
- 파싱 규칙 변경 → 해당 섹션 업데이트
- 마켓 포맷 변경 → `마켓 등록 포맷` 섹션 업데이트
- 버그 수정 → `알려진 이슈 & 해결 패턴` 섹션에 기록
- autoresearch 루프에서 발견된 패턴 → `파싱 규칙` 섹션 보강

---

## Autoresearch 루프

소싱처 수집기를 개발하거나 수정할 때, 아래 루프를 통해 파싱 품질을 자동 검증하고 개선한다.

### 루프 흐름

```
[1] 샘플 데이터 준비 (evals/ 디렉토리의 *-input.json 3~5개)
         ↓
[2] 전체 샘플 파싱 → 품질 체크리스트 채점 (35개 항목, 100점 만점)
         ↓
[3] 점수 < 95%면 → SKILL.md 또는 파서 코드에서 단 1가지만 수정
         ↓
[4] 다시 파싱 → 점수 비교
         ↓
[5] 점수 ↑ → 유지  /  점수 ↓ → 원래대로 복원
         ↓
[6] 95% 이상 3회 연속이면 종료, 아니면 [3]으로
```

### 루프 규칙

1. **한 번에 1가지만 수정** — 여러 변경을 동시에 하면 원인 추적 불가
2. **점수가 내려가면 즉시 복원** — git stash 또는 변경 전 상태 보관
3. **95% 이상 3회 연속이면 종료** — 과적합 방지
4. **새 샘플 추가 시 처음부터** — 기존 점수에 안주하지 않음
5. **루프 결과는 변경 이력에 기록** — 어떤 수정이 점수를 올렸는지 추적

### 루프 실행 방법

```bash
# 1. evals/ 디렉토리의 샘플 목록 확인
ls skills/product-parser/evals/eval-*-input.json

# 2. 각 샘플에 대해 파서 실행 (실제 API 호출 또는 모의 데이터)
# 3. 출력 JSON을 expected와 비교하여 체크리스트 채점
# 4. 점수 보고 및 개선 루프 진입
```

---

## 품질 체크리스트 (35항목, 100점 만점)

수집된 상품 JSON 1건에 대해 Yes=1점, No=0점으로 채점한다.
총점 = (합계 / 35) × 100으로 환산한다.

### A. 기본 정보 (5항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| A1 | `name`이 비어있지 않은가? | `len(name) > 0` | 스마트스토어 `originProduct.name`, 11번가 `prdNm` — 필수 |
| A2 | `brand`가 null/빈값이 아닌가? | `brand is not None and len(brand) > 0` | 스마트스토어 `brand` fallback "상세설명 참조"면 등록은 되지만 노출 불이익 |
| A3 | `sourceSite`가 유효한 소싱처 코드인가? | `sourceSite in VALID_SITES` | 시스템 식별자. 없으면 refresher 매핑 실패 |
| A4 | `siteProductId`가 존재하는가? | `siteProductId is not None and len(str(siteProductId)) > 0` | 갱신/재수집 시 식별 키 |
| A5 | `sourceUrl`이 https:// 로 시작하는 유효 URL인가? | `sourceUrl.startswith("https://")` | 원본 추적용. 프로토콜 누락 주의 |

### B. 가격 (5항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| B1 | `originalPrice`가 0보다 큰 숫자인가? | `isinstance(originalPrice, (int, float)) and originalPrice > 0` | 정가. 스마트스토어 `salePrice` 계산 기준 |
| B2 | `salePrice`가 0보다 큰 숫자인가? | `isinstance(salePrice, (int, float)) and salePrice > 0` | 판매가. 0이면 스마트스토어에서 10000으로 폴백됨 |
| B3 | `salePrice ≤ originalPrice`인가? | `salePrice <= originalPrice` | 판매가가 정가보다 높으면 데이터 오류 |
| B4 | `bestBenefitPrice ≤ salePrice`인가? | `bestBenefitPrice <= salePrice` | 혜택가 > 판매가이면 계산 로직 오류 |
| B5 | `couponPrice ≤ salePrice`인가? | `couponPrice <= salePrice` | 쿠폰가 > 판매가이면 쿠폰 계산 오류 |

### C. 이미지 (5항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| C1 | `images` 배열에 URL이 1개 이상인가? | `len(images) >= 1` | 대표이미지 필수. 스마트스토어 `representativeImage`, 11번가 `imageUrl` |
| C2 | `images`가 9장 이하인가? | `len(images) <= 9` | 무신사 모델 제한 `[:9]`. 초과분은 잘림 |
| C3 | 모든 이미지 URL이 `https://`로 시작하는가? | `all(url.startswith("https://") for url in images)` | `//` 또는 `/` 시작이면 변환 누락 |
| C4 | `detailImages`가 1개 이상 추출되었는가? | `len(detailImages) >= 1` | 상세페이지 이미지. 없으면 마켓 상세설명이 텍스트만 |
| C5 | `detailHtml`이 비어있지 않은가? | `len(detailHtml) > 0` | 11번가 `htmlDetail` CDATA, 스마트스토어 `detailContent` |

### D. 옵션/재고 (5항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| D1 | `options`가 배열인가? | `isinstance(options, list)` | 단일상품이면 빈 배열 `[]`, null이면 안 됨 |
| D2 | 각 옵션에 `name`이 존재하는가? | `all(o.get("name") for o in options)` | 11번가 `optionValue`, 스마트스토어 옵션명 |
| D3 | 각 옵션에 `price`가 0보다 큰 숫자인가? | `all(isinstance(o["price"], (int,float)) and o["price"]>0 for o in options)` | base_price + option_price. 0이면 무료 상품 |
| D4 | 각 옵션에 `isSoldOut`이 boolean인가? | `all(isinstance(o["isSoldOut"], bool) for o in options)` | 품절 필터링 기준. 문자열이면 비교 오류 |
| D5 | 품절 옵션의 `stock`이 0이고, 재고 옵션은 0보다 큰가? | 아래 참조 | `outOfStock=true → stock=0`, `remainQuantity → stock=값` |

D5 검증 로직:
```python
for o in options:
  if o["isSoldOut"]:
    assert o["stock"] == 0
  elif not o.get("isBrandDelivery"):
    assert o["stock"] is not None and o["stock"] > 0
  # 브랜드직배: stock=null 허용
```

### E. 카테고리 (4항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| E1 | `category`가 비어있지 않은가? | `len(category) > 0` | 마켓 카테고리 맵핑 기준 |
| E2 | `category1`(depth1)이 존재하는가? | `len(category1) > 0` | 최소 1단계 카테고리 필수 |
| E3 | `category`에 ` > ` 구분자가 있는가? | `" > " in category` | depth2 이상이어야 마켓 매핑 정확도 향상 |
| E4 | `categoryCode`가 존재하는가? | `len(categoryCode) > 0` | 스마트스토어 `leafCategoryId`, 11번가 `dispCtgrNo` |

### F. 고시정보 — 마켓 등록 핵심 (6항목)

| # | 체크 항목 | 검증 방법 | 근거 (마켓 등록 필드) |
|---|----------|----------|---------------------|
| F1 | `origin`(원산지)이 비어있지 않은가? | `len(origin) > 0` | 스마트스토어 `originAreaInfo.content`, 11번가 `orgnNm` — **마켓 필수** |
| F2 | `material`(소재)이 비어있지 않은가? | `len(material) > 0` | 스마트스토어 `wear.material` — 빈값이면 "상세 이미지 참조" 폴백 |
| F3 | `manufacturer`(제조사)가 비어있지 않은가? | `len(manufacturer) > 0` | 스마트스토어 `wear.manufacturer` — 빈값이면 brand 폴백 |
| F4 | `color`(색상)가 비어있지 않은가? | `len(color) > 0` | 스마트스토어 `wear.color` — 빈값이면 상품명에서 추출 시도 |
| F5 | `careInstructions`(세탁주의)가 존재하는가? | `len(careInstructions) > 0` | 스마트스토어 `wear.caution` — 하드코딩 폴백 존재하지만 정확한 값 우선 |
| F6 | `qualityGuarantee`(품질보증)가 존재하는가? | `len(qualityGuarantee) > 0` | 스마트스토어 `wear.warrantyPolicy` |

**카테고리별 고시정보 차이:**
```
의류(WEAR): material, color, size, manufacturer, caution, warrantyPolicy 전부 필수
신발(SHOES): 위 + 굽 높이, 소재(겉감/안감/밑창) 구분
화장품(COSMETIC): 제조업자, 내용물 용량, 사용기한, 전성분 — 의류 필드와 완전히 다름
```
> 화장품/식품 등 비의류 카테고리는 essential 키워드 매칭이 달라서 material/color가 빈값일 수 있음 (정상)

### G. 판매 상태 (3항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| G1 | `saleStatus`가 `in_stock`/`sold_out`/`preorder` 중 하나인가? | `saleStatus in VALID_STATUSES` | 마켓 등록/중지 판단 기준 |
| G2 | `isOutOfStock`이 boolean인가? | `isinstance(isOutOfStock, bool)` | 품절 필터링 |
| G3 | 전체 옵션 품절 시 `isOutOfStock=true`인가? | 아래 참조 | `all(o["isSoldOut"] for o in options) → isOutOfStock=true` |

G3 검증 로직:
```python
if options and all(o["isSoldOut"] for o in options):
  assert isOutOfStock == True
  assert saleStatus == "sold_out"
```

### H. 마켓 변환 호환 (2항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| H1 | `images[0]`이 대표이미지로 사용 가능한가? | `images[0].startswith("https://") and not any(x in images[0] for x in ["icon","btn_"])` | 스마트스토어 `representativeImage.url`, 11번가 `imageUrl` |
| H2 | 옵션 `name`에 XML 특수문자(`<>&"'`)가 이스케이프 가능한가? | `all(isinstance(o["name"], str) for o in options)` | 11번가 XML `optionValue`에 직접 삽입됨 |

---

### 채점 가중치 & 해석

| 카테고리 | 항목수 | 비중 |
|---------|-------|------|
| A. 기본 정보 | 5 | 14.3% |
| B. 가격 | 5 | 14.3% |
| C. 이미지 | 5 | 14.3% |
| D. 옵션/재고 | 5 | 14.3% |
| E. 카테고리 | 4 | 11.4% |
| F. 고시정보 | 6 | 17.1% |
| G. 판매 상태 | 3 | 8.6% |
| H. 마켓 호환 | 2 | 5.7% |
| **합계** | **35** | **100%** |

```
점수 계산: score = (통과항목수 / 35) × 100

해석:
  95~100%  → 마켓 등록 가능 (autoresearch 종료)
  80~94%   → 고시정보 또는 이미지 누락 가능성 (루프 계속)
  60~79%   → 주요 필드 다수 누락 (파서 구조 점검)
  < 60%    → 파서 기본 동작 불량 (API 응답 구조 확인)
```

### 샘플별 예외 허용

화장품 등 비의류 카테고리는 고시정보 매칭이 구조적으로 다르다.
카테고리 기반으로 일부 체크 항목을 면제할 수 있다:

```python
CATEGORY_EXEMPTIONS = {
  "뷰티": ["F2", "F4"],       # material, color — 화장품 고시정보에 해당 필드 없음
  "디지털/가전": ["F5"],       # careInstructions — 가전 카테고리 해당 없음
  "식품": ["F2", "F4", "F5"], # 식품은 의류 고시정보 체계와 다름
}

# 면제 항목은 자동 pass 처리
exempt = CATEGORY_EXEMPTIONS.get(category1, [])
if check_id in exempt:
  score += 1  # 자동 통과
```

---

## 아키텍처 개요

```
소싱처 상품 페이지
    ↓
[수집 계층] — 서버 직접 HTTP 또는 확장앱 DOM 스크래핑
    ↓
[정규화] — CollectedProduct 모델로 통일
    ↓
[품질 체크리스트 채점] — 35항목 자동 검증
    ↓
[마켓 변환] — 스마트스토어(JSON), 11번가(XML) 등 마켓별 포맷
    ↓
마켓 등록 API
```

### 수집 방식 결정 기준

| 조건 | 방식 | 예시 |
|------|------|------|
| 공개 API 존재 | 서버 직접 HTTP | 무신사 |
| 로그인/JS렌더링 필수 | 확장앱 큐 + DOM | KREAM |
| 공개 페이지 + 정적 HTML | 확장앱 소싱 (범용) | ABCmart, GrandStage |

**원칙: 확장앱은 얇은 클라이언트 — DOM 읽기 + 서버 전송만. 로직은 서버에.**

---

## CollectedProduct 필수 필드

새 소싱처를 추가할 때 반드시 채워야 하는 필드 목록이다.
비어 있으면 마켓 등록 시 거부되므로 가능한 한 모두 채운다.

### 기본 정보
| 필드 | 설명 | 필수 |
|------|------|------|
| `sourceSite` | 소싱처 식별자 (MUSINSA, KREAM 등) | ✅ |
| `siteProductId` | 소싱처 상품번호 | ✅ |
| `sourceUrl` | 원본 상품 URL | ✅ |
| `name` | 상품명 (한국어) | ✅ |
| `nameEn` | 영문 상품명 | ⬜ |
| `brand` | 브랜드명 (한글) | ✅ |
| `brandCode` | 브랜드코드 (영문) | ⬜ |

### 이미지 — 3단계 구조
| 필드 | 설명 | 규칙 |
|------|------|------|
| `images` | 대표+추가 이미지 | **최대 9장**, 첫 번째가 대표이미지 |
| `detailImages` | 상세페이지 이미지 | HTML에서 `<img src>` 추출, icon/btn_ 제외 |
| `detailHtml` | 상세설명 원본 HTML | 마켓 상세설명에 그대로 사용 |

**이미지 URL 정규화 규칙:**
```
1. http로 시작 → 그대로 사용
2. //로 시작 → https: 붙임
3. /로 시작 → https://image.msscdn.net 붙임 (무신사)
4. 각 소싱처마다 CDN 도메인이 다르므로 _to_image_url() 구현 필수
```

**이미지 수집 순서:**
```
1. 썸네일 URL → images[0] (대표이미지)
2. 상품 이미지 배열 → images[1~8] (추가이미지)
3. 중복 제거 (dict.fromkeys)
4. 최대 9장 제한 ([:9])
5. 상세 HTML 파싱 → detailImages (별도)
```

### 가격
| 필드 | 설명 |
|------|------|
| `originalPrice` | 정가 (normalPrice) |
| `salePrice` | 판매가 (할인 적용) |
| `couponPrice` | 쿠폰 적용가 |
| `bestBenefitPrice` | 최대혜택가 (쿠폰+등급+적립금+선할인) |
| `discountRate` | 할인율 (%) |
| `memberDiscountRate` | 회원등급 할인율 (%) |

**무신사 혜택가 5단계 계산 (10원 절사, 쿠폰 API 미사용):**
```
⚠️ 로그인 필수 — 비로그인 수집은 차단됨. 로그인 상태에서는 쿠폰 API(_fetch_coupons)가
   실제 적용 가능한 쿠폰을 반환하므로 bestBenefitPrice 계산에도 반영.
   goodsPrice.couponPrice는 쿠폰 미반영인 경우가 있으므로 쿠폰 API 결과를 우선 사용.

1단계: 기본 판매가 선정
   raw_sale = immediateDiscountedPrice || salePrice
   s_price = raw_sale이 정가 이하이면 raw_sale, 아니면 normalPrice

2단계: 쿠폰 할인 (goodsPrice.couponPrice 기준)
   benefit_coupon_discount = s_price - couponPrice (couponPrice < s_price일 때)
   benefit_base = s_price - benefit_coupon_discount

3단계: 등급할인 (benefit_base 기준, partnerDiscountOn=true일 때만)
   ⚠️ partnerDiscountOn=false이면 등급할인 불가 상품 → grade_discount=0
   grade_discount = benefit_base × memberDiscountRate / 100 (10원 절사) if partnerDiscountOn else 0

4단계: 적립금 (benefit_base - 등급할인 기준)
   point_base = benefit_base - grade_discount
   point_usage = point_base × maxUsePointRate*100 / 100 (10원 절사)

5단계: 적립 선할인 (isPrePoint=true만)
   remaining = benefit_base - 등급 - 적립금
   pre_discount = remaining × memberDiscountRate / 100 (10원 절사)

최종: bestBenefitPrice = remaining - pre_discount
```

### 옵션/재고
| 필드 | 설명 |
|------|------|
| `options[]` | 옵션 배열 |
| `options[].no` | 옵션 고유번호 |
| `options[].name` | 옵션명 (사이즈/색상 조합, " / " 구분) |
| `options[].price` | 옵션별 가격 (base_price + option_price) |
| `options[].stock` | 재고 수량 (null=무한/브랜드직배) |
| `options[].isSoldOut` | 품절 여부 |
| `options[].isBrandDelivery` | 브랜드 직배송 여부 |
| `options[].deliveryType` | 배송 타입 (GENERAL, RESERVATION 등) |
| `options[].managedCode` | 관리코드 |

**옵션 처리 규칙:**
```
1. activated=false 또는 isDeleted=true → 제외
2. 재고 API로 옵션별 재고 조회
3. outOfStock=true + isRedirect=false → stock=0, isSoldOut=true
4. isRedirect=true (브랜드직배) → stock=null, isSoldOut=false
5. remainQuantity 존재 → stock=값
6. 그 외 → stock=999
7. 옵션이 없는 단일상품 → options=[]
```

### 배송 정보 (무배당발)
| 필드 | 설명 |
|------|------|
| `freeShipping` | 무료배송 여부 (Boolean) |
| `sameDayDelivery` | 당일발송 여부 (Boolean) |

**무신사 배송 필드 매핑 (2026-03-22 API 검증 완료):**
```
⚠️ deliveryFeeInfo, todayDelivery, isFreeShipping 필드는 존재하지 않음!

무료배송 = 플러스배송:
  d.isPlusDelivery === true → freeShipping=true

당일발송 = 플러스배송 OR 당일출고:
  d.isPlusDelivery === true → sameDayDelivery=true (플러스배송 = 무배+당발 패키지)
  d.logisticsPrioritizedInventory.isTodayReleaseGoods === true → sameDayDelivery=true (비플러스 당일출고)

참고: PLUS 상품은 마감시간(cutOffHour, 보통 22시) 전 주문 시 당일출고 → 익일도착
DB 컬럼: samba_collected_product.free_shipping / same_day_delivery (Boolean, server_default=false)
```

### 고시정보 (마켓 등록 핵심)
| 필드 | 설명 | 매칭 키워드 |
|------|------|------------|
| `origin` | 원산지/제조국 | "제조국", "원산지" |
| `material` | 소재/재질 | "소재", "재질" |
| `manufacturer` | 제조사 | "제조사", "제조자" |
| `color` | 색상 | "색상" (정확히 일치) |
| `sizeInfo` | 치수 | "치수", "사이즈" (취급/주의 제외) |
| `careInstructions` | 세탁/취급 주의사항 | "세탁", "취급", "주의사항" (치수/사이즈 제외) |
| `qualityGuarantee` | 품질보증 | "품질보증" |

**고시정보 추출 우선순위:**
```
1. 소싱처 API의 고시정보(essential) 전용 엔드포인트 우선
2. 상품 상세 데이터의 goodsMaterial 등 구조화된 필드 fallback
3. 상세 HTML 파싱은 최후 수단
```

### 판매 상태
| 상태 | 판정 조건 (우선순위 순) |
|------|----------------------|
| `sold_out` | isSoldOut=true OR 모든 옵션 품절 |
| `preorder` | saleReserveYmdt 존재 OR 옵션에 RESERVATION/PREORDER 타입 |
| `in_stock` | 그 외 |

---

## 소싱처 인벤토리 (12개 등록)

소싱처별 상세 수집 패턴은 `references/` 디렉토리를 참고한다.

### 활성 파서 (2개)

| 사이트 | 코드 | 수집 방식 | 갱신 | 레퍼런스 |
|--------|------|----------|------|---------|
| 무신사 | `MUSINSA` | 서버 HTTP API | `_parse_musinsa` | → `references/musinsa.md` |
| KREAM | `KREAM` | 확장앱 큐 + DOM | `_parse_kream` | → `references/kream.md` |

### 소싱큐 기반 (7개, 확장앱 DOM 파싱)

| 사이트 | 코드 | 갱신 | 레퍼런스 |
|--------|------|------|---------|
| ABC마트 | `ABCmart` | 스텁 | → `references/generic-sourcing.md` |
| 그랜드스테이지 | `GrandStage` | 스텁 | → `references/generic-sourcing.md` |
| OKmall | `OKmall` | 스텁 | → `references/generic-sourcing.md` |
| 롯데ON | `LOTTEON` | 스텁 | → `references/generic-sourcing.md` |
| GSShop | `GSShop` | 스텁 | → `references/generic-sourcing.md` |
| 이랜드몰 | `ElandMall` | 스텁 | → `references/generic-sourcing.md` |
| SSF샵 | `SSF` | 스텁 | → `references/generic-sourcing.md` |

### 스텁 전용 (3개, 소싱큐 미지원)

| 사이트 | 코드 | 상태 |
|--------|------|------|
| Nike | `Nike` | refresher 스텁만 등록 |
| Adidas | `Adidas` | refresher 스텁만 등록 |
| 패션플러스 | `FashionPlus` | refresher 스텁만 등록 |

### 수집 방식 결정 기준

| 조건 | 방식 | 예시 |
|------|------|------|
| 공개 API 존재 | 서버 직접 HTTP | 무신사 |
| 로그인/JS렌더링 필수 | 확장앱 큐 + DOM | KREAM |
| 공개 페이지 + 정적 HTML | 확장앱 소싱 큐 (범용) | ABCmart, GrandStage 등 |

**원칙: 확장앱은 얇은 클라이언트 — DOM 읽기 + 서버 전송만. 로직은 서버에.**

### 주요 참조 파일

| 파일 | 역할 |
|------|------|
| `backend/.../proxy/musinsa.py` | 무신사 API 클라이언트 |
| `backend/.../proxy/kream.py` | KREAM 클라이언트 + 큐 |
| `backend/.../proxy/sourcing_queue.py` | 통합 소싱 큐 (7개 사이트) |
| `backend/.../collector/refresher.py` | SITE_PARSERS 매핑 + 갱신 로직 |
| `extension/background.js` | 확장앱 수집 핸들러 |
| `frontend/.../collector/page.tsx` | 프론트엔드 UI (12개 사이트 드롭다운) |

---

## 마켓 등록 포맷

### 스마트스토어 (Naver Commerce)
- **포맷:** JSON
- **인증:** OAuth2 + bcrypt 서명
- **이미지:** 외부 URL → 다운로드(Referer 설정) → 네이버 이미지 서버 업로드 → 변환된 URL 사용
- **이미지 제한:** 대표 1장 + 추가 최대 4장 (`images[1:5]`)
- **CDN 차단 감지:** 응답 < 1000B → 핫링크 차단 이미지 의심
- **고시정보 (productInfoProvidedNotice):**
  ```json
  {
    "productInfoProvidedNoticeType": "WEAR",
    "wear": {
      "material": "소재 → product.material || '상세 이미지 참조'",
      "color": "색상 → product.color || 상품명에서 추출 || '상세 이미지 참조'",
      "size": "치수 → 옵션에서 사이즈 추출 || 'FREE (상세 이미지 참조)'",
      "manufacturer": "제조사 → product.manufacturer || brand",
      "caution": "주의사항 → 하드코딩 폴백",
      "packDateText": "포장일 → '주문 후 개별포장 발송'",
      "warrantyPolicy": "품질보증 → 소비자분쟁해결기준",
      "afterServiceDirector": "A/S → '{brand} 고객센터'"
    }
  }
  ```
- **카테고리별 고시정보 타입:** WEAR(의류), SHOES(신발), COSMETIC(화장품) 등

**참조 파일:** `backend/backend/domain/samba/proxy/smartstore.py`

### 11번가
- **포맷:** XML
- **인증:** openapikey 헤더 (32자리 Open API Key)
- **이미지:** `imageUrl`(메인 1장), `addImageUrl1~3`(추가 최대 3장, `images[1:4]`)
- **상세설명:** `<htmlDetail><![CDATA[{detail_html}]]></htmlDetail>`
- **옵션:** `<sellerOptions><sellerOption><optionName>옵션</optionName><optionValue>{name}</optionValue><stockQty>{stock}</stockQty></sellerOption></sellerOptions>`
- **원산지:** `<orgnNm>{origin || "기타"}</orgnNm>`
- **XML 특수문자:** `& < > " '` → `&amp; &lt; &gt; &quot; &apos;` 이스케이프 필수

**참조 파일:** `backend/backend/domain/samba/proxy/elevenst.py`

---

## 새 소싱처 추가 체크리스트

1. **수집 방식 결정** — API 직접 호출 vs 확장앱 DOM
2. **프록시 클라이언트 생성** — `backend/backend/domain/samba/proxy/{site}.py`
3. **이미지 URL 변환 함수** — `_to_image_url()` 구현
4. **옵션/재고 파싱** — 사이트별 옵션 구조 분석
5. **고시정보 추출** — 사이트의 고시정보 API 또는 HTML 파싱
6. **가격 계산** — 할인/쿠폰/혜택가 로직
7. **refresher 등록** — `refresher.py`의 SITE_PARSERS에 추가
8. **확장앱 연동** (필요 시) — `background.js`에 사이트별 핸들러
9. **CollectedProduct 모델 호환** — 모든 필수 필드 매핑 확인
10. **eval 추가** — `evals/` 디렉토리에 입력+기대출력 추가
11. **autoresearch 루프 실행** — 95% 이상 달성 확인

---

## 알려진 이슈 & 해결 패턴

### KREAM 이미지 미수집
- **현상:** KREAM 상품 이미지가 빈 배열로 수집됨
- **원인:** __NUXT__ 데이터 로드 타이밍 이슈
- **해결:** 현재 방식 유지 (우회하지 않음). 탭 active 전환 후 재시도

### 무신사 CDN 차단
- **현상:** 이미지 다운로드 시 1000B 미만 응답
- **원인:** Referer 미설정
- **해결:** Referer: https://www.musinsa.com/ 헤더 필수 (msscdn.net 도메인 감지)

### 고시정보 키워드 불일치
- **현상:** "제조자/수입자" → "제조사" 키워드 매칭 실패
- **해결:** "제조자" 키워드도 매칭 조건에 포함 (`'제조사' in name or '제조자' in name`)

### 비의류 카테고리 고시정보 빈값
- **현상:** 화장품/식품 등에서 material, color가 빈값
- **원인:** essential API의 필드명이 의류와 다름 ("소재" 대신 "전성분" 등)
- **해결:** 카테고리별 CATEGORY_EXEMPTIONS 적용. 빈값이 정상인 경우 체크리스트에서 면제

### 스마트스토어 이미지 업로드 실패
- **현상:** 외부 이미지 업로드 시 "이미지가 비정상적으로 작음" 에러
- **원인:** CDN에서 Referer 없이 요청하면 1x1 투명 GIF 반환
- **해결:** 이미지 원본 도메인을 Referer로 설정, 무신사는 `https://www.musinsa.com/`

### 무신사 bestBenefitPrice 과다할인 (2026-03-20 수정)
- **현상:** 상품 4468698에서 사이트 최대혜택가 150,890원인데 코드가 과다할인으로 수집
- **원인 1:** `_fetch_coupons()` 쿠폰 API가 비로그인 상태에서 적용 불가한 쿠폰을 반환하여 할인액 과다 계산
- **원인 2:** `partnerDiscountOn=false`(등급할인 불가 상품)인데 `memberDiscountRate`로 등급할인 적용
- **해결 1:** bestBenefitPrice 계산에서 쿠폰 API 결과 제외, `goodsPrice.couponPrice`만 사용
- **해결 2:** 등급할인을 `partnerDiscountOn=true`일 때만 적용. 선할인(isPrePoint)은 기존대로 `memberDiscountRate` 사용

### 무신사 시즌 "ALL ALL" 빈값 수집 (2026-03-22 수정)
- **현상:** 상품 4258416에서 무신사 웹 "ALL ALL" 표시인데 season이 빈값으로 수집
- **원인:** API 응답 `seasonYear=0000, season=0`을 빈값으로 필터링하는 로직
- **해결:** `seasonYear="0000"` → `"ALL"`, `_SEASON_MAP["0"]` → `"ALL"`로 변환하여 `"ALL ALL"` 수집

### 무신사 로그인(쿠키) 필수 (2026-03-20 추가)
- **현상:** 비로그인 상태에서 수집하면 쿠폰/등급 혜택가 부정확
- **해결:** 쿠키 없으면 수집 시도하지 않고 HTTP 400 에러 반환 ("확장앱에서 무신사 로그인 후 다시 시도하세요")

### 무신사 bestBenefitPrice 과소할인 (2026-03-21 수정)
- **현상:** 상품 4551978에서 사이트 최대혜택가 139,040원인데 코드가 159,820원으로 수집
- **원인 1:** `grade_discount_rate` 변수가 `memberDiscountRate` 키 1개만 조회. 다른 키(`gradeDiscountRate`/`gradeRate`)에 값이 있으면 놓침
- **원인 2:** `partnerDiscountOn=false` 상품에서 `memberDiscountRate=0` 반환. 선할인(`isPrePoint=true`)에 필요한 등급률도 0이 됨
- **원인 3:** `max(계산값, API값)` 안전장치가 적립금/선할인 적용된 계산값을 API 값(쿠폰가)으로 역전시킴
- **해결 1:** `grade_discount_rate`를 4개 키 + 회원등급 API fallback으로 조회
- **해결 2:** 회원 등급 API(`/api2/member/v1/me`)에서 `gradeName` 조회 → `GRADE_DISCOUNT_MAP`으로 할인율 매핑
- **해결 3:** `max()` 안전장치 제거 — 계정별 등급이 다르므로 API 값은 신뢰 불가

---

## 변경 이력

| 날짜 | 내용 | autoresearch 점수 |
|------|------|-----------------|
| 2026-03-20 | 초안 작성. 무신사/KREAM 패턴 기반 | - |
| 2026-03-20 | autoresearch 루프 + 35항목 체크리스트 추가 | - |
| 2026-03-20 | 테스트 실행 — 스키마 일관성 원칙 추가 (with-skill 100% vs baseline 50%) | 100% |
| 2026-03-20 | KREAM eval 샘플 추가, description 최적화 | - |
| 2026-03-20 | 등급할인 partnerDiscountOn 분기 추가, 무신사 로그인 필수 체크 | - |
| 2026-03-21 | 회원등급 API로 grade_discount_rate 조회, max() 안전장치 제거, 복수키 조회 | - |
| 2026-03-22 | 시즌 0000/0 → ALL ALL 변환 (빈값 수집 수정) | - |
| 2026-03-22 | 성별(sex) 빈값 → "남녀공용" 폴백 (무신사 수집) | - |
| 2026-03-22 | 무배당발 수집 추가 — isPlusDelivery(무배+당발), isTodayReleaseGoods(비플러스 당발). API 검증 완료 | - |
