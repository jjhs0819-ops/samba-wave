---
name: product-upload
description: >
  마켓플레이스에 상품을 등록·수정·판매중지·삭제하는 모든 작업에 사용.
  수집된 상품 데이터를 마켓 API 형식으로 변환(transform_product)하고 전송하는
  아웃바운드 파이프라인 전체를 다룬다.
  포함 범위: 상세페이지 HTML 생성(_build_detail_html, 상단/하단 템플릿),
  이미지 업로드 및 CDN 치환, 고시정보 타입 분기(WEAR/SHOES/COSMETIC),
  카테고리 코드 매핑, 옵션 변환, XML/JSON 포맷팅, 마켓 API 에러 처리,
  상품번호(originProductNo) 저장, 판매중지(SUSPENSION/STOP).
  대상 파일: service.py, dispatcher.py, smartstore.py, elevenst.py, coupang.py.
  제외: 소싱처 수집·파싱(→ product-parser), 주문관리, 대시보드 UI.
---

# Product Upload — 수집 상품 마켓 등록 & 등록 품질 보증

## 용어/약어

| 약어 | 정식명 | 비고 |
|------|--------|------|
| 스스 | 스마트스토어 | 사용자가 일상적으로 사용하는 약어 |
| 쿠팡 | 쿠팡 | - |
| 11번가 | 11번가(elevenst) | - |
| 롯데온 | 롯데ON(lotteon) | - |

## 이 스킬의 목적

수집·정규화된 상품(CollectedProduct)을 **마켓 API에 정상 등록하여 판매 가능 상태**로 만든다.
핵심 질문: "CollectedProduct가 마켓 API 요구사항에 맞게 변환되었는가?"

- **product-parser** = "수집 데이터 품질" (소싱처 → CollectedProduct)
- **product-upload** = "마켓 등록 품질" (CollectedProduct → 마켓 API)

## 자기 진화 규칙

**사용자가 마켓 전송 관련 수정을 요구하면, 수정 내용을 이 스킬 파일에도 반영해야 한다.**
- 새 마켓 추가 → `references/`에 마켓별 파일 추가
- 필드 매핑 변경 → `references/field-mapping.md` 업데이트
- 에러 해결 → `references/error-guide.md` 업데이트
- transform 로직 변경 → 해당 섹션 업데이트
- autoresearch 루프에서 발견된 패턴 → 체크리스트/파이프라인 섹션 보강

---

## Autoresearch 루프

마켓 전송 코드를 개발하거나 수정할 때, 아래 루프를 통해 업로드 품질을 자동 검증하고 개선한다.

### 루프 흐름

```
[1] 샘플 데이터 준비 (evals/ 디렉토리의 *-input.json 3~5개)
         ↓
[2] 전체 샘플 변환 → 업로드 체크리스트 채점 (25항목, 100점 만점)
         ↓
[3] 점수 < 95%면 → SKILL.md 또는 transform/dispatcher 코드에서 단 1가지만 수정
         ↓
[4] 다시 변환 → 점수 비교
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
ls skills/product-upload/evals/eval-*-input.json

# 2. 각 샘플에 대해 SmartStoreClient.transform_product() 실행
# 3. 출력 JSON을 expected와 비교하여 체크리스트 채점
# 4. 점수 보고 및 개선 루프 진입
```

---

## 업로드 품질 체크리스트 (25항목, 100점 만점)

`transform_product()` 출력 JSON 1건에 대해 Yes=1점, No=0점으로 채점한다.
총점 = (합계 / 25) × 100으로 환산한다.

### A. API 필수필드 (6항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| A1 | `originProduct.name` 비어있지 않은가 | `len(name) > 0` | 스마트스토어 상품명 필수 |
| A2 | `originProduct.salePrice > 0`인가 | `salePrice > 0 and isinstance(salePrice, int)` | 0이면 등록 거부 |
| A3 | `statusType == "SALE"`인가 | `statusType == "SALE"` | SUSPENSION이면 판매중지 |
| A4 | `saleType == "NEW"`인가 | `saleType == "NEW"` | 중고(USED) 아닌지 확인 |
| A5 | `representativeImage.url` 존재하는가 | `len(url) > 0` | 대표이미지 없으면 등록 거부 |
| A6 | `detailContent` 비어있지 않은가 | `len(detailContent) > 0` | 상세설명 필수 |

