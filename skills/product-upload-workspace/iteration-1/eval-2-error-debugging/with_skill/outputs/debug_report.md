# 디버그 리포트: 스마트스토어 InvalidInputs — leafCategoryId 유효하지 않은 카테고리

## 에러 원문

```
HTTP 400: InvalidInputs [originProduct.leafCategoryId: 유효하지 않은 카테고리입니다]
```

---

## 1. 에러 분류 체계 분석

### dispatcher.py 에러 분류 로직 (라인 93~109)

디스패처는 예외 발생 시 `str(exc).lower()` 결과에 포함된 키워드를 기준으로 4단계 분류한다:

| 에러 타입 | 감지 키워드 | 의미 |
|-----------|------------|------|
| `auth_failed` | `401`, `403`, `unauthorized`, `인증` | 인증 실패 |
| `schema_changed` | `400`, `422`, `필수`, `required` | API 스펙 불일치 |
| `network` | `timeout`, `connect`, `network` | 네트워크 장애 |
| `unknown` | (그 외) | 미분류 |

### 이 에러의 분류 결과: `schema_changed`

에러 메시지 `"HTTP 400: InvalidInputs [originProduct.leafCategoryId: 유효하지 않은 카테고리입니다]"`에 `"400"`이 포함되어 있으므로, 디스패처는 이 에러를 **`schema_changed`** 타입으로 분류한다.

```python
# dispatcher.py 라인 94, 98
exc_str = str(exc).lower()
elif "400" in exc_str or "422" in exc_str or "필수" in exc_str or "required" in exc_str:
    error_type = "schema_changed"
```

### 분류의 의미

`schema_changed`로 분류된 에러는 **코드 수정이 필요한 에러**로 판단된다. 재전송(retransmit)으로는 해결되지 않으며, transform 로직 또는 카테고리 매핑 데이터를 수정해야 한다.

---

## 2. 카테고리 검증 로직 상세 분석

### 2.1 dispatcher.py `_handle_smartstore` 카테고리 검증 (라인 146~151)

```python
# 카테고리 코드가 숫자가 아니면 경고 (경로 문자열은 API에서 사용 불가)
if category_id and not category_id.isdigit():
    logger.warning(f"[스마트스토어] 카테고리 '{category_id}'가 숫자 코드가 아님 — 기본 카테고리 사용")
    category_id = ""

if not category_id:
    return {"success": False, "message": "스마트스토어 카테고리 코드가 없습니다. 카테고리 매핑을 설정해주세요."}
```

디스패처는 두 단계로 카테고리를 검증한다:

1. **형식 검증**: `category_id.isdigit()`으로 숫자 여부만 확인. 숫자가 아니면(경로 문자열 등) 빈 문자열로 초기화하고 등록을 거부한다.
2. **비어있음 검증**: 카테고리가 빈 문자열이면 즉시 실패를 반환한다.

**문제점**: `isdigit()` 검증을 통과한 숫자 코드가 네이버 커머스 API에서 실제로 유효한 카테고리인지는 검증하지 않는다. 따라서 **형식은 올바르지만 코드 자체가 무효한 경우** API 호출까지 진행된 후 400 에러가 발생한다.

### 2.2 smartstore.py `transform_product`의 카테고리 처리 (라인 476)

```python
"leafCategoryId": category_id or "50000803",
```

`category_id`가 빈 문자열이면 기본값 `"50000803"`을 사용한다. 그러나 위 2.1의 검증에서 빈 문자열이면 이미 실패 반환하므로, 실질적으로 이 기본값(`50000803`)이 사용되는 경우는 `transform_product()`를 직접 호출할 때뿐이다.

### 2.3 service.py `_resolve_category_mappings`의 카테고리 조회 (라인 374~423)

카테고리 코드는 `_resolve_category_mappings()`에서 결정된다:

```
1순위: DB 매핑 테이블 (SambaCategoryMappingRepository.find_mapping)
  → source_site + source_category → target_mappings[market_type]

2순위: 키워드 기반 자동 제안 (SambaCategoryService.suggest_category)
  → source_category 문자열로 검색 → 첫 번째 결과 사용
```

이후 `service.py` 라인 220에서 마켓별 카테고리를 추출한다:

```python
category_id = mapped_categories.get(market_type, "")
```

---

## 3. 근본 원인 분석

이 에러가 발생하는 시나리오는 총 **3가지**다:

### 원인 1: 카테고리 매핑 테이블에 경로 문자열이 저장된 경우

DB의 `SambaCategoryMapping.target_mappings`에 숫자 코드가 아닌 경로 문자열이 저장된 경우:

```json
{
  "smartstore": "상의 > 맨투맨/스웨트셔츠"  // 잘못됨
}
```

이 경우 디스패처의 `isdigit()` 검증에서 걸려 `category_id = ""`로 초기화되고, `"카테고리 코드가 없습니다"` 메시지로 사전 차단된다. **이 경우에는 leafCategoryId 에러가 아닌 사전 차단 에러가 발생한다.**

### 원인 2: 유효하지 않은 숫자 카테고리 코드 (가장 유력)

DB 매핑 또는 자동 제안에서 반환된 숫자 코드가 네이버 커머스 API에서 더 이상 유효하지 않은 경우:

```json
{
  "smartstore": "99999999"  // 숫자이지만 폐지된 카테고리
}
```

`isdigit()` 검증은 통과하지만, 실제 API 호출 시 네이버 서버에서 유효하지 않은 카테고리로 판단하여 400 에러를 반환한다. 이것이 **가장 유력한 원인**이다.

**발생 경로:**
```
_resolve_category_mappings()
  → DB 매핑에서 "99999999" 반환 (또는 자동 제안에서 잘못된 코드 반환)
  → dispatcher._handle_smartstore()에서 isdigit() 통과
  → SmartStoreClient.transform_product()에서 leafCategoryId에 그대로 설정
  → SmartStoreClient.register_product() → POST /v2/products
  → 네이버 API가 400 InvalidInputs 반환
  → SmartStoreApiError 발생
  → dispatcher에서 "400" 키워드 감지 → schema_changed로 분류
```

### 원인 3: 기본값 `50000803`이 무효화된 경우

만약 `transform_product()`가 직접 호출되어 기본값 `"50000803"`이 사용되었는데, 해당 코드가 네이버에서 폐지된 경우에도 같은 에러가 발생한다. 다만 현재 코드 흐름에서는 디스패처가 빈 카테고리를 사전 차단하므로 이 경로는 발생 확률이 낮다.

---

## 4. 에러 발생 위치 추적

```
[1] service.py L148: _resolve_category_mappings() → 카테고리 코드 결정
[2] service.py L220: category_id = mapped_categories.get(market_type, "")
[3] service.py L223-224: dispatch_to_market(session, market_type, product_dict, category_id, account)
[4] dispatcher.py L92: handler(session, product, category_id, account)
[5] dispatcher.py L146-148: isdigit() 검증 통과 (숫자 코드이므로)
[6] smartstore.py L199: transform_product(product_copy, category_id) → leafCategoryId 설정
[7] smartstore.py L200: register_product(data) → POST /v2/products
[8] smartstore.py L108-117: resp.is_success == False → invalidInputs 파싱
[9] smartstore.py L117: raise SmartStoreApiError("HTTP 400: InvalidInputs [...]")
[10] dispatcher.py L93-108: except → "400" 감지 → error_type="schema_changed"
```

---

## 5. 해결 방법

### 즉시 해결 (데이터 수정)

