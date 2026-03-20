# 무신사 (MUSINSA) 수집 레퍼런스

## 개요

| 항목 | 내용 |
|------|------|
| **사이트 코드** | `MUSINSA` |
| **수집 방식** | 서버 직접 HTTP API |
| **갱신 파서** | `_parse_musinsa` (활성) |
| **인증** | 쿠키 기반 (확장앱 자동 동기화) |
| **참조 파일** | `backend/backend/domain/samba/proxy/musinsa.py` |

## API 엔드포인트

```
상품상세:  GET  https://goods-detail.musinsa.com/api2/goods/{goods_no}
옵션:     GET  https://goods-detail.musinsa.com/api2/goods/{goods_no}/options
재고:     POST https://goods-detail.musinsa.com/api2/goods/{goods_no}/options/v2/prioritized-inventories
고시정보:  GET  https://goods-detail.musinsa.com/api2/goods/{goods_no}/essential
쿠폰:     GET  https://api.musinsa.com/api2/coupon/coupons/getUsableCouponsByGoodsNo
검색:     GET  https://api.musinsa.com/api2/dp/v1/plp/goods
로그인확인: GET  https://api.musinsa.com/api2/member/v1/me
```

## 수집 흐름

```
1. 상품 상세 API → 기본정보, 가격, 이미지, 카테고리
2. 옵션 API → optionItems 배열 + optionValueNo 수집
3. 재고 API (POST) → optionValueNos 전송 → 옵션별 재고/품절/브랜드직배 판정
4. 고시정보 API → 소재/색상/치수/제조사/원산지/세탁/품질보증
5. 쿠폰 API → 사용 가능 쿠폰 할인액 계산
6. 최종 가격 계산 (5단계 혜택가)
```

## 필드 매핑 (API 응답 → CollectedProduct)

### MUSINSA_FIELDS (fallback 체인)

```python
# API 필드가 변경될 때 여기만 수정하면 됨
MUSINSA_FIELDS = {
  "normal_price": ["goodsPrice.normalPrice"],
  "sale_price": ["goodsPrice.immediateDiscountedPrice", "goodsPrice.salePrice"],
  "member_discount_rate": [
    "goodsPrice.memberDiscountRate",
    "goodsPrice.gradeDiscountRate",
    "goodsPrice.memberGradeDiscountRate",
    "goodsPrice.gradeRate",
  ],
  "coupon_price": ["goodsPrice.couponPrice"],
  "max_benefit_price": [
    "goodsPrice.maxBenefitPrice",
    "goodsPrice.benefitSalePrice",
    "goodsPrice.bestBenefitPrice",
  ],
  "is_sold_out": ["isSoldOut", "goodsPrice.isSoldOut", "isOutOfStock"],
}
```

## 이미지 수집

### URL 변환 (`_to_image_url`)
```python
# path가 http로 시작 → 그대로
# //로 시작 → https: 붙임
# /로 시작 → https://image.msscdn.net 붙임
```

### 수집 순서
```
1. thumbnailImageUrl → images[0] (대표이미지)
2. goodsImages[] 배열 → images[1~8] (각 imageUrl)
3. 중복 제거 (dict.fromkeys)
4. 최대 9장 제한 ([:9])
5. goodsContents HTML → <img src> 파싱 → detailImages (icon/btn_ 제외)
```

### CDN 차단 대응
- Referer 헤더 필수: `https://www.musinsa.com/`
- `msscdn.net` 도메인 → 무조건 `Referer: https://www.musinsa.com/`
- 응답 < 1000B → 핫링크 차단 이미지 의심

## 옵션/재고 처리

### 옵션 API 응답 구조
```json
{
  "data": {
    "optionItems": [
      {
        "no": 101,
        "activated": true,
        "isDeleted": false,
        "price": 0,
        "managedCode": "LMT-BLK-230",
        "optionValues": [{ "no": 1001, "name": "230" }]
      }
    ]
  }
}
```

### 재고 API (POST)
```json
// 요청: {"optionValueNos": [1001, 1002, ...]}
// 응답:
{
  "data": [
    {
      "productVariantId": 101,
      "remainQuantity": 15,
      "outOfStock": false,
      "isRedirect": false,
      "domesticDelivery": { "deliveryType": "GENERAL" }
    }
  ]
}
```

### 옵션 판정 규칙
```
1. activated=false OR isDeleted=true → 제외 (목록에 나타나지 않음)
2. outOfStock=true + isRedirect=false → stock=0, isSoldOut=true
3. isRedirect=true (브랜드직배) → stock=null, isSoldOut=false
4. remainQuantity 존재 → stock=값
5. 그 외 → stock=999
6. 옵션명: optionValues의 name을 " / "로 조인
7. 옵션가격: base_price + item.price (option_price)
```

### base_price 결정
```python
base_price = (
  goodsPrice.immediateDiscountedPrice
  or goodsPrice.salePrice
  or goodsPrice.normalPrice
)
```

## 가격 계산 (5단계 혜택가)