### B. 이미지 처리 (5항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| B1 | 대표이미지 URL이 네이버 CDN인가 | `"naver.net" in url or "pstatic.net" in url` | 업로드 완료 확인 |
| B2 | optionalImages가 4장 이하인가 | `len(optionalImages) <= 4` | 스마트스토어 제한 |
| B3 | 상세HTML 내 이미지가 네이버 CDN으로 치환되었는가 | 상세HTML 내 img src 검사 | 핫링크 차단 방지 |
| B4 | 원본 CDN URL이 상세HTML에 남아있지 않은가 | `"msscdn.net" not in detailContent` | 소싱처 CDN 잔존 확인 |
| B5 | 이미지 다운로드 시 Referer 설정이 올바른가 | 코드 검증 | msscdn.net → musinsa.com |

### C. 고시정보 변환 (5항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| C1 | `productInfoProvidedNoticeType`이 카테고리에 맞는가 | 현재: `"WEAR"` 고정 | 의류 외 카테고리 분기 미구현 |
| C2 | `material` 비어있지 않은가 | `len(material) > 0` | 폴백: "상세 이미지 참조" |
| C3 | `manufacturer` 비어있지 않은가 | `len(manufacturer) > 0` | 폴백: brand |
| C4 | `color` 비어있지 않은가 | `len(color) > 0` | 폴백: 상품명 추출 → "상세 이미지 참조" |
| C5 | `size` 비어있지 않은가 | `len(size) > 0` | 폴백: "FREE (상세 이미지 참조)" |

### D. 가격/배송 (4항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| D1 | `salePrice`가 정수인가 | `isinstance(salePrice, int)` | float이면 API 거부 |
| D2 | `deliveryCompany`가 유효 코드인가 | `deliveryCompany == "CJGLS"` | 기타: EPOST, HANJIN 등 |
| D3 | `returnDeliveryFee > 0`인가 | `returnDeliveryFee == 3000` | 현재 고정값 |
| D4 | `exchangeDeliveryFee > 0`인가 | `exchangeDeliveryFee == 6000` | 현재 고정값 |

### E. 카테고리/옵션 (3항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| E1 | `leafCategoryId`가 숫자 코드인가 | `category_id.isdigit()` | 경로 문자열이면 API 거부 |
| E2 | `stockQuantity > 0`인가 | `stockQuantity == 999` | 현재 고정값 |
| E3 | `channelProductName` 비어있지 않은가 | `len(channelProductName) > 0` | 스토어 노출 상품명 |

### F. 마켓 호환 (2항목)

| # | 체크 항목 | 검증 방법 | 근거 |
|---|----------|----------|------|
| F1 | `originAreaInfo.content` 비어있지 않은가 | `len(content) > 0` | 폴백: "해외" |
| F2 | `afterServiceInfo` 필드가 존재하는가 | 딕셔너리 키 존재 확인 | 필수 항목 |

---

### 채점 가중치 & 해석

| 카테고리 | 항목수 | 비중 |
|---------|-------|------|
| A. API 필수필드 | 6 | 24% |
| B. 이미지 처리 | 5 | 20% |
| C. 고시정보 변환 | 5 | 20% |
| D. 가격/배송 | 4 | 16% |
| E. 카테고리/옵션 | 3 | 12% |
| F. 마켓 호환 | 2 | 8% |
| **합계** | **25** | **100%** |

```
점수 계산: score = (통과항목수 / 25) × 100

해석:
  95~100%  → 마켓 등록 가능 (autoresearch 종료)
  80~94%   → 고시정보 타입 또는 이미지 치환 문제
  60~79%   → 필수필드 또는 카테고리 매핑 오류
  < 60%    → transform_product 기본 동작 불량
```

### 샘플별 예외 허용

B1/B3/B4(이미지 CDN 치환)는 `transform_product()` 단독 실행 시 검증 불가하다.
이 항목들은 `_handle_smartstore()` 통합 테스트에서만 채점하며,
transform 단독 테스트에서는 자동 pass 처리한다.

```python
TRANSFORM_ONLY_EXEMPTIONS = ["B1", "B3", "B4", "B5"]
# transform_product() 단독 테스트 시 이 항목들은 자동 통과
# _handle_smartstore() 통합 테스트에서만 실제 채점
```

---

## 업로드 파이프라인 아키텍처

