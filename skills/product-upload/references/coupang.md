# 쿠팡 Wing API 상세 참조

소스 파일: `backend/backend/domain/samba/proxy/coupang.py`

---

## HMAC-SHA256 인증 흐름

```
1. datetime = UTC 현재시각 "yyMMddTHHmmssZ" 형식
2. message = datetime + method + path + query (단순 연결, 구분자 없음)
3. signature = hmac.new(secret_key, message, sha256).hexdigest()
4. Authorization = f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={datetime}, signature={signature}"
```

```python
def _generate_signature(self, method, path, query=""):
  dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
  # 단순 연결 — 줄바꿈(\n) 넣으면 Invalid signature 발생
  message = f"{dt}{method}{path}{query}"
  signature = hmac.new(
    self.secret_key.encode("utf-8"),
    message.encode("utf-8"),
    hashlib.sha256,
  ).hexdigest()
  authorization = (
    f"CEA algorithm=HmacSHA256, access-key={self.access_key}, "
    f"signed-date={dt}, signature={signature}"
  )
  return authorization, dt
```

**필요 인증 정보:** `accessKey`, `secretKey`, `vendorId`
**설정 조회:** 계정 객체 → `samba_settings` 테이블 `store_coupang` 키 폴백

---

## API 엔드포인트

| 동작 | 메서드 | 경로 |
|------|--------|------|
| 상품 등록 | `POST` | `/v2/providers/seller_api/apis/api/v1/marketplace/seller-products` |
| 상품 수정 | `PUT` | `/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}` |
| 상품 조회 | `GET` | `/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}` |

**BASE_URL:** `https://api-gateway.coupang.com`
**타임아웃:** 30초
**추가 헤더:** `X-Requested-By: samba-wave`

---

## transform_product() 출력 JSON 구조

`CoupangClient.transform_product(product, category_id, return_center_code, outbound_shipping_place_code)`:

```json
{
  "displayCategoryCode": "{category_id || 0}",
  "sellerProductName": "{product.name}",
  "vendorId": "",
  "saleStartedAt": "",
  "saleEndedAt": "",
  "displayProductName": "{product.name}",
  "brand": "{product.brand || ''}",
  "generalProductName": "{product.name}",
  "productGroup": "",
  "deliveryMethod": "PARCEL",
  "deliveryCompanyCode": "CJGLS",
  "deliveryChargeType": "FREE",
  "deliveryCharge": 0,
  "freeShipOverAmount": 0,
  "deliveryChargeOnReturn": 5000,
  "remoteAreaDeliverable": "N",
  "unionDeliveryType": "NOT_UNION_DELIVERY",
  "returnCenterCode": "{return_center_code}",
  "returnChargeName": "반품배송비",
  "companyContactNumber": "02-0000-0000",
  "returnChargeVendor": "VENDOR",
  "afterServiceContactNumber": "02-0000-0000",
  "afterServiceGuideContent": "상세페이지 참조",
  "outboundShippingPlaceCode": "{outbound_shipping_place_code}",
  "vendorUserId": "",
  "requested": false,
  "manufacture": "{product.manufacturer || ''}",
  "extraInfoMessage": "",
  "requiredDocuments": [],
  "vendorImageUrls": [
    { "imageOrder": 0, "imageUrl": "{images[0]}" },
    { "imageOrder": 1, "imageUrl": "{images[1]}" }
  ],
  "contentDetails": [
    {
      "content": "{product.detail_html || '<p>{name}</p>'}",
      "detailType": "HTML"
    }
  ],
  "items": [
    {
      "itemName": "{option.name || option.size || '기본'}",
      "originalPrice": "{int(original_price)}",
      "salePrice": "{int(sale_price)}",
      "maximumBuyCount": 999,
      "maximumBuyForPerson": 0,
      "outboundShippingTimeDay": 3,
      "unitCount": 1,
      "adultOnly": "EVERYONE",
      "taxType": "TAX",
      "vendorInventoryItemList": [
        { "quantity": "{option.stock || 999}" }
      ]
    }
  ]
}
```

---

## 필드 매핑 테이블

