# 스마트스토어(네이버 커머스) API 상세 참조

소스 파일: `backend/backend/domain/samba/proxy/smartstore.py`

---

## OAuth2 인증 흐름

```
1. client_id + "_" + timestamp(ms) → 문자열 생성
2. bcrypt.hashpw(문자열, client_secret) → bcrypt 해시
3. base64.standard_b64encode(해시) → client_secret_sign
4. POST /external/v1/oauth2/token
   - Content-Type: application/x-www-form-urlencoded
   - Body: client_id, timestamp, client_secret_sign, grant_type=client_credentials, type=SELF
5. 응답: access_token + expires_in (기본 3600초)
6. 이후 모든 API: Authorization: Bearer {access_token}
```

**토큰 캐싱:** `_token_expires_at - 60초` 이전이면 기존 토큰 재사용.

**인증 실패 시:**
- Settings 테이블 `store_smartstore` 키에서 clientId/clientSecret 조회
- 계정 객체 우선 → Settings 폴백 순서

---

## transform_product() 출력 JSON 구조

`SmartStoreClient.transform_product(product, category_id, delivery_fee_type)` 의 반환값:

```json
{
  "originProduct": {
    "statusType": "SALE",
    "saleType": "NEW",
    "leafCategoryId": "{category_id || '50000803'}",
    "name": "{product.name}",
    "detailContent": "{product.detail_html || '<p>{name}</p>'}",
    "images": {
      "representativeImage": { "url": "{images[0]}" },
      "optionalImages": [
        { "url": "{images[1]}" },
        { "url": "{images[2]}" },
        { "url": "{images[3]}" },
        { "url": "{images[4]}" }
      ]
    },
    "salePrice": "{int(sale_price) || int(original_price) || 10000}",
    "stockQuantity": 999,
    "deliveryInfo": {
      "deliveryType": "DELIVERY",
      "deliveryAttributeType": "NORMAL",
      "deliveryCompany": "CJGLS",
      "deliveryFee": {
        "deliveryFeeType": "{delivery_fee_type || 'FREE'}",
        "baseFee": 0
      },
      "claimDeliveryInfo": {
        "returnDeliveryFee": 3000,
        "exchangeDeliveryFee": 6000
      }
    },
    "detailAttribute": {
      "afterServiceInfo": {
        "afterServiceTelephoneNumber": "02-1234-5678",
        "afterServiceGuideContent": "상세페이지 참조"
      },
      "originAreaInfo": {
        "originAreaCode": "03",
        "content": "{product.origin || '해외'}"
      },
      "minorPurchasable": false,
      "productInfoProvidedNotice": {
        "productInfoProvidedNoticeType": "WEAR",
        "wear": {
          "material": "{product.material || '상세 이미지 참조'}",
          "color": "{db_color || 상품명추출 || '상세 이미지 참조'}",
          "size": "발길이(mm): {sizes쉼표연결}" 또는 "FREE (상세 이미지 참조)",
          "manufacturer": "{product.manufacturer || brand}",
          "caution": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 사용 금지",
          "packDateText": "주문 후 개별포장 발송",
          "warrantyPolicy": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
          "afterServiceDirector": "{brand} 고객센터"
        }
      }
    }
  },
  "smartstoreChannelProduct": {
    "channelProductName": "{product.name}",
    "storeKeepExclusiveProduct": false,
    "naverShoppingRegistration": false,
    "channelProductDisplayStatusType": "ON"
  }
}
```

### 필드 매핑 상세

**가격:**
```python
sale_price = int(product.get("sale_price", 0))
if sale_price <= 0:
  sale_price = int(product.get("original_price", 0)) or 10000
```

**색상 추출 체인:**
```python
# 1순위: DB color 필드
db_color = product.get("color", "")
# 2순위: 상품명에서 " - " 뒤 추출
if " - " in name:
  color_part = name.split(" - ", 1)[1].split("/")[0].strip()
# 3순위: 폴백
color_text = db_color or (color_part[:200] if color_part else "상세 이미지 참조")
```