전체 흐름은 `service.py → dispatcher.py → {market_proxy}.py` 순으로 진행된다.

```
[1] 필수필드 검증 (dispatcher.validate_transform)
    → name, sale_price 확인
    → 누락 시 즉시 반환 {"success": False, "error_type": "schema_changed"}

[2] 상세페이지 HTML 생성 (service._build_detail_html)
    → 정책 템플릿(상단/하단 이미지) + 상품 이미지 조합
    → 구조: top_image → images[0] → images[1:] → detail_images → bottom_image
    → 폴백: <p>{상품명}</p>

[3] 카테고리 매핑 조회 (service._resolve_category_mappings)
    → DB 매핑 우선 (SambaCategoryMappingRepository.find_mapping)
    → 없으면 키워드 자동 제안 (SambaCategoryService.suggest_category)
    → 결과: {market_type: category_code} dict

[4] 정책 기반 계정 필터링
    → product.applied_policy_id → policy.market_policies
    → MARKET_TYPE_TO_POLICY_KEY 역매핑 (영문 → 한글, 18개)
    → 정책에 지정된 accountIds만 전송 대상

[5] 이미지 업로드 (CDN → 마켓 서버)
    → 스마트스토어: 외부 URL → 네이버 이미지 서버 업로드
    → 대표이미지 + 추가이미지(최대 5장) 순차 업로드
    → 상세HTML 내 <img src> URL도 정규식으로 추출 → 네이버 URL로 치환
    → Referer 설정: msscdn.net → "https://www.musinsa.com/"
    → CDN 차단 감지: 응답 < 1000B → SmartStoreApiError

[6] 데이터 변환 (SmartStoreClient.transform_product)
    → CollectedProduct dict → 스마트스토어 JSON 포맷
    → 고시정보, 배송정보, 이미지 등 전체 매핑

[7] API 호출 (SmartStoreClient.register_product)
    → POST /v2/products
    → 에러 시 invalidInputs 배열 파싱

[8] 결과 처리
    → 상품번호 추출: originProductNo > productNo > smartstoreChannelProductNo
    → market_product_nos에 {account_id: product_no} 저장
    → registered_accounts 업데이트
    → 전체 성공="completed", 전체 실패="failed", 혼합="partial"
    → 성공 계정 있으면 product.status = "registered"
```

### 상세 HTML 생성 구조

```html
<!-- 상단 이미지 (정책 템플릿) -->
<div style="text-align:center;">
  <img src="{top_image_s3_key}" style="max-width:860px;width:100%;" />
</div>

<!-- 대표이미지 -->
<div style="text-align:center;">
  <img src="{images[0]}" style="max-width:860px;width:100%;" />
</div>

<!-- 추가이미지 -->
<div style="text-align:center;">
  <img src="{images[1:]}" style="max-width:860px;width:100%;" />
</div>

<!-- 상세 이미지 (소싱처 수집) -->
<div style="text-align:center;">
  <img src="{detail_images[]}" style="max-width:860px;width:100%;" />
</div>

<!-- 하단 이미지 (정책 템플릿) -->
<div style="text-align:center;">
  <img src="{bottom_image_s3_key}" style="max-width:860px;width:100%;" />
</div>
```

---

## CollectedProduct → 스마트스토어 필드 매핑 요약

상세는 `references/field-mapping.md` 참조.

| CollectedProduct | 스마트스토어 | 폴백 |
|---|---|---|
| `name` | `originProduct.name` + `channelProductName` | (필수, 폴백 없음) |
| `sale_price` | `originProduct.salePrice` | `original_price` → `10000` |
| `images[0]` | `representativeImage.url` | (필수) |
| `images[1:5]` | `optionalImages` | (선택, 최대 4장) |
| `detail_html` | `detailContent` | `<p>{name}</p>` |
| `origin` | `originAreaInfo.content` | `"해외"` |
| `material` | `wear.material` | `"상세 이미지 참조"` |
| `color` | `wear.color` | 상품명에서 ` - ` 뒤 추출 → `"상세 이미지 참조"` |
| `manufacturer` | `wear.manufacturer` | `brand` |
| `brand` | `afterServiceDirector` 텍스트 | `"상세설명 참조"` |
| `options[].name/size` | `wear.size` (쉼표 연결) | `"FREE (상세 이미지 참조)"` |
| `tags` | `detailAttribute.seoInfo.sellerTags` | **최대 10개**, 시스템마커·브랜드·상품명·카테고리 포함 태그 자동 제외 |

