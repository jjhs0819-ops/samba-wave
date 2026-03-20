# 파싱 계산 과정 — eval-3-soldout-options

## 입력 데이터
- 상품번호: 4293381
- 상품명: [3PACK] 링클프리 와이드 팬츠
- 소싱처: MUSINSA

---

## 1. 가격 계산 (5단계 혜택가)

### 1단계: 기본 판매가 선정
```
immediateDiscountedPrice = null
salePrice = 79900
raw_sale = salePrice = 79900 (immediateDiscountedPrice가 null이므로 salePrice 사용)
normalPrice = 79900
raw_sale(79900) <= normalPrice(79900) → s_price = 79900
```

### 2단계: 쿠폰 할인
```
goodsPrice.couponPrice = 79900 (salePrice와 동일 = 쿠폰할인 없음)
coupon_api.list = [] (사용 가능 쿠폰 없음)
best_coupon_discount = 0
coupon_applied = 79900 - 0 = 79900
```

### 3단계: 등급할인
```
memberDiscountRate = 0
grade_discount = int(79900 * 0 / 100 / 10) * 10 = 0
```

### 4단계: 적립금
```
isRestictedUsePoint = false → 적립금 사용 가능
point_base = coupon_applied - grade_discount = 79900 - 0 = 79900
maxUsePointRate = 0.07 → point_rate = 7 (0~1 범위이므로 *100)
point_usage = int(79900 * 7 / 100 / 10) * 10
            = int(5593 / 10) * 10
            = 559 * 10
            = 5590
```

### 5단계: 적립 선할인 (isPrePoint=true)
```
remaining = s_price - 쿠폰할인 - 등급할인 - 적립금
          = 79900 - 0 - 0 - 5590
          = 74310
pre_discount = int(74310 * 0 / 100 / 10) * 10 = 0
(memberDiscountRate가 0이므로 선할인도 0)
```

### 최종 혜택가
```
bestBenefitPrice = remaining - pre_discount = 74310 - 0 = 74310
```

### 가격 요약
| 필드 | 값 | 설명 |
|------|-----|------|
| originalPrice | 79,900 | normalPrice |
| salePrice | 79,900 | immediateDiscountedPrice가 null이므로 salePrice 사용 |
| couponPrice | 79,900 | 쿠폰 없음, 원래 couponPrice 그대로 |
| bestBenefitPrice | 74,310 | 적립금 5,590원 차감 |
| discountRate | 0 | goodsPrice.discountRate |
| memberDiscountRate | 0 | goodsPrice.memberDiscountRate |

---

## 2. 옵션/재고 처리

### 옵션 필터링
| no | 이름 | activated | isDeleted | 판정 |
|----|------|-----------|-----------|------|
| 501 | S | true | false | 포함 |
| 502 | M | true | false | 포함 |
| 503 | L | true | false | 포함 |
| 504 | XL | true | false | 포함 |
| 505 | XXL | true | false | 포함 |
| 506 | 3XL | **false** | **true** | **제외** (규칙: activated=false OR isDeleted=true → 제외) |

### base_price 결정
```
immediateDiscountedPrice = null
salePrice = 79900
base_price = salePrice = 79900
모든 옵션의 item.price = 0
→ 옵션가격 = base_price + 0 = 79900
```

### 재고 판정
| productVariantId | outOfStock | isRedirect | remainQuantity | 판정 |
|-----------------|------------|------------|----------------|------|
| 501 (S) | true | false | 0 | stock=0, isSoldOut=true |
| 502 (M) | false | false | 3 | stock=3, isSoldOut=false |
| 503 (L) | true | false | 0 | stock=0, isSoldOut=true |
| 504 (XL) | true | false | 0 | stock=0, isSoldOut=true |
| 505 (XXL) | false | **true** | null | stock=null, isSoldOut=false, **isBrandDelivery=true** |

### 재고 판정 규칙 적용
- 501 (S): outOfStock=true + isRedirect=false → stock=0, isSoldOut=true
- 502 (M): outOfStock=false, remainQuantity=3 → stock=3, isSoldOut=false
- 503 (L): outOfStock=true + isRedirect=false → stock=0, isSoldOut=true
- 504 (XL): outOfStock=true + isRedirect=false → stock=0, isSoldOut=true
- 505 (XXL): isRedirect=true → stock=null, isSoldOut=false, isBrandDelivery=true

---

## 3. 이미지 처리

### 대표/추가 이미지 (images)
```
1. thumbnailImageUrl: /images/goods_img/20240802/4293381/4293381_17549680630454_500.jpg
   → /로 시작 → https://image.msscdn.net 붙임
   → https://image.msscdn.net/images/goods_img/20240802/4293381/4293381_17549680630454_500.jpg

2. goodsImages[0]: /images/prd_img/20240802/4293381/detail_4293381_17549680630455_500.jpg
   → https://image.msscdn.net/images/prd_img/20240802/4293381/detail_4293381_17549680630455_500.jpg

3. goodsImages[1]: /images/prd_img/20240802/4293381/detail_4293381_17549680630456_500.jpg
   → https://image.msscdn.net/images/prd_img/20240802/4293381/detail_4293381_17549680630456_500.jpg

총 3장 (9장 이하, 중복 없음)
```

