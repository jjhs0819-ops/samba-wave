# 스마트스토어 상품 등록 에러 디버그 리포트

## 에러 메시지

```
HTTP 400: InvalidInputs [originProduct.leafCategoryId: 유효하지 않은 카테고리입니다]
```

---

## 1. 에러 분류 체계 분석 (dispatcher.py)

### 1.1 디스패처의 에러 분류 구조

`dispatcher.py`의 `dispatch_to_market()` 함수(93~109행)는 마켓 핸들러에서 발생하는 예외를 4가지 유형으로 분류한다.

| error_type | 분류 조건 (exc_str 기준) | 의미 |
|---|---|---|
| `auth_failed` | `401`, `403`, `unauthorized`, `인증` 포함 | 인증 실패 |
| `schema_changed` | `400`, `422`, `필수`, `required` 포함 | API 스펙 변경 또는 잘못된 입력 |
| `network` | `timeout`, `connect`, `network` 포함 | 네트워크 오류 |
| `unknown` | 위 조건 모두 불일치 | 미분류 에러 |

추가로, 핸들러 호출 전 단계에서 `validate_transform()`이 필수필드 누락을 검사하며, 누락 시 `error_type: "schema_changed"`를 직접 반환한다(76~82행).

### 1.2 이 에러의 분류 결과

이 에러는 `SmartStoreApiError("HTTP 400: InvalidInputs [originProduct.leafCategoryId: 유효하지 않은 카테고리입니다]")`로 발생한다. 에러 문자열에 `"400"`이 포함되므로 **`schema_changed`로 분류**된다.

이 분류는 부정확하다. 실제 원인은 스펙 변경이 아니라 **잘못된 카테고리 코드 전달**이다. `schema_changed`라는 레이블은 개발자에게 "API 스펙이 바뀌었나?"라는 잘못된 방향으로 조사를 유도할 수 있다.

---

## 2. 카테고리 검증 로직 분석 (_handle_smartstore)

### 2.1 dispatcher.py의 카테고리 검증 (145~151행)

```python
# 카테고리 코드가 숫자가 아니면 경고 (경로 문자열은 API에서 사용 불가)
if category_id and not category_id.isdigit():
    logger.warning(f"[스마트스토어] 카테고리 '{category_id}'가 숫자 코드가 아님 - 기본 카테고리 사용")
    category_id = ""

if not category_id:
    return {"success": False, "message": "스마트스토어 카테고리 코드가 없습니다. 카테고리 매핑을 설정해주세요."}
```

이 검증은 **형식(숫자 여부)만 확인**하고, 해당 숫자 코드가 네이버 커머스에서 실제로 유효한 말단(leaf) 카테고리인지는 검증하지 않는다.

### 2.2 SmartStoreClient.transform_product()의 기본값 (smartstore.py 476행)

```python
"leafCategoryId": category_id or "50000803",
```

`category_id`가 빈 문자열이면 하드코딩된 `"50000803"`이 사용된다. 이 코드가 현재 네이버에서 유효하지 않거나 삭제/변경된 경우에도 그대로 전송된다.

### 2.3 카테고리 매핑 해결 과정 (service.py의 _resolve_category_mappings)

전송 시 카테고리 매핑은 다음 순서로 결정된다.

1. **DB 매핑 조회**: `samba_category_mapping` 테이블에서 `source_site + source_category`로 매핑 검색
2. **target_mappings 사용**: 매핑 레코드의 `target_mappings` JSON에서 `smartstore` 키의 값 사용
3. **자동 추천 fallback**: DB 매핑이 없으면 `suggest_category()`로 키워드 매칭 또는 AI 추천

**핵심 문제**: `target_mappings`에 저장되는 값이 **카테고리 경로 문자열**(예: `"패션의류 > 남성의류 > 티셔츠"`)인지, **숫자 카테고리 코드**(예: `"50000803"`)인지에 따라 결과가 달라진다.

- `suggest_category()`는 `MARKET_CATEGORIES` 딕셔너리에서 **경로 문자열**을 반환한다
- dispatcher는 `isdigit()` 검사를 통과하는 **숫자 코드**만 허용한다
- 경로 문자열이 전달되면 `isdigit()` 검사에서 걸려 빈 문자열로 초기화되고, "카테고리 코드가 없습니다" 에러가 발생한다

---

## 3. 에러 원인 분석

### 3.1 직접 원인

네이버 커머스 API의 `leafCategoryId` 필드에 **유효하지 않은 카테고리 코드**가 전달되었다.

### 3.2 가능한 시나리오 (우선순위순)

#### 시나리오 A: 존재하지 않거나 만료된 카테고리 코드

- DB의 `samba_category_mapping.target_mappings`에 저장된 스마트스토어 카테고리 코드가 네이버에서 폐지/변경됨
- 또는 하드코딩 기본값 `"50000803"`이 더 이상 유효하지 않음
- 네이버는 카테고리 체계를 주기적으로 개편하며, 기존 코드가 비활성화될 수 있음

#### 시나리오 B: 말단(leaf) 카테고리가 아닌 상위 카테고리 코드 전달

- 네이버 API는 **최하위(leaf) 카테고리**만 허용한다
- 중간 단계 카테고리 코드(예: "패션의류" 대분류 코드)를 전달하면 이 에러가 발생한다

#### 시나리오 C: 카테고리 경로 문자열이 숫자로 잘못 해석

- AI 추천이나 수동 매핑에서 숫자만으로 된 카테고리 이름이 저장될 가능성은 낮지만, 데이터 정합성 문제로 발생 가능

---

## 4. 코드상 구조적 문제점

### 4.1 카테고리 코드 유효성 미검증