---

## 마켓 핸들러 인벤토리 (18개 등록)

### 완전 구현 (8개)

| 마켓 | 코드 | 인증 방식 | 데이터 포맷 | 참조 |
|------|------|----------|-----------|------|
| 스마트스토어 | `smartstore` | OAuth2 + bcrypt 서명 | JSON | → `references/smartstore.md` |
| 쿠팡 | `coupang` | HMAC-SHA256 | JSON | → `references/coupang.md` |
| 11번가 | `11st` | OpenAPI Key 헤더 | XML | → `references/elevenst.md` |
| 롯데ON | `lotteon` | Bearer API Key | JSON | → `references/lotteon.md` |
| SSG(신세계) | `ssg` | API Key | JSON | storeId 기본 "6004" |
| 롯데홈쇼핑 | `lottehome` | userId/password | JSON | agncNo/env 필요 |
| GS샵 | `gsshop` | supCd/aesKey | JSON | subSupCd/env 필요 |
| KREAM | `kream` | token/cookie | JSON | 사이즈별 매도 입찰 |

### 신규 구현 (4개, 2026-03-24)

| 마켓 | 코드 | 인증 방식 | 비고 |
|------|------|----------|------|
| 토스 | `toss` | HMAC-SHA256 | JSON, 실 테스트 필요 |
| 라쿠텐 | `rakuten` | ESA Base64 | JSON 2.0 우선, XML 폴백 |
| 아마존 | `amazon` | LWA OAuth | Listings API, AWS SigV4 미구현(추후) |
| 바이마 | `buyma` | 없음 (CSV) | API 없음, CSV 생성 방식 |

### 스텁 (6개, API 연동 미구현)

| 마켓 | 코드 | 상태 |
|------|------|------|
| eBay | `ebay` | 스텁 |
| Lazada | `lazada` | 스텁 |
| Qoo10 | `qoo10` | 스텁 |
| Shopee | `shopee` | 스텁 |
| Shopify | `shopify` | 스텁 |
| Zum(줌) | `zoom` | 스텁 |

### 미지원 (공개 API 없음)

`gmarket`, `auction`, `homeand`, `hmall` — 파트너 계약 또는 연동솔루션 필요

### 삭제/판매중지 구현 (4개)

| 마켓 | 방식 |
|------|------|
| `smartstore` | `statusType: "SUSPENSION"` |
| `coupang` | `statusType: "STOP"` |
| `lottehome` | `update_sale_status(product_no, "02")` |
| `gsshop` | `update_sale_status(product_no, "02")` |

---

## 트러블슈팅 의사결정 트리

코드를 읽지 않고도 문제 원인을 빠르게 좁힐 수 있는 분기 트리.

### 이미지가 안 보일 때

```
이미지가 안 보인다
├─ 서버 로그에 "이미지가 비정상적으로 작음" 경고?
│  └─ YES → CDN 핫링크 차단. Referer 설정 확인
│     └─ msscdn.net → Referer는 "https://www.musinsa.com/" (코드 정상)
│     └─ 다른 CDN → 해당 도메인을 Referer 특수 처리에 추가 필요
├─ 대표이미지 URL이 비어있다?
│  └─ YES → 모든 이미지 업로드가 except로 스킵됨
│     └─ 원인: Content-Type 미검증으로 HTML 차단 페이지를 이미지로 인식 실패
│     └─ 해결: content_type.startswith("image/") 검증 추가 (현재 미구현)
├─ 상세페이지 이미지만 깨진다?
│  └─ YES → 상세 HTML 내 소싱처 CDN URL이 네이버 URL로 치환 안 됨
│     └─ 원인: upload_image_from_url 실패 시 원본 URL 잔존
│     └─ 확인: 상세HTML에서 msscdn.net/kream 등 외부 도메인 검색
└─ 전부 안 보인다?
   └─ OAuth 토큰 만료 또는 네이버 이미지 서버 장애 가능성
```

### API 에러가 발생할 때