**사이즈 텍스트:**
```python
options = product.get("options") or []
sizes = [o.get("size", "") or o.get("name", "") for o in options if o.get("size") or o.get("name")]
size_text = ", ".join(sorted(set(s for s in sizes if s)))[:200] or "상세설명 참조"
# 사이즈 있으면: "발길이(mm): 230, 240, 250, 260, 270, 280"
# 사이즈 없으면: "FREE (상세 이미지 참조)"
```

---

## upload_image_from_url() 상세

### 이미지 다운로드 + 업로드 2단계

```
[1] 외부 이미지 다운로드
    - User-Agent: Mozilla/5.0 브라우저 에뮬레이션
    - Referer: 이미지 원본 도메인 자동 설정
    - Accept: image/webp,image/apng,image/*,*/*;q=0.8
    - follow_redirects=True

[2] 네이버 이미지 서버 업로드
    - POST /external/v1/product-images/upload
    - multipart/form-data: imageFiles=(filename, bytes, content_type)
    - 응답: {"images": [{"url": "https://shop-phinf.pstatic.net/..."}]}
```

### Referer 규칙

| 이미지 도메인 | Referer 설정 | 이유 |
|---|---|---|
| `msscdn.net` | `https://www.musinsa.com/` | 무신사 CDN 핫링크 방지 |
| 기타 | `{scheme}://{netloc}/` | 이미지 원본 도메인 |

### CDN 차단 감지

```python
if len(img_bytes) < 1000:
  raise SmartStoreApiError(f"이미지가 비정상적으로 작음({len(img_bytes)}B) — CDN 차단 가능성")
```
1000B 미만이면 핫링크 차단 이미지(1x1 투명 GIF 등)로 판단.

### 확장자 결정

```python
ext = "jpg"  # 기본
if "png" in content_type: ext = "png"
elif "webp" in content_type: ext = "webp"
```

---

## register_product() API

- **엔드포인트:** `POST /external/v2/products`
- **Content-Type:** application/json
- **인증:** Bearer 토큰
- **타임아웃:** 30초

### 성공 응답

```json
{
  "originProductNo": 123456789,
  "smartstoreChannelProductNo": 987654321,
  "productNo": 123456789
}
```

상품번호 추출 우선순위:
1. `originProductNo` (수정/삭제 API에 필요)
2. `productNo`
3. `smartstoreChannelProductNo`
4. `product_id` / `productId`

### 에러 응답 파싱

```json
{
  "message": "InvalidInputs",
  "invalidInputs": [
    { "field": "originProduct.salePrice", "message": "가격은 0보다 커야 합니다" },
    { "field": "originProduct.leafCategoryId", "message": "유효하지 않은 카테고리입니다" }
  ]
}
```

파싱 로직:
```python
invalid_inputs = data.get("invalidInputs") or []
if invalid_inputs:
  details = "; ".join(
    f"{iv.get('field', '?')}: {iv.get('message', '')}" for iv in invalid_inputs
  )
  msg = f"{msg} [{details}]"
```

---

## 채널 정보 조회 / 스토어 슬러그

### get_channel_info()

- `GET /external/v1/seller/channels`
- 다양한 응답 구조 대응: list, dict(contents/channels/data/result), 단일 객체
- 추출: channelNo, channelName, storeSlug, url

### get_store_slug_fallback()

- 채널 API 실패 시 대체 방법
- 등록된 상품 검색 → smartstore.naver.com/{slug}/products/... 에서 슬러그 추출

---

## 상품 판매중지

```python
await client.update_product(product_no, {
  "originProduct": {"statusType": "SUSPENSION"}
})
```

`MARKET_DELETE_HANDLERS["smartstore"]`에서 호출.
`product.market_product_nos[account_id]`에서 상품번호 조회.