| CollectedProduct | 쿠팡 필드 | 변환 로직 | 폴백 |
|---|---|---|---|
| `name` | `sellerProductName` | 그대로 | (필수) |
| `name` | `displayProductName` | 그대로 | (필수) |
| `name` | `generalProductName` | 그대로 | (필수) |
| `brand` | `brand` | 그대로 | `""` |
| `manufacturer` | `manufacture` | 그대로 | `""` |
| `images[:10]` | `vendorImageUrls[].imageUrl` | `imageOrder` 인덱스 부여 | (필수) |
| `detail_html` | `contentDetails[0].content` | `detailType: "HTML"` | `<p>{name}</p>` |
| `category_code` | `displayCategoryCode` | 그대로 | `0` |
| `options[].name/size` | `items[].itemName` | 그대로 | `"기본"` |
| `options[].stock` | `items[].vendorInventoryItemList[0].quantity` | 그대로 | `999` |
| `original_price` | `items[].originalPrice` | `int()` | `0` |
| `sale_price` | `items[].salePrice` | `int()` | `0` |

### 고정값

| 필드 | 값 | 설명 |
|---|---|---|
| `deliveryMethod` | `"PARCEL"` | 택배 |
| `deliveryCompanyCode` | `"CJGLS"` | CJ대한통운 |
| `deliveryChargeType` | `"FREE"` | 무료배송 |
| `deliveryChargeOnReturn` | `5000` | 반품 배송비 |
| `remoteAreaDeliverable` | `"N"` | 도서산간 배송 불가 |
| `unionDeliveryType` | `"NOT_UNION_DELIVERY"` | 묶음배송 불가 |
| `outboundShippingTimeDay` | `3` | 출고 소요일 |
| `adultOnly` | `"EVERYONE"` | 성인 전용 아님 |
| `taxType` | `"TAX"` | 과세 |

---

## 옵션 처리

옵션이 있는 경우:
```python
for opt in options:
  items.append({
    "itemName": opt.get("name", "") or opt.get("size", "") or "기본",
    "originalPrice": int(product.get("original_price", 0)),
    "salePrice": int(product.get("sale_price", 0)),
    "vendorInventoryItemList": [{"quantity": opt.get("stock", 999)}],
    ...
  })
```

옵션이 없는 경우:
```python
items.append({
  "itemName": product.get("name", "기본"),
  "originalPrice": int(product.get("original_price", 0)),
  "salePrice": int(product.get("sale_price", 0)),
  "vendorInventoryItemList": [{"quantity": 999}],
  ...
})
```

**주의:** 각 옵션이 독립적인 `items` 배열 요소. 스마트스토어의 `combinationOption`과 다름.

---

## 제한사항

| 항목 | 제한 |
|------|------|
| 상품명 길이 | 200자 |
| 이미지 | 최대 10장 (`images[:10]`) |
| 이미지 형식 | JPG/PNG (외부 URL 직접 사용) |
| 상세설명 | HTML |
| 옵션 | `items` 배열 (각 옵션이 독립 아이템) |
| 배송비 | 무료 고정 (`FREE`) |
| 반품비 | 5,000원 |
| 데이터 포맷 | JSON |

---

## 디스패처 연동

`dispatcher.py:_handle_coupang()` (라인 204~233):

1. 계정 객체에서 `accessKey`, `secretKey`, `vendorId` 추출
2. 폴백: `samba_settings` 테이블 `store_coupang` 키
3. `CoupangClient.transform_product()` → JSON 생성
4. `data["vendorId"] = vendor_id` 런타임 주입
5. `client.register_product(data)` 호출

**이미지 업로드:** 별도 업로드 없음. 외부 URL 직접 사용.

---

## 판매중지

`dispatcher.py:_delete_coupang()` (라인 568~586):

```python
await client.update_product(product_no, {
  "sellerProductName": product.get("name", ""),
  "statusType": "STOP"
})
```

`market_product_nos[account_id]`에서 상품번호 조회.

---

## 알려진 제한사항

1. **반품센터 코드:** `returnCenterCode` 빈값으로 전달. 쿠팡 Wing API로 동적 조회 미구현
2. **출고지 코드:** `outboundShippingPlaceCode` 빈값. 별도 설정 필요
3. **vendorId 런타임 주입:** transform에서 빈값 → dispatcher에서 채움