```
상품 등록 실패
├─ "leafCategoryId: 유효하지 않은 카테고리"?
│  └─ isdigit() 통과했지만 네이버에서 폐지된 코드
│     └─ 해결: 카테고리 매핑 페이지에서 유효 코드 재설정
│     └─ retransmit()에서 카테고리 매핑 재조회하므로 재전송 가능
├─ "필수필드 누락: name, sale_price"?
│  └─ validate_transform() 사전 검증에서 차단
│     └─ 수집 데이터 자체에 문제 → product-parser 스킬 참조
├─ "토큰 발급 실패"?
│  └─ auth_failed. client_id/client_secret 확인
│     └─ client_secret은 bcrypt salt 형식($2b$...)이어야 함
├─ HTTP 400 + invalidInputs?
│  └─ schema_changed. invalidInputs 배열에서 정확한 필드/메시지 확인
│     └─ 네이버 API는 [{"field":"...", "message":"..."}] 형태로 상세 에러 제공
├─ "어린이제품 인증대상 인증 종류를 선택하셔야 합니다"?
│  └─ 카테고리가 어린이제품 인증 필수 카테고리
│     └─ 해결: 카테고리 API에서 certificationInfos 조회 → productCertificationInfos 자동 생성 (2026-03-22 구현 완료)
│     └─ _build_certification_infos()가 카테고리별 인증유형(CHILD_CERTIFICATION 등)에 기본값 "해당사항없음" 설정
└─ timeout/connect 에러?
   └─ network. retransmit()으로 재시도 가능
```

### 고시정보 관련 문제

```
고시정보 타입 불일치
├─ 현재 구현: WEAR 하드코딩 (smartstore.py L508)
├─ 신발 상품인데 WEAR로 등록?
│  └─ _determine_notice_type() 분기 구현 필요
│  └─ SHOES 필수 필드: material, color, size, height, manufacturer
├─ 화장품인데 WEAR로 등록?
│  └─ COSMETIC 필수 필드: capacity, mainIngredient, expirationDate, manufacturer
│  └─ 주의: COSMETIC은 의류와 완전히 다른 필드 구조
└─ 폴백값("상세 이미지 참조")이 너무 많다?
   └─ 수집 단계에서 고시정보 추출 강화 → product-parser 스킬 참조
```

---

## 실전 함정 (코드만으로 발견하기 어려운 것들)

이 섹션은 코드 리뷰나 디버깅에서 놓치기 쉬운 패턴을 모은 것이다. 코드를 읽으면 동작은 이해할 수 있지만, "왜 이렇게 해야 하는지"는 이 컨텍스트 없이는 알기 어렵다.

### 1. 이미지 업로드 실패의 조용한 전파

`_handle_smartstore()`에서 이미지 업로드 실패가 `except Exception`으로 잡히고 warning만 남긴다. 대표이미지(images[0])가 실패하면 `naver_images`가 빈 배열이 되고, `transform_product()`에서 `representativeImage`가 빈 dict `{}`가 된다. 이 상태로 register_product()가 호출되면 네이버 API가 "대표이미지 필수" 에러를 반환한다. **하지만 에러 메시지에는 CDN 차단이 원인이라는 힌트가 없어서** 원인 추적이 어렵다.

### 2. 상세 HTML은 service에서 재생성된다

수집된 `detail_html`은 `_transmit_product()`에서 항상 `_build_detail_html()`로 재생성된다(service.py L145). 소싱처 CDN URL이 포함된 원본 HTML은 무시되고, 정책 템플릿(상단/하단) + images + detail_images로 새로 조합된다. **따라서 detail_html 필드를 직접 수정해도 전송 시 반영되지 않는다.**

### 3. retransmit()은 카테고리를 재조회한다 (2026-03-22 수정)

`service.py:retransmit()`에서 `_resolve_category_mappings()`를 재호출하여 실패 계정의 카테고리를 정상 전달한다. 이전에는 `category_id=""`로 호출하여 항상 실패했다.

### 4. 네이버 API의 originProductNo vs productNo

상품 등록 응답에서 `originProductNo`와 `productNo`가 다르다. 수정/삭제 API는 `originProductNo`를 사용해야 한다. service.py에서 우선순위가 `originProductNo > productNo > smartstoreChannelProductNo`로 올바르게 설정되어 있다. 이 순서를 변경하면 판매중지가 안 된다.

### 5. 정책 기반 계정 필터링의 역매핑

