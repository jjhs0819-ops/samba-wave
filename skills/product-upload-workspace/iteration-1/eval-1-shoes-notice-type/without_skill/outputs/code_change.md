# 고시정보 타입 카테고리 기반 분기 (WEAR/SHOES/COSMETIC)

## 문제점

현재 `smartstore.py`의 `transform_product()` 메서드에서 `productInfoProvidedNoticeType`이 `"WEAR"`로 하드코딩되어 있다.
신발 카테고리 상품이나 화장품 카테고리 상품도 모두 `WEAR` 타입으로 등록되므로, 네이버 커머스 API에서 고시정보 불일치 오류가 발생할 수 있다.

## 변경 대상 파일

`backend/backend/domain/samba/proxy/smartstore.py` — `transform_product()` 메서드

## 변경 내용

### 1. 카테고리 기반 고시정보 타입 판별 헬퍼 함수 추가

`transform_product()` 위에 다음 헬퍼 메서드를 추가한다.

```python
@staticmethod
def _detect_notice_type(product: dict[str, Any]) -> str:
    """카테고리·상품명 기반으로 네이버 고시정보 타입(WEAR/SHOES/COSMETIC)을 판별."""
    category = (product.get("category") or "").lower()
    category1 = (product.get("category1") or "").lower()
    category2 = (product.get("category2") or "").lower()
    category3 = (product.get("category3") or "").lower()
    name_lower = (product.get("name") or "").lower()

    all_category_text = f"{category} {category1} {category2} {category3} {name_lower}"

    # 신발 키워드
    shoe_keywords = [
        "신발", "슈즈", "shoes", "sneakers", "스니커즈", "운동화",
        "부츠", "boots", "샌들", "sandals", "슬리퍼", "slipper",
        "로퍼", "loafer", "구두", "힐", "heel", "플랫", "flat",
        "러닝화", "축구화", "농구화", "트레이닝화", "워커",
        "flip-flop", "플립플랍", "뮬", "mule", "에스파드류",
    ]

    # 화장품 키워드
    cosmetic_keywords = [
        "화장품", "코스메틱", "cosmetic", "스킨케어", "skincare",
        "메이크업", "makeup", "립스틱", "lipstick", "파운데이션",
        "foundation", "선크림", "sunscreen", "세럼", "serum",
        "로션", "lotion", "클렌저", "cleanser", "토너", "toner",
        "마스크팩", "mask", "아이크림", "향수", "perfume",
    ]

    for kw in shoe_keywords:
        if kw in all_category_text:
            return "SHOES"

    for kw in cosmetic_keywords:
        if kw in all_category_text:
            return "COSMETIC"

    return "WEAR"
```

### 2. transform_product() 내부 고시정보 생성 로직 변경

기존 코드 (460~519번 줄 부근):

```python
    # 카테고리에서 상품 유형 판단
    category = product.get("category", "") or ""
    name_lower = product.get("name", "").lower()

    # 색상: 상품명에서 추출 시도
    if " - " in product.get("name", ""):
      color_part = product["name"].split(" - ", 1)[1].split("/")[0].strip()
    # DB color 필드 우선, 없으면 상품명에서 추출
    db_color = product.get("color", "")
    color_text = db_color or (color_part[:200] if color_part else "상세 이미지 참조")

    return {
      "originProduct": {
        ...
        "detailAttribute": {
          ...
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
        },
      },
      ...
    }
```

변경 후 코드 (전체 `transform_product` 메서드):

