# CollectedProduct → 마켓 필드 매핑 테이블

소스 파일:
- `smartstore.py` → `transform_product()` (라인 423~516)
- `elevenst.py` → `transform_product()` (라인 119~185)
- `coupang.py` → `transform_product()` (라인 141~230)
- `dispatcher.py` → `_transform_for_lottehome()`, `_transform_for_gsshop()`

---

## CollectedProduct 전체 필드 목록 (32개)

소스: `backend/backend/domain/samba/collector/model.py`

### 기본 정보

| # | 필드명 | 타입 | 설명 | 마켓 등록 사용 |
|---|--------|------|------|-------------|
| 1 | `id` | str (PK) | `cp_{ULID}` 형식 | - |
| 2 | `source_site` | Text | 소싱처 식별자 | 카테고리 매핑 조회 키 |
| 3 | `search_filter_id` | Text | 검색필터 참조 | - |
| 4 | `site_product_id` | Text | 소싱처 상품번호 | - |
| 5 | `name` | Text | 상품명 | **필수** (모든 마켓) |
| 6 | `name_en` | Text | 영문 상품명 | 해외 마켓용 |
| 7 | `name_ja` | Text | 일본어 상품명 | 해외 마켓용 |
| 8 | `brand` | Text | 브랜드명 | 고시정보 폴백, A/S 정보 |

### 가격

| # | 필드명 | 타입 | 설명 | 마켓 등록 사용 |
|---|--------|------|------|-------------|
| 9 | `original_price` | float | 정가 | salePrice 폴백 |
| 10 | `sale_price` | float | 판매가 | **필수** (모든 마켓) |
| 11 | `cost` | float | 원가 | 마진 계산용 |

### 콘텐츠

| # | 필드명 | 타입 | 설명 | 마켓 등록 사용 |
|---|--------|------|------|-------------|
| 12 | `images` | JSON (List[str]) | 대표+추가 이미지 URL | 대표/추가 이미지 |
| 13 | `detail_images` | JSON (List[str]) | 상세페이지 이미지 URL | 상세HTML 생성 |
| 14 | `options` | JSON (List) | 사이즈/옵션 배열 | 사이즈 텍스트 추출 |
| 15 | `detail_html` | Text | 상세설명 HTML | 상세페이지 (재생성됨) |

### 카테고리

| # | 필드명 | 타입 | 설명 | 마켓 등록 사용 |
|---|--------|------|------|-------------|
| 16 | `category` | Text | 전체 경로 | 매핑 조회 키 |
| 17~20 | `category1~4` | Text | 1~4뎁스 | - |

### 상태/관리

| # | 필드명 | 타입 | 설명 | 마켓 등록 사용 |
|---|--------|------|------|-------------|
| 21 | `status` | Text | collected/saved/registered | 등록 후 "registered" |
| 22 | `applied_policy_id` | Text | 적용 정책 ID | 계정 필터링, 상세 템플릿 |
| 23 | `market_prices` | JSON | 마켓별 가격 | - |
| 24 | `market_enabled` | JSON | 마켓별 활성화 | - |
| 25 | `registered_accounts` | JSON (List[str]) | 등록된 계정 ID 목록 | 등록 후 업데이트 |
| 26 | `market_product_nos` | JSON | {account_id: product_no} | 삭제/수정 시 사용 |

### 고시정보

| # | 필드명 | 타입 | 설명 | 마켓 등록 사용 |
|---|--------|------|------|-------------|
| 27 | `manufacturer` | Text | 제조사 | 고시정보 manufacturer |
| 28 | `origin` | Text | 원산지 | 고시정보 origin |
| 29 | `material` | Text | 소재 | 고시정보 material |
| 30 | `color` | Text | 색상 | 고시정보 color |

### 기타

| # | 필드명 | 타입 | 설명 |
|---|--------|------|------|
| 31 | `kream_data` | JSON | KREAM 전용 데이터 |
| 32 | `is_sold_out` | bool | 품절 여부 |

---

## 마켓별 매핑 (상세는 개별 파일 참조)

| 마켓 | 포맷 | 이미지 제한 | 상세 참조 |
|------|------|-----------|----------|
| 스마트스토어 | JSON | 대표1 + 추가4 = 5장 | → `references/smartstore.md` |
| 11번가 | XML | 메인1 + 추가3 = 4장 | → `references/elevenst.md` |
| 쿠팡 | JSON | 최대 10장 | → `references/coupang.md` |
| 롯데홈쇼핑 | JSON | 1장 | dispatcher 내 인라인 변환 |
| GS샵 | JSON | 1장 | dispatcher 내 인라인 변환 |

### 롯데홈쇼핑 (인라인)

소스: `dispatcher.py:_transform_for_lottehome()` (라인 402~413)