`MARKET_TYPE_TO_POLICY_KEY`는 영문 market_type → 한글 정책 키 역매핑이다(예: `'smartstore': '스마트스토어'`). 이 매핑에 없는 마켓 계정은 **정책 필터링에서 자동 제외**된다. 새 마켓을 추가할 때 이 매핑도 반드시 업데이트해야 한다.

### 6. 스마트스토어 상품 수정/조회 API 경로는 origin-products 필수

네이버 커머스 API에서 상품 등록은 `POST /v2/products`이지만, **수정/조회/삭제는 `/v2/products/origin-products/{originProductNo}`** 경로를 사용해야 한다. `/v2/products/{product_no}`는 존재하지 않아 404를 반환한다. `update_product()`와 `get_product()` 모두 이 경로를 사용해야 한다. (2026-03-20 수정 완료)

### 7. 정책 미적용 상품 전송 차단

`applied_policy_id`가 없는 상품은 전송이 차단된다(프론트+백엔드 양쪽). 정책 없이 전체 선택 계정으로 전송되던 이전 동작은 제거되었다. 사용자가 반드시 정책을 적용한 후 전송해야 한다. (2026-03-20 추가)

### 9. 롯데ON API는 2단계 응답 구조를 사용한다

롯데ON API는 등록 실패 시에도 HTTP 200을 반환한다. 응답은 2단계 구조:
- **1단계**: `returnCode` — 요청 레벨 (예: 필수파라미터 누락). `_call_api()`에서 `returnCode not in ("0000", "00", "SUCCESS")`이면 `LotteonApiError` 발생.
- **2단계**: `data[].resultCode` — 개별 상품 레벨 (예: 카테고리 매핑 오류, 배송권역 누락). `register_product()`/`update_product()`에서 `data[0].resultCode != "0000"`이면 `LotteonApiError` 발생. 이전에는 이 검증이 없어서 실패한 등록도 성공으로 표기되었다.
- **상품번호**: 성공 시 `data[0].spdNo`에 담기며, `register_product()`가 `result["spdNo"]`로 직접 반환. service.py에서도 `result.get("spdNo")`로 우선 추출. (2026-03-21 수정)

### 8. 카테고리 매핑 없으면 해당 마켓 전송 차단

`mapped_categories`에서 해당 마켓의 카테고리 코드가 빈 문자열이면 해당 계정 전송을 스킵하고 "카테고리 매핑 없음" 에러를 기록한다. 이전에는 빈 카테고리로 API를 호출하여 마켓 측에서 에러가 발생했다. (2026-03-20 추가)

### 10. 롯데홈쇼핑 API 특이사항

**인증 & 인코딩:**
- 인증: `createCertification.lotte` POST → certkey 24시간 유효
- 모든 요청: EUC-KR 인코딩 필수 (`Content-Type: application/x-www-form-urlencoded; charset=euc-kr`)
- 응답: XML (EUC-KR)

**테스트서버 제약 (2026-03-24 확인):**
- 테스트 URL: `http://openapitst.lotteimall.com/openapi/`
- 운영 URL: `https://openapi.lotteimall.com/openapi/`
- 테스트서버에서 **인증 + 상품등록** API만 외부 접근 가능
- 조회 API (배송지/카테고리/브랜드/MD 등)는 HTML 로그인 페이지 반환 (내부망 전용 추정)
- 출고지/반품지 등록 API(`registDlvpOpenApi.lotte`)는 "사전협의된 특정 업체만 사용 가능" (에러 2062)
- 파트너 관리자 페이지(`partnertst.lotteimall.com`)도 외부 접속 불가

**필수 파라미터 3종 (상품등록 시):**
- `dlv_polc_no`: 배송정책번호 — `searchDlvPolcListOpenApi.lotte`로 조회 (테스트서버 조회 불가, 수동 입력 필요)
- `corp_dlvp_sn`: 반품지번호 — `searchReturnListOpenApi.lotte?dlvp_tp_cd=10` (기본반품지) 또는 `30` (반품지)
- `corp_rls_pl_sn`: 출고지번호 — `searchReturnListOpenApi.lotte?dlvp_tp_cd=40` (기본출고지) 또는 `50` (출고지)
- **주의**: 배송지 조회 API는 `searchDlvPlcListOpenApi`가 아니라 `searchReturnListOpenApi`가 올바른 엔드포인트
- `_handle_lottehome`에서 creds에 값 없으면 자동 조회 로직 구현 완료 (2026-03-24)

