# 코드 변경안: 고시정보 타입 카테고리 기반 분기 (WEAR/SHOES/COSMETIC)

## 변경 대상 파일

`backend/backend/domain/samba/proxy/smartstore.py` — `transform_product()` 메서드

## 문제점

현재 `transform_product()`에서 고시정보 타입이 `"WEAR"`로 하드코딩되어 있다.
신발 카테고리 상품을 등록하면 스마트스토어에서 고시정보 타입 불일치로 경고가 발생하거나,
신발 전용 필드(`height` 등)가 누락된다.

**현재 코드 (라인 508~519):**
```python
"productInfoProvidedNotice": {
    "productInfoProvidedNoticeType": "WEAR",
    "wear": {
        "material": product.get("material", "") or "상세 이미지 참조",
        "color": color_text,
        "size": f"발길이(mm): {size_text}" if sizes else "FREE (상세 이미지 참조)",
        "manufacturer": mfr,
        "caution": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 사용 금지",
        "packDateText": "주문 후 개별포장 발송",
        "warrantyPolicy": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
        "afterServiceDirector": f"{brand} 고객센터",
    },
},
```

## 분기 전략

`SambaCollectedProduct`의 `category` 필드(전체 카테고리 경로)와 `category1`~`category4`(뎁스별)를 활용하여 키워드 매칭으로 고시정보 타입을 결정한다.

| 고시정보 타입 | 매칭 키워드 | 카테고리 예시 |
|---|---|---|
| `SHOES` | 신발, 슈즈, 스니커즈, 부츠, 샌들, 로퍼, 힐, 플랫, 슬리퍼, 뮬, shoes, sneakers, boots | `상의 > 신발`, `스니커즈` |
| `COSMETIC` | 화장품, 스킨케어, 메이크업, 향수, 코스메틱, 뷰티, cosmetic, beauty, skincare | `뷰티 > 스킨케어` |
| `WEAR` | 위 두 가지에 해당하지 않는 모든 경우 (기본값) | `상의 > 반소매 티셔츠` |

## 변경 코드

### `transform_product()` 전체 수정본 (라인 436~529)

```python
  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str = "",
    delivery_fee_type: str = "FREE",
  ) -> dict[str, Any]:
    """SambaCollectedProduct -> 스마트스토어 상품 등록 데이터 변환."""
    images_raw = product.get("images") or []
    representative = {"url": images_raw[0]} if images_raw else {}
    optional = [{"url": u} for u in images_raw[1:5]] if len(images_raw) > 1 else []

    sale_price = int(product.get("sale_price", 0))
    if sale_price <= 0:
      sale_price = int(product.get("original_price", 0)) or 10000

    brand = product.get("brand", "") or "상세설명 참조"
    # 제조사 정보 (manufacturer 필드에 "제조사: Nike inc. / 수입처: 나이키코리아" 형태로 저장)
    mfr = product.get("manufacturer", "") or brand

    # 옵션에서 사이즈 정보 추출
    options = product.get("options") or []
    sizes = [o.get("size", "") or o.get("name", "") for o in options if o.get("size") or o.get("name")]
    size_text = ", ".join(sorted(set(s for s in sizes if s)))[:200] or "상세설명 참조"

    # 카테고리에서 상품 유형 판단
    category = product.get("category", "") or ""
    name_lower = product.get("name", "").lower()

    # 색상: 상품명에서 추출 시도
    color_part = ""
    if " - " in product.get("name", ""):
      color_part = product["name"].split(" - ", 1)[1].split("/")[0].strip()
    # DB color 필드 우선, 없으면 상품명에서 추출
    db_color = product.get("color", "")
    color_text = db_color or (color_part[:200] if color_part else "상세 이미지 참조")

    # ------------------------------------------------------------------
    # 고시정보 타입 결정: 카테고리 키워드 기반 분기
    # ------------------------------------------------------------------
    notice_type = _determine_notice_type(category, name_lower)
    material_text = product.get("material", "") or "상세 이미지 참조"

    if notice_type == "SHOES":
      notice_data = {
        "productInfoProvidedNoticeType": "SHOES",
        "shoes": {
          "material": material_text,
          "color": color_text,
          "size": f"발길이(mm): {size_text}" if sizes else "FREE (상세 이미지 참조)",
          "height": "상세 이미지 참조",
          "manufacturer": mfr,
          "caution": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 사용 금지",
          "warrantyPolicy": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
          "afterServiceDirector": f"{brand} 고객센터",
        },
      }
    elif notice_type == "COSMETIC":
      notice_data = {
        "productInfoProvidedNoticeType": "COSMETIC",
        "cosmetic": {
          "capacity": "상세 이미지 참조",
          "mainIngredient": material_text,
          "functionality": "해당없음",
          "expirationDate": "제조일로부터 36개월 (상세 이미지 참조)",
          "usageDirection": "상세 이미지 참조",
          "manufacturer": mfr,
          "manufacturedCountry": product.get("origin", "") or "해외",
          "caution": "상세 이미지 참조",
        },
      }
    else:
      # 기본값: WEAR (의류)
      notice_data = {
        "productInfoProvidedNoticeType": "WEAR",
        "wear": {
          "material": material_text,
          "color": color_text,
          "size": f"발길이(mm): {size_text}" if sizes else "FREE (상세 이미지 참조)",
          "manufacturer": mfr,
          "caution": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 사용 금지",
          "packDateText": "주문 후 개별포장 발송",
          "warrantyPolicy": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
          "afterServiceDirector": f"{brand} 고객센터",
        },
      }

    return {
      "originProduct": {
        "statusType": "SALE",
        "saleType": "NEW",
        "leafCategoryId": category_id or "50000803",
        "name": product.get("name", ""),
        "detailContent": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
        "images": {
          "representativeImage": representative,
          "optionalImages": optional,
        },
        "salePrice": sale_price,
        "stockQuantity": 999,
        "deliveryInfo": {
          "deliveryType": "DELIVERY",
          "deliveryAttributeType": "NORMAL",
          "deliveryCompany": "CJGLS",
          "deliveryFee": {
            "deliveryFeeType": delivery_fee_type,
            "baseFee": 0,
          },
          "claimDeliveryInfo": {
            "returnDeliveryFee": 3000,
            "exchangeDeliveryFee": 6000,
          },
        },
        "detailAttribute": {
          "afterServiceInfo": {
            "afterServiceTelephoneNumber": "02-1234-5678",
            "afterServiceGuideContent": "상세페이지 참조",
          },
          "originAreaInfo": {
            "originAreaCode": "03",
            "content": product.get("origin", "") or "해외",
          },
          "minorPurchasable": False,
          "productInfoProvidedNotice": notice_data,
        },
      },
      "smartstoreChannelProduct": {
        "channelProductName": product.get("name", ""),
        "storeKeepExclusiveProduct": False,
        "naverShoppingRegistration": False,
        "channelProductDisplayStatusType": "ON",
      },
    }
```