```
1단계: 기본 판매가 선정
  raw_sale = immediateDiscountedPrice || salePrice
  s_price = raw_sale (정가 이하이면) || normalPrice

2단계: 쿠폰 할인
  - goodsPrice.couponPrice와 maxBenefitPrice 중 더 큰 할인
  - 쿠폰 API 응답에서 추가 할인 탐색
  - coupon_applied = s_price - best_coupon_discount

  쿠폰 salePrice 해석 로직:
    salePrice < s_price * 0.5 → 할인금액
    salePrice >= s_price * 0.5 → 적용가 (s_price - salePrice = 할인금액)

3단계: 등급할인 (쿠폰적용가 기준)
  grade_discount = coupon_applied × memberDiscountRate / 100
  → 10원 절사: int(... / 10) * 10

4단계: 적립금 (쿠폰적용가 - 등급할인 기준)
  point_base = coupon_applied - grade_discount
  point_rate = maxUsePointRate × 100 (0~1 범위면 ×100)
  point_usage = int(point_base × point_rate / 100 / 10) * 10
  (isRestictedUsePoint=true면 0)

5단계: 적립 선할인 (isPrePoint=true만)
  remaining = s_price - 쿠폰 - 등급 - 적립금
  pre_discount = int(remaining × memberDiscountRate / 100 / 10) * 10

최종: bestBenefitPrice = remaining - pre_discount
```

## 고시정보 추출 (`_fetch_essential`)

### API 응답 구조
```json
{
  "data": {
    "essentials": [
      { "name": "소재", "value": "면 100%" },
      { "name": "색상", "value": "블랙" }
    ]
  }
}
```

### 키워드 매칭 규칙
```python
"소재" in name or "재질" in name → material
name == "색상" → color (정확 일치)
("치수" in name or "사이즈" in name) and "취급" not in name → size
"제조사" in name or "제조자" in name → manufacturer
"제조국" in name or "원산지" in name → origin
("세탁" in name or "취급" in name or "주의사항" in name) and "치수" not in name → careInstructions
"품질보증" in name → qualityGuarantee
```

### 소재 fallback
```python
# essential에 소재가 없으면 goodsMaterial.materials에서 추출
materials = data.goodsMaterial.materials
material_str = ", ".join(f"{name} {rate}%" for each material)
```

## 판매 상태 판정

```python
# 우선순위: sold_out → preorder → in_stock
saleStatus = (
  "sold_out"  if (isSoldOut OR 모든옵션.isSoldOut)
  "preorder"  if (saleReserveYmdt OR 옵션에 RESERVATION/PREORDER)
  "in_stock"  otherwise
)
```

## 차단 대응

| 상황 | 대응 |
|------|------|
| HTTP 429/403 | `RateLimitError` → exponential backoff (인터벌 2배, 최대 30초) |
| 연속 5회 실패 | 해당 사이트 전체 일시중단 |
| Retry-After 헤더 | 지정 시간 대기 후 1회 재시도 |
| 성공 시 | 인터벌 점진 복원 (최대 1.0초) |

## 쿠키 동기화 (확장앱)

```
확장앱 background.js:
1. chrome.webRequest.onBeforeSendHeaders → *.musinsa.com/* 요청 감지
2. Cookie 헤더 변경 감지
3. chrome.storage.local에 저장
4. 3초 debounce 후 서버로 전송 (POST /api/v1/samba/proxy/musinsa/set-cookie)
```

## 출력 JSON 구조 (get_goods_detail 반환값)

```json
{
  "id": "col_musinsa_{goods_no}_{timestamp}",
  "sourceSite": "MUSINSA",
  "siteProductId": "3347848",
  "sourceUrl": "https://www.musinsa.com/products/3347848",
  "name": "메이트 블랙",
  "nameEn": "Mate Black",
  "brand": "르무통",
  "brandCode": "lemouton",
  "category": "신발 > 스니커즈 > 라이프스타일화",
  "category1~4": "...",
  "categoryCode": "003002006",
  "images": ["https://image.msscdn.net/..."],
  "detailImages": ["https://image.msscdn.net/..."],
  "detailHtml": "<div>...</div>",
  "options": [
    {
      "no": 101,
      "name": "230",
      "price": 116900,
      "stock": 15,
      "isSoldOut": false,
      "isBrandDelivery": false,
      "deliveryType": "GENERAL",
      "managedCode": "LMT-BLK-230"
    }
  ],
  "originalPrice": 149000,
  "salePrice": 116900,
  "couponPrice": 105210,
  "bestBenefitPrice": 93990,
  "memberDiscountRate": 2,
  "origin": "베트남",
  "material": "메리노 울 70%",
  "manufacturer": "주식회사 우주텍",
  "color": "블랙",
  "sizeInfo": "230~280",
  "careInstructions": "찬물 손세탁 권장",
  "qualityGuarantee": "소비자분쟁해결기준",
  "saleStatus": "in_stock",
  "isOutOfStock": false,
  "isBoutique": false,
  "status": "collected"
}
```
