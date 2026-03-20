# bestBenefitPrice 계산 과정

## 입력값

| 필드 | 값 | 출처 |
|------|-----|------|
| normalPrice | 149,000 | detail_api.goodsPrice |
| immediateDiscountedPrice | 116,900 | detail_api.goodsPrice |
| salePrice | 116,900 | detail_api.goodsPrice |
| couponPrice | 105,210 | detail_api.goodsPrice |
| maxBenefitPrice | 99,800 | detail_api.goodsPrice |
| memberDiscountRate | 2 (%) | detail_api.goodsPrice |
| maxUsePointRate | 0.07 | detail_api |
| isPrePoint | true | detail_api |
| isRestictedUsePoint | false | detail_api |
| 쿠폰 API discountPrice | 11,690 | coupon_api.data.list[0] |

---

## 1단계: 기본 판매가 선정

```
raw_sale = immediateDiscountedPrice || salePrice
        = 116,900

s_price = raw_sale <= normalPrice ? raw_sale : normalPrice
        = 116,900 <= 149,000 ? 116,900
        = 116,900
```

**s_price = 116,900**

---

## 2단계: 쿠폰 할인

쿠폰 API 응답: `{ salePrice: 105210, discountPrice: 11690 }`

```
쿠폰 salePrice 해석:
  105,210 >= 116,900 * 0.5 (= 58,450) → 적용가로 해석
  할인금액 = 116,900 - 105,210 = 11,690 (discountPrice와 일치)

best_coupon_discount = 11,690
coupon_applied = s_price - best_coupon_discount
               = 116,900 - 11,690
               = 105,210
```

**coupon_applied = 105,210**

---

## 3단계: 등급할인 (쿠폰적용가 기준)

```
grade_discount = int(coupon_applied * memberDiscountRate / 100 / 10) * 10
               = int(105,210 * 2 / 100 / 10) * 10
               = int(2,104.2 / 10) * 10
               = int(210.42) * 10
               = 210 * 10
               = 2,100
```

**grade_discount = 2,100**

---

## 4단계: 적립금

```
point_base = coupon_applied - grade_discount
           = 105,210 - 2,100
           = 103,110

point_rate = maxUsePointRate * 100
           = 0.07 * 100
           = 7 (%)

isRestictedUsePoint = false → 적립금 적용

point_usage = int(point_base * point_rate / 100 / 10) * 10
            = int(103,110 * 7 / 100 / 10) * 10
            = int(721,770 / 100 / 10) * 10
            = int(7,217.7 / 10) * 10
            = int(721.77) * 10
            = 721 * 10
            = 7,210
```

**point_usage = 7,210**

---

## 5단계: 적립 선할인 (isPrePoint=true)

```
remaining = s_price - 쿠폰할인 - 등급할인 - 적립금
          = 116,900 - 11,690 - 2,100 - 7,210
          = 95,900

isPrePoint = true → 선할인 적용

pre_discount = int(remaining * memberDiscountRate / 100 / 10) * 10
             = int(95,900 * 2 / 100 / 10) * 10
             = int(1,918 / 10) * 10
             = int(191.8) * 10
             = 191 * 10
             = 1,910
```

**pre_discount = 1,910**

---

## 최종 계산

```
bestBenefitPrice = remaining - pre_discount
                 = 95,900 - 1,910
                 = 93,990
```

**bestBenefitPrice = 93,990**

---

## 검증

| 체크 | 결과 |
|------|------|
| bestBenefitPrice <= salePrice | 93,990 <= 116,900 (통과) |
| couponPrice <= salePrice | 105,210 <= 116,900 (통과) |
| salePrice <= originalPrice | 116,900 <= 149,000 (통과) |
| API maxBenefitPrice (99,800) vs 계산값 (93,990) | 계산값이 더 낮음 - 5단계 선할인이 추가 적용됨 |

## 할인 내역 요약

| 단계 | 할인명 | 할인액 | 누적 적용가 |
|------|--------|--------|------------|
| 0 | 정가 | - | 149,000 |
| 1 | 즉시할인 | 32,100 (22%) | 116,900 |
| 2 | 쿠폰할인 | 11,690 | 105,210 |
| 3 | 등급할인 (2%) | 2,100 | 103,110 |
| 4 | 적립금 (7%) | 7,210 | 95,900 |
| 5 | 선할인 (2%) | 1,910 | **93,990** |
| **합계** | | **55,010** (36.9%) | **93,990** |