### 신규 모듈-레벨 함수 `_determine_notice_type()` (클래스 바깥, `SmartStoreClient` 위에 추가)

```python
# ------------------------------------------------------------------
# 고시정보 타입 결정 헬퍼
# ------------------------------------------------------------------

# 신발 카테고리 키워드
_SHOES_KEYWORDS = [
  "신발", "슈즈", "스니커즈", "부츠", "샌들", "로퍼",
  "힐", "플랫", "슬리퍼", "뮬", "운동화", "구두", "워커",
  "shoes", "sneakers", "boots", "sandals", "loafer",
]

# 화장품 카테고리 키워드
_COSMETIC_KEYWORDS = [
  "화장품", "스킨케어", "메이크업", "향수", "코스메틱", "뷰티",
  "립스틱", "파운데이션", "선크림", "세럼", "로션", "클렌징",
  "cosmetic", "beauty", "skincare", "perfume",
]


def _determine_notice_type(category: str, name_lower: str) -> str:
  """카테고리 경로와 상품명을 기반으로 고시정보 타입을 결정한다.

  Args:
    category: 상품 카테고리 전체 경로 (예: "신발 > 스니커즈")
    name_lower: 소문자 변환된 상품명

  Returns:
    "SHOES", "COSMETIC", "WEAR" 중 하나
  """
  # 카테고리 경로를 소문자로 변환하여 키워드 매칭
  cat_lower = category.lower()

  # 신발 카테고리 확인
  for kw in _SHOES_KEYWORDS:
    if kw in cat_lower or kw in name_lower:
      return "SHOES"

  # 화장품 카테고리 확인
  for kw in _COSMETIC_KEYWORDS:
    if kw in cat_lower or kw in name_lower:
      return "COSMETIC"

  # 기본값: 의류
  return "WEAR"
```

## 변경 요약

### 추가된 코드
1. **`_SHOES_KEYWORDS`** — 신발 카테고리 판별용 키워드 리스트 (15개)
2. **`_COSMETIC_KEYWORDS`** — 화장품 카테고리 판별용 키워드 리스트 (14개)
3. **`_determine_notice_type(category, name_lower)`** — 카테고리+상품명 기반 고시정보 타입 결정 함수

### 변경된 코드
4. **`transform_product()` 내 고시정보 블록** — `"WEAR"` 하드코딩을 `_determine_notice_type()` 호출로 교체하고, SHOES/COSMETIC/WEAR 3분기 생성

### 타입별 필드 차이

| 필드 | WEAR | SHOES | COSMETIC |
|---|---|---|---|
| `material` | O | O | `mainIngredient`로 대체 |
| `color` | O | O | X (필드 없음) |
| `size` | O | O | X (필드 없음) |
| `height` | X | O (굽높이) | X |
| `packDateText` | O | X (API 스펙에 없음) | X |
| `capacity` | X | X | O (용량) |
| `functionality` | X | X | O (기능성) |
| `expirationDate` | X | X | O (사용기한) |
| `usageDirection` | X | X | O (사용방법) |
| `manufacturedCountry` | X | X | O (제조국) |

### 기존 동작 유지
- 카테고리가 비어있거나 키워드에 매칭되지 않으면 기존과 동일하게 `WEAR`로 처리
- `WEAR` 타입의 필드 구성은 기존 코드와 100% 동일
- `sale_price`, `images`, `deliveryInfo` 등 고시정보 외 필드는 변경 없음

## 체크리스트 영향 (스킬 기준)

| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| C1 (`productInfoProvidedNoticeType`이 카테고리에 맞는가) | X (WEAR 고정) | O (SHOES/COSMETIC/WEAR 분기) |
| C2~C5 | 변경 없음 | 변경 없음 |

## 반영 시 재시작 필요
- **백엔드 서버 재시작 필요** (`smartstore.py` 변경)