`_handle_smartstore`는 `isdigit()` 형식 검사만 수행하며, 네이버 API에 실제로 유효한 leaf 카테고리인지 사전 확인하지 않는다. 네이버 커머스 API에는 카테고리 조회 엔드포인트(`GET /v1/categories`)가 있고, `SmartStoreClient.get_categories()` 메서드도 구현되어 있지만 전송 시 사용되지 않는다.

### 4.2 경로 문자열 vs 숫자 코드 불일치

- `MARKET_CATEGORIES`와 `suggest_category()`는 **경로 문자열** 반환
- `transform_product()`과 네이버 API는 **숫자 코드** 요구
- 이 변환 과정이 명확하게 구현되어 있지 않다

### 4.3 하드코딩 기본값의 위험

```python
"leafCategoryId": category_id or "50000803",
```

이 기본값은 코드 작성 시점에는 유효했을 수 있지만, 네이버 카테고리 개편 시 만료될 수 있다. 기본값 없이 명시적으로 실패하는 것이 안전하다.

### 4.4 재전송(retransmit) 시 카테고리 누락

`service.py`의 `retransmit()` 메서드(427~488행)에서 재전송 시 `category_id`를 빈 문자열 `""`로 전달한다(464행).

```python
result = await dispatch_to_market(
    self.session, account.market_type, product_dict, ""  # category_id가 항상 빈 문자열
)
```

이 경우 `_handle_smartstore`에서 "카테고리 코드가 없습니다" 에러로 항상 실패한다. 재전송 시에도 `_resolve_category_mappings`를 호출하여 카테고리를 다시 조회해야 한다.

---

## 5. 해결 방법

### 5.1 즉시 조치 (데이터 수정)

1. **현재 매핑된 카테고리 코드 확인**: DB의 `samba_category_mapping` 테이블에서 해당 상품의 소싱처 카테고리에 매핑된 스마트스토어 카테고리 코드 확인
2. **네이버 카테고리 코드 유효성 확인**: 네이버 커머스 API `GET /v1/categories?last=true`를 호출하여 해당 코드가 현재 유효한 leaf 카테고리인지 확인
3. **유효한 leaf 카테고리 코드로 교체**: `target_mappings`에 올바른 숫자 코드를 저장

### 5.2 코드 개선 (dispatcher.py)

#### A. 카테고리 코드 사전 검증 추가

`_handle_smartstore`에서 상품 등록 API 호출 전에 카테고리 유효성을 검증한다.

```python
# 카테고리 코드 유효성 사전 검증
try:
    categories = await client.get_categories(last_only=True)
    valid_ids = {str(c.get("id", "")) for c in categories if isinstance(c, dict)}
    if category_id not in valid_ids:
        return {
            "success": False,
            "error_type": "invalid_category",
            "message": f"스마트스토어 카테고리 코드 '{category_id}'가 유효하지 않습니다. 카테고리 매핑을 다시 설정해주세요.",
        }
except Exception as e:
    logger.warning(f"[스마트스토어] 카테고리 검증 실패 (전송 계속): {e}")
```

#### B. 에러 분류에 `invalid_category` 유형 추가

```python
elif "category" in exc_str or "카테고리" in exc_str:
    error_type = "invalid_category"
```

#### C. 하드코딩 기본값 제거

```python
# 변경 전
"leafCategoryId": category_id or "50000803",

# 변경 후
"leafCategoryId": category_id,  # 반드시 유효한 leaf 카테고리 코드 필요
```

### 5.3 코드 개선 (service.py)

#### D. retransmit() 카테고리 매핑 복원

```python
# retransmit()에서 카테고리 매핑 다시 조회
mapped_categories = await self._resolve_category_mappings(
    product_row.source_site or "",
    product_row.category or "",
    failed_accounts,
)
# ...
category_id = mapped_categories.get(account.market_type, "")
result = await dispatch_to_market(
    self.session, account.market_type, product_dict, category_id
)
```

### 5.4 카테고리 매핑 파이프라인 개선 (category/service.py)

#### E. 경로 문자열을 숫자 코드로 변환하는 로직 추가

`suggest_category()`가 반환하는 경로 문자열을 숫자 코드로 변환하는 매퍼가 필요하다. `SmartStoreClient.get_categories()`의 응답에서 `wholeCategoryName` -> `id` 매핑 테이블을 구축하여 사용한다.

---

## 6. 관련 파일

| 파일 | 역할 |
|---|---|
| `backend/backend/domain/samba/shipment/dispatcher.py` | 마켓별 상품 등록 라우팅 및 에러 분류 |
| `backend/backend/domain/samba/proxy/smartstore.py` | 네이버 커머스 API 클라이언트 및 데이터 변환 |
| `backend/backend/domain/samba/shipment/service.py` | 전송 오케스트레이션 및 카테고리 매핑 해결 |
| `backend/backend/domain/samba/category/service.py` | 카테고리 추천 및 매핑 관리 |
| `backend/backend/domain/samba/category/model.py` | 카테고리 매핑/트리 DB 모델 |

---

## 7. 요약

- **에러 원인**: `leafCategoryId`에 네이버에서 유효하지 않은(만료/비말단) 카테고리 코드가 전달됨
- **에러 분류**: `schema_changed`로 분류되나, 실제로는 잘못된 카테고리 데이터 문제
- **핵심 취약점**: (1) 카테고리 코드 유효성 사전 검증 부재, (2) 경로 문자열과 숫자 코드 간 변환 로직 부재, (3) 재전송 시 카테고리 빈 문자열 전달, (4) 하드코딩 기본값 `"50000803"`의 만료 위험
- **우선 조치**: DB의 카테고리 매핑을 유효한 네이버 leaf 카테고리 숫자 코드로 업데이트