1. **카테고리 매핑 확인**: 프론트엔드의 `카테고리` 메뉴에서 해당 소싱처 카테고리의 스마트스토어 매핑이 올바른 숫자 코드인지 확인
2. **유효 코드 조회**: 네이버 커머스 API의 카테고리 목록 조회(`GET /v1/categories?last=true`)를 통해 현재 유효한 `leafCategoryId` 확인
3. **매핑 업데이트**: DB의 `samba_category_mapping` 테이블에서 `target_mappings.smartstore` 값을 유효한 코드로 수정

### 근본 해결 (코드 수정)

#### 방법 A: 카테고리 유효성 사전 검증 추가

`_handle_smartstore()`에서 API 호출 전에 카테고리 코드의 유효성을 검증한다:

```python
# dispatcher.py _handle_smartstore 내부, transform_product 호출 전
try:
    categories = await client.get_categories(last_only=True)
    valid_ids = {str(c.get("id", "")) for c in categories}
    if category_id not in valid_ids:
        return {
            "success": False,
            "error_type": "schema_changed",
            "message": f"유효하지 않은 카테고리 코드: {category_id}. 카테고리 매핑을 다시 설정해주세요.",
        }
except Exception:
    pass  # 검증 실패 시 그대로 진행 (API에서 최종 판단)
```

#### 방법 B: 자동 제안 품질 개선

`_resolve_category_mappings()`의 `suggest_category()` 결과가 잘못된 코드를 반환하는 경우, 제안 로직의 검색 키워드 매칭 정확도를 개선한다.

#### 방법 C: 에러 메시지 개선

현재 에러 메시지가 API 원문 그대로 전달되어 사용자가 원인을 파악하기 어렵다. 디스패처에서 `leafCategoryId` 관련 에러를 감지하여 사용자 친화적 메시지로 변환한다:

```python
# dispatcher.py except 블록 내부
if "leafcategoryid" in exc_str:
    return {
        "success": False,
        "error_type": "schema_changed",
        "message": f"카테고리 코드 '{category_id}'가 스마트스토어에서 유효하지 않습니다. 카테고리 매핑 페이지에서 올바른 코드로 수정해주세요.",
    }
```

---

## 6. 재전송(retransmit) 가능 여부

| 항목 | 판단 |
|------|------|
| error_type | `schema_changed` |
| 재전송 효과 | **없음** — 같은 카테고리 코드로 재전송하면 동일 에러 반복 |
| 추가 문제 | `retransmit()` 시 카테고리가 빈값으로 전달됨 (알려진 제한사항 #6) |
| 해결 후 재전송 | 카테고리 매핑 수정 후 **새 전송**으로 처리해야 함 |

---

## 7. 관련 파일

| 파일 | 역할 |
|------|------|
| `backend/backend/domain/samba/shipment/dispatcher.py` | 에러 분류 (L93-109), 카테고리 형식 검증 (L146-151) |
| `backend/backend/domain/samba/proxy/smartstore.py` | `transform_product()` (L436-529), `register_product()` (L272-306), `_call_api()` 에러 파싱 (L108-117) |
| `backend/backend/domain/samba/shipment/service.py` | `_resolve_category_mappings()` (L374-423), 카테고리 전달 (L220) |

---

## 8. 요약

| 항목 | 내용 |
|------|------|
| **에러** | `HTTP 400: InvalidInputs [originProduct.leafCategoryId: 유효하지 않은 카테고리입니다]` |
| **분류** | `schema_changed` (디스패처가 "400" 키워드로 감지) |
| **근본 원인** | DB 매핑 또는 자동 제안에서 반환된 카테고리 코드가 네이버 API에서 유효하지 않음. `isdigit()` 형식 검증은 통과하지만 실제 API 유효성 검증이 없어 등록 시점에 실패 |
| **즉시 조치** | 카테고리 매핑 페이지에서 해당 상품의 스마트스토어 카테고리를 유효한 숫자 코드로 재설정 |
| **근본 조치** | 전송 전 `get_categories()` API로 카테고리 유효성 사전 검증 로직 추가 |
| **재전송** | 불가 — 카테고리 매핑 수정 후 새 전송 필요 |
