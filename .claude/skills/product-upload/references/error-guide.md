# 마켓별 에러 분류 + 해결 가이드

소스: `backend/backend/domain/samba/shipment/dispatcher.py` (라인 93~109)

---

## 에러 분류 체계

디스패처는 예외 메시지를 분석하여 4가지 타입으로 분류한다:

| 타입 | 감지 키워드 | 의미 | 대응 |
|------|-----------|------|------|
| `auth_failed` | `401`, `403`, `unauthorized`, `인증` | 인증 실패 | API 키/토큰 재발급 |
| `schema_changed` | `400`, `422`, `필수`, `required` | API 스펙 불일치 | transform 로직 수정 |
| `network` | `timeout`, `connect`, `network` | 네트워크 에러 | 재전송 (retransmit) |
| `unknown` | (그 외 모든 에러) | 미분류 | 로그 확인 |

```python
# dispatcher.py 라인 93~109
except Exception as exc:
  exc_str = str(exc).lower()
  if "401" in exc_str or "403" in exc_str or "unauthorized" in exc_str or "인증" in exc_str:
    error_type = "auth_failed"
  elif "400" in exc_str or "422" in exc_str or "필수" in exc_str or "required" in exc_str:
    error_type = "schema_changed"
  elif "timeout" in exc_str or "connect" in exc_str or "network" in exc_str:
    error_type = "network"
  else:
    error_type = "unknown"
```

---

## 스마트스토어 흔한 에러 10가지

### 1. 토큰 발급 실패

**에러:** `SmartStoreApiError: 토큰 발급 실패: Unauthorized`
**분류:** `auth_failed`
**원인:** client_id 또는 client_secret 오류. bcrypt salt 형식 불일치.
**해결:**
- 네이버 커머스 API 센터에서 애플리케이션 키 재확인
- `client_secret`은 bcrypt salt 형식이어야 함 (`$2b$...`)
- 계정 설정 페이지에서 재입력 후 저장

### 2. 카테고리 코드 오류

**에러:** `HTTP 400: originProduct.leafCategoryId: 유효하지 않은 카테고리입니다`
**분류:** `schema_changed`
**원인:** 경로 문자열(`상의 > 맨투맨/스웨트셔츠`)을 숫자 코드 대신 전달
**해결:**
- 카테고리 매핑 테이블에서 숫자 코드 확인
- `category_id.isdigit()` 사전 검증 (dispatcher 라인 146~148)
- 매핑이 없으면 등록 거부 (빈값 → 기본 카테고리 사용 안 함)

### 3. 이미지 업로드 실패 (CDN 차단)

**에러:** `SmartStoreApiError: 이미지가 비정상적으로 작음(43B) — CDN 차단 가능성`
**분류:** `unknown`
**원인:** Referer 미설정으로 CDN이 핫링크 차단 이미지(1x1 GIF) 반환
**해결:**
- `upload_image_from_url()`의 Referer 설정 확인
- 무신사: `msscdn.net` → Referer `https://www.musinsa.com/`
- 기타: 이미지 원본 도메인을 Referer로 자동 설정

### 4. 필수필드 누락

**에러:** `필수필드 누락: name, sale_price`
**분류:** `schema_changed` (사전 검증)
**원인:** CollectedProduct에 name 또는 sale_price가 비어있음
**해결:**
- 수집 단계에서 필수필드 검증 (product-parser 스킬 참조)
- `validate_transform()` 사전 검증에서 걸림

### 5. 가격 0원

**에러:** `HTTP 400: originProduct.salePrice: 가격은 0보다 커야 합니다`
**분류:** `schema_changed`
**원인:** sale_price=0이고 original_price도 0
**해결:**
- transform_product의 폴백 체인 확인: sale_price → original_price → 10000
- 수집 시 가격 필드 검증 강화

### 6. 상품명 길이 초과

**에러:** `HTTP 400: originProduct.name: 100자를 초과할 수 없습니다`
**분류:** `schema_changed`
**원인:** 소싱처 상품명이 100자 초과
**해결:**
- `name[:100]` 절삭 적용 (현재 미구현)
- 브랜드명, 부가 설명 제거 후 재시도

### 7. 이미지 업로드 응답 없음

**에러:** `SmartStoreApiError: 이미지 업로드 응답에 URL 없음`
**분류:** `unknown`
**원인:** 네이버 이미지 서버 일시적 장애 또는 파일 형식 미지원
**해결:**
- 이미지 Content-Type 확인 (jpg/png/webp만 지원)
- 재시도 (일시적 장애인 경우)

