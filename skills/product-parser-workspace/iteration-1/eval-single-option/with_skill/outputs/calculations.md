# bestBenefitPrice 계산 과정

## 입력값 (goodsPrice)
- normalPrice: 52,000
- immediateDiscountedPrice: 39,000
- salePrice: 39,000
- couponPrice: 39,000 (판매가와 동일 = 쿠폰 할인 없음)
- maxBenefitPrice: null
- memberDiscountRate: 0
- gradeRate: 0
- maxUsePointRate: 0.04
- isPrePoint: false
- isRestictedUsePoint: false

## 쿠폰 API
- coupon_api.data.list: [] (사용 가능 쿠폰 없음)

---

## 1단계: 기본 판매가 선정
```
raw_sale = immediateDiscountedPrice = 39,000
s_price = 39,000 (39,000 <= 52,000 이므로 raw_sale 사용)
```

## 2단계: 쿠폰 할인
```
couponPrice(API) = 39,000 (salePrice와 동일 → 쿠폰 할인 없음)
maxBenefitPrice(API) = null
coupon_api.data.list = [] (쿠폰 없음)

best_coupon_discount = 0
coupon_applied = 39,000 - 0 = 39,000
```

## 3단계: 등급할인
```
memberDiscountRate = 0%
grade_discount = int(39,000 × 0 / 100 / 10) × 10 = 0
```

## 4단계: 적립금
```
point_base = coupon_applied - grade_discount = 39,000 - 0 = 39,000
maxUsePointRate = 0.04 → point_rate = 0.04 × 100 = 4(%)
isRestictedUsePoint = false → 적립금 사용 가능

point_usage = int(39,000 × 4 / 100 / 10) × 10
            = int(1,560 / 10) × 10
            = 156 × 10
            = 1,560
```

## 5단계: 적립 선할인
```
isPrePoint = false → 선할인 미적용
pre_discount = 0
```

## 최종 계산
```
remaining = s_price - coupon - grade - point
          = 39,000 - 0 - 0 - 1,560
          = 37,440

bestBenefitPrice = remaining - pre_discount
                 = 37,440 - 0
                 = 37,440
```

## 결과
| 항목 | 금액 |
|------|------|
| 정가 (originalPrice) | 52,000원 |
| 판매가 (salePrice) | 39,000원 |
| 쿠폰적용가 (couponPrice) | 39,000원 |
| 쿠폰 할인 | 0원 |
| 등급 할인 | 0원 |
| 적립금 사용 | 1,560원 |
| 선할인 | 0원 (isPrePoint=false) |
| **최대혜택가 (bestBenefitPrice)** | **37,440원** |

## 참고: 비의류(뷰티) 카테고리 특이사항
- category1 = "뷰티" → CATEGORY_EXEMPTIONS에 의해 F2(material), F4(color) 면제
- material: "" (essential에 "소재"/"재질" 키워드 없음, goodsMaterial.materials도 빈 배열)
- color: "" (essential에 "색상" 정확 일치 항목 없음)
- careInstructions: "" (essential에 "세탁"/"취급"/"주의사항" 키워드 없음)
- 위 빈값들은 화장품 카테고리에서 정상 동작임