**안전인증 파라미터:**
- `sft_cert_tgt_seq`: 안전인증대상일련번호 — 품목코드별 `searchGoodsArtcOpenApi.lotte`에서 TgtSeq 조회
- 병행수입(`prl_imp_yn=Y`)이거나 안전인증대상이 없으면 빈값 허용
- `sft_cert_sct_cd`: 안전인증구분코드 — 필수여부(MdtYn)가 Y인 경우만 필수
- `sft_cert_no`: 안전인증번호 — 선택

**전시카테고리:**
- `disp_no`: 전시번호 — 필수. `searchDispNoListOpenApi.lotte`로 조회
- `md_gsgr_no`와 별도. MD상품군번호 ≠ 전시번호
- 테스트서버 테스트 시 전시번호를 롯데홈쇼핑 담당자에게 별도 확인 필요

**테스트 계정 (2026-03-24 확인):**
- userId: `037800LT`, password: `037800LT`, agncNo: `037800LT`
- 테스트서버: 전시카테고리 `5157537`, MD상품군 `24973` (조회API 대부분 차단)
- 테스트서버: 배송지/배송정책 등록 불가 (API 권한 없음 + 조회 API 차단)

**운영 계정 (2026-03-24 등록 성공):**
- userId: `037800LT`, password: `gemini0674@@`, agncNo: `037800LT`, env: `prod`
- MD코드: `220056` (최예지), MD상품군: `334` (스니커즈/운동화)
- 전시카테고리: `5158302` (롯데아이몰 > 패션슈즈 > 스니커즈/운동화 > 런닝화/워킹화)
- 배송정책번호: `3673192`
- 반품지번호: `1967053`
- 출고지번호: `1967054`
- 등록 성공: goods_no `3270343975`

**전시카테고리 ↔ 표준카테고리 매핑:**
- API: `loadStdCatsByDispNo.lotte?subscriptionId=[인증키]&disp_no=[전시카테고리번호]`
- 전시카테고리 1개 → 표준카테고리 N개 매핑 가능
- 응답: `StdCatInfoLst > StdCatInfo[]` — `StdCatNo`(표준카테고리번호), `FullStdCatNm`(전체 경로)
- 표준카테고리는 `BH` prefix + 8자리 코드 (예: `BH34090700`)

**에러 코드:**
| 코드 | 메시지 | 원인 |
|------|--------|------|
| 9001 | 인증에 실패하였습니다 | userId/password 오류 |
| 1032 | 출고배송지가 입력되지 않았습니다 | corp_rls_pl_sn 빈값 |
| 1005 | 필수 전시번호가 입력되지 않았습니다 | disp_no 빈값 |
| 1018 | 대표 전시매장이 올바르지 않습니다 | disp_no 잘못된 값 |
| 2013 | 안전인증대상일련번호 오류 | sft_cert_tgt_seq 잘못된 값 |
| 2062 | 출고지/반품배송지 등록 API 사용 불가 | API 등록 권한 없는 협력사 |
| 0005 | 필수파라미터 오류 | dlvp_tp_cd 등 누락 |
| 0001 | 인증키오류 | 인증키 만료/미존재 |
| 5001 | 유효기한 초과 | 인증키 24시간 초과 |

---

## 알려진 제한사항

1. **고시정보 타입 하드코딩:** `WEAR` 고정 → 신발(SHOES)/화장품(COSMETIC)/가방(BAG) 카테고리 분기 미구현
2. **옵션 전달 구현 완료:** 옵션 2개 이상이면 `optionInfo.optionCombinations`으로 사이즈별 재고/품절 전달. 옵션 1개(단일)이면 옵션 없이 등록.
3. **이미지 순차 업로드:** `asyncio.gather` 병렬화 미적용. 이미지 많을수록 느림
4. **11번가 이미지:** 외부 URL 직접 사용. 별도 업로드 미구현
5. **쿠팡 반품센터:** `returnCenterCode` 동적 조회 미구현 (빈값)
6. ~~**재전송 카테고리:** `retransmit()` 시 카테고리 빈값으로 전달됨~~ → 2026-03-22 수정 완료

---

## 주요 참조 파일