### 8. 고시정보 타입 불일치

**에러:** `HTTP 400: productInfoProvidedNotice: WEAR 타입에 맞지 않는 카테고리`
**분류:** `schema_changed`
**원인:** 신발/화장품 카테고리인데 WEAR 고시정보 전송
**해결:**
- 카테고리 기반 고시정보 타입 분기 구현 (현재 미구현, 알려진 제한사항 #1)
- 수동으로 적합한 고시정보 타입 지정

### 9. 인증 만료

**에러:** `HTTP 401: 인증 정보가 유효하지 않습니다`
**분류:** `auth_failed`
**원인:** access_token 만료 후 갱신 실패
**해결:**
- `_ensure_token()`의 60초 안전 버퍼 확인
- 장시간 전송 시 토큰 만료 가능 → 재전송으로 해결

### 10. originAreaCode 오류

**에러:** `HTTP 400: originAreaInfo.originAreaCode: 유효하지 않은 원산지 코드`
**분류:** `schema_changed`
**원인:** 스마트스토어 원산지 코드 변경
**해결:**
- 현재 `originAreaCode: "03"` (기타/해외) 고정
- 유효 코드: 01(국산), 02(수입), 03(기타)

---

## 11번가 주요 에러

### 1. XML 파싱 에러

**에러:** `ElevenstApiError: HTTP 400: XML 파싱 에러`
**원인:** 상품명/옵션에 XML 특수문자(`& < > " '`) 미이스케이프
**해결:** `_escape_xml()` 함수로 모든 텍스트 필드 처리

### 2. 카테고리 코드 오류

**에러:** `ElevenstApiError: API 에러 (9999): 유효하지 않은 카테고리`
**원인:** 숫자 카테고리 코드가 11번가 체계와 불일치
**해결:** 11번가 카테고리 API로 유효 코드 조회 후 매핑

### 3. API Key 오류

**에러:** `ElevenstApiError: HTTP 403: openapikey 인증 실패`
**원인:** 만료되거나 잘못된 Open API Key
**해결:** 11번가 셀러오피스에서 API Key 재발급

---

## 쿠팡 주요 에러

### 1. HMAC 서명 오류

**에러:** `CoupangApiError: HTTP 401: Invalid signature`
**원인:** access_key/secret_key 오류 또는 서명 생성 로직 불일치
**해결:**
- 서명 메시지 형식: `{datetime}\n{method}\n{path}\n{query}`
- datetime 형식: `yyMMddTHHmmssZ` (UTC)
- 쿠팡 Wing API 콘솔에서 키 재확인

### 2. vendorId 누락

**에러:** `CoupangApiError: HTTP 400: vendorId는 필수값입니다`
**원인:** transform 후 vendorId 채우기 누락
**해결:** `dispatcher.py` 라인 231에서 `data["vendorId"] = vendor_id` 설정

### 3. 반품센터 코드

**에러:** `CoupangApiError: HTTP 400: returnCenterCode가 유효하지 않습니다`
**원인:** 반품센터 코드 미설정 (빈값)
**해결:** 쿠팡 Wing API로 반품센터 목록 조회 후 설정 (현재 미구현)

---

## 재시도 전략 (retransmit)

`SambaShipmentService.retransmit(shipment_id)`:

1. 기존 shipment의 `transmit_result`에서 `failed` 계정만 추출
2. 상품 데이터 재조회
3. 실패 계정에 대해서만 `dispatch_to_market()` 재호출
4. 같은 shipment 레코드 업데이트 (새 레코드 생성 아님)
5. **주의:** 카테고리 빈값으로 전달됨 (알려진 제한사항 #6)

### 재시도 대상 판단

| error_type | 재시도 | 이유 |
|---|---|---|
| `network` | O | 일시적 장애, 재시도로 해결 가능 |
| `auth_failed` | △ | 키 재발급 후에만 의미 |
| `schema_changed` | X | 코드 수정 필요 |
| `unknown` | △ | 원인 파악 후 판단 |

---

## 품절 시 판매중지 흐름

`SambaShipmentService.delete_from_markets()`:

```
1. product.registered_accounts에서 등록된 계정 확인
2. 각 계정의 market_product_nos에서 상품번호 조회
3. dispatcher.delete_from_market() 호출
   → 스마트스토어: statusType="SUSPENSION"
   → 쿠팡: statusType="STOP"
   → 롯데홈쇼핑/GS샵: update_sale_status(product_no, "02")
4. 성공 시 registered_accounts에서 제거
5. 모든 계정 제거 시 product.status = "collected"
```