### 상세 이미지 (detailImages)
```
goodsContents에서 <img src> 추출:
1. /images/prd_img/20240802/4293381/desc_wrinkle_01.jpg → icon/btn_ 아님 → 포함
   → https://image.msscdn.net/images/prd_img/20240802/4293381/desc_wrinkle_01.jpg
2. /images/prd_img/20240802/4293381/desc_wrinkle_02.jpg → icon/btn_ 아님 → 포함
   → https://image.msscdn.net/images/prd_img/20240802/4293381/desc_wrinkle_02.jpg

총 2장
```

---

## 4. 고시정보 (essential) 키워드 매칭

| essential name | 매칭 규칙 | 매핑 필드 | 값 |
|----------------|----------|----------|-----|
| "소재/재질" | "소재" in name → material | material | "폴리에스터 95%, 스판덱스 5%" |
| "색상" | name == "색상" (정확 일치) | color | "블랙/네이비/그레이" |
| "치수" | "치수" in name, "취급" not in name | sizeInfo | "S(25)/M(26)/L(27-28)/XL(29-30)/XXL(31-32)" |
| "제조자/수입자" | "제조자" in name | manufacturer | "(주)더엣지" |
| "제조국(원산지)" | "원산지" in name | origin | "중국" |
| "세탁방법 및 취급시 주의사항" | "세탁" in name, "치수" not in name | careInstructions | "단독세탁, 표백제 사용 금지, 드라이클리닝 가능" |
| "품질보증기준" | "품질보증" in name | qualityGuarantee | "관련 법령 및 소비자분쟁해결기준에 따름" |

---

## 5. 판매 상태 판정

```
옵션 품절 현황:
- S: isSoldOut=true
- M: isSoldOut=false ← 재고 있음
- L: isSoldOut=true
- XL: isSoldOut=true
- XXL: isSoldOut=false ← 브랜드직배

all(o["isSoldOut"] for o in options) = false (M, XXL가 살아있음)
→ isOutOfStock = false

saleReserveYmdt = null, RESERVATION/PREORDER 배송타입 없음
→ saleStatus = "in_stock"
```

---

## 6. 카테고리

```
depth1: "바지" (code: "004")
depth2: "슈트 팬츠/슬랙스" (code: "004005")
depth3: null
depth4: null

category = "바지 > 슈트 팬츠/슬랙스"
categoryCode = "004005" (가장 깊은 non-null 코드)
```

---

## 7. 품질 체크리스트 자체 검증 (35항목)

| # | 항목 | 결과 | 비고 |
|---|------|------|------|
| A1 | name 비어있지 않음 | PASS | "[3PACK] 링클프리 와이드 팬츠" |
| A2 | brand null/빈값 아님 | PASS | "더엣지" |
| A3 | sourceSite 유효 | PASS | "MUSINSA" |
| A4 | siteProductId 존재 | PASS | "4293381" |
| A5 | sourceUrl https:// | PASS | "https://www.musinsa.com/products/4293381" |
| B1 | originalPrice > 0 | PASS | 79900 |
| B2 | salePrice > 0 | PASS | 79900 |
| B3 | salePrice <= originalPrice | PASS | 79900 <= 79900 |
| B4 | bestBenefitPrice <= salePrice | PASS | 74310 <= 79900 |
| B5 | couponPrice <= salePrice | PASS | 79900 <= 79900 |
| C1 | images >= 1 | PASS | 3장 |
| C2 | images <= 9 | PASS | 3장 |
| C3 | 모든 이미지 https:// | PASS | 전부 https://image.msscdn.net/... |
| C4 | detailImages >= 1 | PASS | 2장 |
| C5 | detailHtml 비어있지 않음 | PASS | HTML 존재 |
| D1 | options 배열 | PASS | 5개 옵션 배열 |
| D2 | 각 옵션 name 존재 | PASS | S, M, L, XL, XXL |
| D3 | 각 옵션 price > 0 | PASS | 79900 |
| D4 | 각 옵션 isSoldOut boolean | PASS | 모두 true/false |
| D5 | 품절=stock 0, 재고=stock>0 | PASS | S/L/XL=0, M=3, XXL=null(브랜드직배 허용) |
| E1 | category 비어있지 않음 | PASS | "바지 > 슈트 팬츠/슬랙스" |
| E2 | category1 존재 | PASS | "바지" |
| E3 | " > " 구분자 존재 | PASS | "바지 > 슈트 팬츠/슬랙스" |
| E4 | categoryCode 존재 | PASS | "004005" |
| F1 | origin 비어있지 않음 | PASS | "중국" |
| F2 | material 비어있지 않음 | PASS | "폴리에스터 95%, 스판덱스 5%" |
| F3 | manufacturer 비어있지 않음 | PASS | "(주)더엣지" |
| F4 | color 비어있지 않음 | PASS | "블랙/네이비/그레이" |
| F5 | careInstructions 존재 | PASS | "단독세탁, 표백제 사용 금지, 드라이클리닝 가능" |
| F6 | qualityGuarantee 존재 | PASS | "관련 법령 및 소비자분쟁해결기준에 따름" |
| G1 | saleStatus 유효값 | PASS | "in_stock" |
| G2 | isOutOfStock boolean | PASS | false |
| G3 | 전체 품절 시 isOutOfStock=true | PASS | 전체 품절 아님 → isOutOfStock=false (정상) |
| H1 | images[0] 대표이미지 가능 | PASS | https:// 시작, icon/btn_ 없음 |
| H2 | 옵션 name XML 호환 | PASS | S, M, L, XL, XXL — 특수문자 없음 |

### 최종 점수: 35/35 = 100%