| 파일 | 역할 |
|------|------|
| `skills/product-parser/SKILL.md` | 패턴 참조 (프론트매터, autoresearch, 체크리스트 구조) |
| `backend/.../proxy/smartstore.py` | `transform_product()`, `upload_image_from_url()` |
| `backend/.../proxy/elevenst.py` | 11번가 XML 변환 |
| `backend/.../proxy/coupang.py` | 쿠팡 JSON 변환, HMAC 서명 |
| `backend/.../shipment/dispatcher.py` | 마켓 라우팅, 필수필드 검증, 에러 분류 |
| `backend/.../shipment/service.py` | 전체 파이프라인, `_build_detail_html`, `_resolve_category_mappings` |
| `backend/.../collector/model.py` | `SambaCollectedProduct` 스키마 |

---

## 변경 이력

| 날짜 | 내용 | autoresearch 점수 |
|------|------|-----------------|
| 2026-03-20 | 초안 작성. 스마트스토어 기준 25항목 체크리스트 + 파이프라인 아키텍처 | - |
| 2026-03-20 | autoresearch 실행 — eval-1(의류완비) 100%, eval-2(폴백) 100%, eval-3(CDN이미지) 100% | 100% |
| 2026-03-20 | skill-creator 벤치마크 실행. 트러블슈팅 의사결정 트리 + 실전 함정 5가지 추가 | - |
| 2026-03-20 | description 최적화 — 행동 중심 + 함수명 키워드 + 범위 명확화 | - |
| 2026-03-20 | 판매중지 404 버그 수정: update_product/get_product API 경로 `/v2/products/origin-products/` 로 변경 | - |
| 2026-03-20 | 정책 미적용 상품 전송 차단 + 카테고리 매핑 없으면 전송 차단 로직 추가 | - |
| 2026-03-21 | 롯데ON 등록 거짓 성공 버그 수정: _call_api에 returnCode 체크 추가, register/update_product에 data[].resultCode 검증 추가, service.py data 리스트 처리 | - |
| 2026-03-21 | 스마트스토어 태그 등록 수정: 시스템 마커(__ai_tagged__ 등) 필터링 후 sellerTags 전송 | - |
| 2026-03-21 | 스마트스토어 옵션 등록 구현: options → optionInfo.optionCombinations (사이즈별 재고/품절, _max_stock 반영) | - |
| 2026-03-21 | 스마트스토어 태그 위치 버그 수정: sellerTags를 originProduct.detailAttribute 하위로 이동 (seoInfo 내부 X, 최상위 X) — Context7 API 스펙 검증 | - |
| 2026-03-21 | 스마트스토어 반품안심케어 버그 수정: returnSafeguardType(존재하지 않는 필드) → claimDeliveryInfo 내 freeReturnInsuranceYn: true — Context7 API 스펙 검증 | - |
| 2026-03-21 | 글로벌 삭제어(SambaForbiddenWord) 상품 전송 시 적용: service._transmit_product에서 상품명 조합 후 삭제어 제거 추가 | - |
| 2026-03-22 | retransmit() 카테고리 재조회 버그 수정: category_id="" → _resolve_category_mappings() 재호출 + account 전달 | - |
| 2026-03-22 | 어린이제품 인증정보 자동 설정: 카테고리 API에서 certificationInfos 조회 → productCertificationInfos 자동 생성 (_build_certification_infos) | - |
| 2026-03-24 | 롯데홈쇼핑 배송지/출고지/반품지 자동 조회 구현: _handle_lottehome에서 creds 빈값 시 searchReturnListOpenApi 자동 조회. 배송지 조회 엔드포인트 수정 (searchDlvPlcListOpenApi → searchReturnListOpenApi) | - |
| 2026-03-24 | 롯데홈쇼핑 테스트서버 연동 검증: 인증 성공, 배송지 통과, 안전인증(sft_cert_tgt_seq 빈값+prl_imp_yn=Y) 통과, 전시카테고리(disp_no) 미해결 — 테스트서버 조회API 외부차단 | - |
| 2026-03-24 | 스킬 문서에 롯데홈쇼핑 API 특이사항 + 에러코드 + 테스트계정 + 전시-표준카테고리 매핑API 추가 | - |
| 2026-03-24 | 4개 마켓 상품등록 구현: 토스(HMAC-SHA256), 라쿠텐(ESA), 아마존(LWA OAuth), 바이마(CSV) — 프록시 4개 + dispatcher 핸들러 4개 + UI 마켓목록 추가 | - |