| CollectedProduct | 롯데홈쇼핑 필드 |
|---|---|
| `name` | `goods_nm` |
| `sale_price` | `sel_price` (문자열 변환) |
| `category_code` | `disp_ctgr_no` |
| `brand` | `brand_nm` |
| `images[0]` | `goods_img_url` |
| `detail_html` | `goods_detail` |

### GS샵 (인라인)

소스: `dispatcher.py:_transform_for_gsshop()` (라인 416~427)

| CollectedProduct | GS샵 필드 |
|---|---|
| `name` | `prdNm` |
| `brand` | `brndNm` |
| `sale_price` | `selPrc` (int 변환) |
| `category_code` | `dispCtgrNo` |
| `images[0]` | `prdCntntListCntntUrlNm` + `mobilBannerImgUrl` |
| `detail_html` | `prdDetailCntnt` |

---

## 고시정보 타입별 필드

### WEAR (의류) — 현재 구현

```json
{
  "productInfoProvidedNoticeType": "WEAR",
  "wear": {
    "material": "소재",
    "color": "색상",
    "size": "치수",
    "manufacturer": "제조사/수입사",
    "caution": "취급 주의사항",
    "packDateText": "포장일",
    "warrantyPolicy": "품질보증기준",
    "afterServiceDirector": "A/S 책임자"
  }
}
```

### SHOES (신발) — 미구현

```json
{
  "productInfoProvidedNoticeType": "SHOES",
  "shoes": {
    "material": "소재 (겉감/안감/밑창)",
    "color": "색상",
    "size": "치수 (발길이mm)",
    "height": "굽 높이",
    "manufacturer": "제조사/수입사",
    "caution": "취급 주의사항",
    "warrantyPolicy": "품질보증기준",
    "afterServiceDirector": "A/S 책임자"
  }
}
```

### BAG (가방) — 미구현

```json
{
  "productInfoProvidedNoticeType": "BAG",
  "bag": {
    "material": "소재",
    "color": "색상",
    "size": "크기",
    "manufacturer": "제조사/수입사",
    "caution": "취급 주의사항",
    "warrantyPolicy": "품질보증기준",
    "afterServiceDirector": "A/S 책임자"
  }
}
```

### COSMETIC (화장품) — 미구현

```json
{
  "productInfoProvidedNoticeType": "COSMETIC",
  "cosmetic": {
    "capacity": "내용물의 용량 또는 중량",
    "mainIngredient": "주요 성분",
    "functionality": "기능성 화장품 여부",
    "expirationDate": "사용기한 또는 개봉 후 사용기간",
    "usageDirection": "사용방법",
    "manufacturer": "제조업자/수입자",
    "manufacturedCountry": "제조국",
    "caution": "사용 시 주의사항"
  }
}
```

---

## 마켓별 제한사항

| 항목 | 스마트스토어 | 11번가 | 쿠팡 |
|------|-----------|--------|------|
| 상품명 길이 | 100자 | 100자 | 200자 |
| 대표 이미지 | 1장 (업로드 필수) | 1장 (외부 URL) | 10장 (외부 URL) |
| 추가 이미지 | 최대 4장 | 최대 3장 | (대표에 포함) |
| 이미지 형식 | JPG/PNG/WebP | JPG/PNG | JPG/PNG |
| 상세설명 | HTML | HTML (CDATA) | HTML |
| 옵션 | combinationOption (미사용) | sellerOption | items 배열 |
| 재고 | 고정 999 | 옵션별 stockQty | 옵션별 quantity |
| 배송비 | FREE/CONDITIONAL | DV_FREE 등 | FREE/CONDITIONAL |
| 반품비 | 3,000원 | 5,000원 | 5,000원 |
| 교환비 | 6,000원 | 5,000원 | - |
| 인증 | OAuth2+bcrypt | API Key 헤더 | HMAC-SHA256 |
| 데이터 포맷 | JSON | XML | JSON |

---

## 폴백 체인 전체 테이블

데이터 변환 시 값이 비어있을 때 적용되는 폴백 순서:

| 필드 | 1순위 | 2순위 | 최종 폴백 |
|------|-------|-------|----------|
| `salePrice` | `sale_price` | `original_price` | `10000` |
| `brand` | `brand` | - | `"상세설명 참조"` |
| `manufacturer` | `manufacturer` | `brand` | `"상세설명 참조"` |
| `material` | `material` | - | `"상세 이미지 참조"` |
| `color` | DB `color` 필드 | 상품명 ` - ` 뒤 추출 | `"상세 이미지 참조"` |
| `size` | 옵션 사이즈 쉼표 연결 | - | `"FREE (상세 이미지 참조)"` |
| `origin` | `origin` | - | `"해외"` (스마트스토어) / `"기타"` (11번가) |
| `detailContent` | `detail_html` | - | `<p>{name}</p>` |
| `category_id` | DB 매핑 조회 | 키워드 자동 제안 | `"50000803"` (스마트스토어 기본) |