```python
  @staticmethod
  def _detect_notice_type(product: dict[str, Any]) -> str:
    """카테고리·상품명 기반으로 네이버 고시정보 타입(WEAR/SHOES/COSMETIC)을 판별."""
    category = (product.get("category") or "").lower()
    category1 = (product.get("category1") or "").lower()
    category2 = (product.get("category2") or "").lower()
    category3 = (product.get("category3") or "").lower()
    name_lower = (product.get("name") or "").lower()

    all_category_text = f"{category} {category1} {category2} {category3} {name_lower}"

    # 신발 키워드
    shoe_keywords = [
      "신발", "슈즈", "shoes", "sneakers", "스니커즈", "운동화",
      "부츠", "boots", "샌들", "sandals", "슬리퍼", "slipper",
      "로퍼", "loafer", "구두", "힐", "heel", "플랫", "flat",
      "러닝화", "축구화", "농구화", "트레이닝화", "워커",
      "flip-flop", "플립플랍", "뮬", "mule", "에스파드류",
    ]

    # 화장품 키워드
    cosmetic_keywords = [
      "화장품", "코스메틱", "cosmetic", "스킨케어", "skincare",
      "메이크업", "makeup", "립스틱", "lipstick", "파운데이션",
      "foundation", "선크림", "sunscreen", "세럼", "serum",
      "로션", "lotion", "클렌저", "cleanser", "토너", "toner",
      "마스크팩", "mask", "아이크림", "향수", "perfume",
    ]

    for kw in shoe_keywords:
      if kw in all_category_text:
        return "SHOES"

    for kw in cosmetic_keywords:
      if kw in all_category_text:
        return "COSMETIC"

    return "WEAR"

  @staticmethod
  def _build_notice(
    notice_type: str,
    product: dict[str, Any],
    *,
    material: str,
    color_text: str,
    size_text: str,
    sizes: list[str],
    mfr: str,
    brand: str,
  ) -> dict[str, Any]:
    """고시정보 타입에 따른 productInfoProvidedNotice 블록 생성."""

    if notice_type == "SHOES":
      return {
        "productInfoProvidedNoticeType": "SHOES",
        "shoes": {
          "material": material,
          "color": color_text,
          "size": f"발길이(mm): {size_text}" if sizes else "상세 이미지 참조",
          "height": "상세 이미지 참조",
          "manufacturer": mfr,
          "caution": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지",
          "packDateText": "주문 후 개별포장 발송",
          "warrantyPolicy": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
          "afterServiceDirector": f"{brand} 고객센터",
        },
      }

    if notice_type == "COSMETIC":
      return {
        "productInfoProvidedNoticeType": "COSMETIC",
        "cosmetic": {
          "capacity": "상세 이미지 참조",
          "specification": "상세 이미지 참조",
          "expirationDate": "제조일로부터 36개월",
          "usage": "상세 이미지 참조",
          "manufacturer": mfr,
          "customizedCosmeticReport": "해당없음",
          "caution": "상세 이미지 참조",
          "qualityAssuranceStandard": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
          "afterServiceDirector": f"{brand} 고객센터",
        },
      }

    # 기본값: WEAR
    return {
      "productInfoProvidedNoticeType": "WEAR",
      "wear": {
        "material": material,
        "color": color_text,
        "size": f"발길이(mm): {size_text}" if sizes else "FREE (상세 이미지 참조)",
        "manufacturer": mfr,
        "caution": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 사용 금지",
        "packDateText": "주문 후 개별포장 발송",
        "warrantyPolicy": "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상",
        "afterServiceDirector": f"{brand} 고객센터",
      },
    }

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
    # 제조사 정보
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

    # 소재 정보
    material = product.get("material", "") or "상세 이미지 참조"

    # 고시정보 타입 자동 판별 (카테고리/상품명 기반)
    notice_type = SmartStoreClient._detect_notice_type(product)
    notice_block = SmartStoreClient._build_notice(
      notice_type,
      product,
      material=material,
      color_text=color_text,
      size_text=size_text,
      sizes=sizes,
      mfr=mfr,
      brand=brand,
    )

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
          "productInfoProvidedNotice": notice_block,
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

## 변경 요약

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| 고시정보 타입 | `"WEAR"` 하드코딩 | 카테고리/상품명 기반 `WEAR` / `SHOES` / `COSMETIC` 자동 분기 |
| 신발 판별 | 없음 | `category`, `category1~4`, `name`에서 신발 키워드 탐색 |
| 화장품 판별 | 없음 | 동일 필드에서 화장품 키워드 탐색 |
| SHOES 고시정보 | 없음 | `shoes` 블록 생성 (`height` 필드 포함) |
| COSMETIC 고시정보 | 없음 | `cosmetic` 블록 생성 (`capacity`, `expirationDate` 등 포함) |
| 코드 구조 | 인라인 딕셔너리 | `_detect_notice_type()` + `_build_notice()` 헬퍼로 분리 |

## 참고: SambaCollectedProduct 모델 필드

`model.py`에서 카테고리 관련 필드 구조:

- `category`: 전체 카테고리 경로 (예: "신발 > 스니커즈")
- `category1` ~ `category4`: 카테고리 계층별 값
- `name`: 상품명

이 필드들을 모두 조합하여 키워드 매칭을 수행하므로, 카테고리 경로에 "신발"이 포함되거나 상품명에 "sneakers"가 포함되는 경우 등을 폭넓게 감지할 수 있다.

## 네이버 커머스 API 고시정보 타입별 필수 필드

- **WEAR**: `material`, `color`, `size`, `manufacturer`, `caution`, `packDateText`, `warrantyPolicy`, `afterServiceDirector`
- **SHOES**: `material`, `color`, `size`, `height`, `manufacturer`, `caution`, `packDateText`, `warrantyPolicy`, `afterServiceDirector`
- **COSMETIC**: `capacity`, `specification`, `expirationDate`, `usage`, `manufacturer`, `customizedCosmeticReport`, `caution`, `qualityAssuranceStandard`, `afterServiceDirector`
