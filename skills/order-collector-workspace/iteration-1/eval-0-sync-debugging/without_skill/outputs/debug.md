# 스마트스토어 주문 동기화 0건 문제 디버깅 분석

## 분석 대상 파일
- `backend/backend/api/v1/routers/samba/order.py` — `sync-from-markets` 엔드포인트, `_parse_smartstore_order` 함수
- `backend/backend/domain/samba/proxy/smartstore.py` — `SmartStoreClient.get_orders()`

---

## 동기화 흐름 요약

```
POST /orders/sync-from-markets { days, account_id? }
  1. 활성 마켓 계정 조회 (account_repo)
  2. market_type == "smartstore" → SmartStoreClient 생성
  3. client.get_orders(days) → raw_orders (2단계 API 호출)
     3-1. GET /v1/pay-order/seller/product-orders/last-changed-statuses (변경된 주문 ID 목록)
     3-2. POST /v1/pay-order/seller/product-orders/query (주문 상세 조회)
  4. _parse_smartstore_order()로 dict 변환
  5. order_number 기준 중복 체크 → 신규면 create_order, 기존이면 update
```

---

## 주문이 0건 들어올 수 있는 원인 분석

### 원인 1: 인증 정보 누락으로 계정 skip (가능성: 높음)

**위치**: `order.py` 210~223행

```python
client_id = extras.get("clientId", "") or account.api_key or ""
client_secret = extras.get("clientSecret", "") or account.api_secret or ""
if not client_id or not client_secret:
    # fallback: 공유 설정
    ...
if not client_id or not client_secret:
    results.append({"account": label, "status": "skip", "message": "인증정보 없음"})
    continue
```

`additional_fields`에 `clientId`/`clientSecret`이 없고, `api_key`/`api_secret`도 비어있고, `store_smartstore` 공유 설정도 없으면 해당 계정은 **skip**된다. 결과에 `"status": "skip"` 으로 표시되므로 프론트 로그에서 "인증정보 없음"이 보일 것이다.

**확인 방법**: 프론트엔드 로그에 "인증정보 없음" 메시지가 뜨는지 확인.

---

### 원인 2: 활성 계정이 없거나 market_type 불일치 (가능성: 중간)

**위치**: `order.py` 189~195행

```python
if body.account_id:
    target = await account_repo.get_async(body.account_id)
    active_accounts = [target] if target else []
else:
    active_accounts = await account_repo.filter_by_async(
        is_active=True, order_by="created_at", order_by_desc=True
    )
```

- `is_active=False`인 계정은 전체 동기화 시 조회되지 않는다.
- `market_type`이 `"smartstore"`가 아닌 다른 값(예: `"SmartStore"`, `"naver"`, `"스마트스토어"`)으로 저장되어 있으면 `if market_type == "smartstore":` 분기를 타지 않고 250행의 `else`로 빠져서 "주문 조회 미지원"으로 skip된다.

**확인 방법**: DB에서 `samba_market_account` 테이블의 `market_type`, `is_active` 값 확인.

---

### 원인 3: API 응답 구조 파싱 실패 — lastChangeStatuses가 빈 배열 (가능성: 높음)

**위치**: `smartstore.py` 362~373행

```python
result = await self._call_api(
    "GET",
    "/v1/pay-order/seller/product-orders/last-changed-statuses",
    params=qparams,
)
data = result.get("data", result) if isinstance(result, dict) else {}
statuses = data.get("lastChangeStatuses", []) if isinstance(data, dict) else []
```

네이버 커머스 API의 실제 응답 구조는 다음과 같다:
```json
{
  "data": {
    "lastChangeStatuses": [...]
  }
}
```

**잠재적 문제**: 네이버 API 응답에서 `"data"` 래핑이 없거나, 키 이름이 `"lastChangeStatuses"` 대신 다른 이름(예: `"lastChangedStatuses"`)인 경우 빈 배열이 반환된다. 네이버 API 문서에서는 응답 필드명이 **`lastChangeStatuses`**(Change, 단수)인데, 실제 API 버전에 따라 달라질 수 있다.

**확인 방법**: 백엔드 로그에서 `[스마트스토어] 변경된 주문 수: 0` 이 출력되는지 확인. 0이면 1단계 API 호출에서 이미 데이터를 못 가져오는 것이다.

---

### 원인 4: 조회 기간 내 주문 변경 없음 (가능성: 중간)

**위치**: `smartstore.py` 337~338행

```python
effective_days = min(days, 89)
since = datetime.now(kst) - timedelta(days=effective_days)
```

`last-changed-statuses` API는 **상태가 변경된** 주문만 반환한다. 조회 기간 내에 상태 변경이 없는 주문은 조회되지 않는다. 예를 들어 30일 전에 결제 완료된 후 아무 변경이 없는 주문은 7일 조회로는 안 나온다.

**확인 방법**: 기간을 90일로 늘려서 재시도.

---

### 원인 5: 토큰 발급 실패 — bcrypt 서명 오류 (가능성: 중간)

**위치**: `smartstore.py` 42~46행

```python
hashed = bcrypt.hashpw(
    password.encode("utf-8"),
    self.client_secret.encode("utf-8"),
)
```

`client_secret`이 bcrypt salt 형식(`$2b$...`)이 아니면 `bcrypt.hashpw`에서 예외가 발생한다. 이 경우 전체 `try/except`에 잡혀서 `"status": "error"`로 리포트된다.

**확인 방법**: 프론트엔드 로그에 "오류" 메시지 확인, 백엔드 로그에서 `토큰 발급 실패` 확인.

---

### 원인 6: 2단계 상세 조회 응답 파싱 실패 (가능성: 중간)

**위치**: `smartstore.py` 388~402행

```python
details_result = await self._call_api(
    "POST",
    "/v1/pay-order/seller/product-orders/query",
    body={"productOrderIds": po_ids[:300]},
)
details_data = details_result.get("data", details_result) if isinstance(details_result, dict) else details_result
if isinstance(details_data, list):
    orders_data = details_data
elif isinstance(details_data, dict):
    orders_data = details_data.get("productOrders", [])
```

1단계에서 주문 ID를 가져왔더라도 2단계 상세 조회 응답의 구조가 예상과 다르면 `orders_data`가 빈 배열이 된다. 특히 응답이 `{"data": {"productOrders": [...]}}`인 경우는 정상이지만, `{"data": [...]}`처럼 직접 배열이면 `productOrders` 키를 찾지 못한다.

**확인 방법**: 백엔드 로그에서 `[스마트스토어] 주문 상세 결과: 0건` 인지 확인. "변경된 주문 수"는 양수인데 "상세 결과"가 0이면 이 원인이다.

---

### 원인 7: 중복 체크로 synced 카운트가 0 (가능성: 높음)

**위치**: `order.py` 256~297행

```python
existing = await svc.repo.find_by_async(order_number=order_data["order_number"])
if existing:
    # 기존 주문: 업데이트만 하고 continue
    ...
    continue
await svc.create_order(order_data)
synced += 1
```

이미 동기화된 주문이 DB에 존재하면 `synced` 카운트가 올라가지 않는다. **실제 주문은 가져왔지만 이미 저장된 주문이라 "0건 신규 저장"으로 표시**되는 것일 수 있다.

프론트엔드 로그 형식: `"X건 조회, 0건 신규 저장"`
- `fetched`가 양수인데 `synced`가 0이면 → 원인 7 (중복 주문, 정상 동작)
- `fetched`도 0이면 → 원인 3, 4, 5, 6

**확인 방법**: 로그에서 `fetched`와 `synced` 값을 비교.

---

### 원인 8: find_by_async에서 다중 결과로 인한 예외 (가능성: 낮음)

**위치**: `base_repository.py` 325~348행

```python
async def find_by_async(self, **kwargs: Any) -> Optional[ModelType]:
    ...
    entity: Optional[ModelType] = result.scalar_one_or_none()
    return entity
```

`scalar_one_or_none()`은 결과가 2개 이상이면 `MultipleResultsFound` 예외를 발생시킨다. 만약 같은 `order_number`로 중복 레코드가 DB에 존재하면, 두 번째 동기화부터 이 예외가 발생하여 전체 루프가 `except`에 잡혀 에러가 된다.

**확인 방법**: DB에서 `SELECT order_number, COUNT(*) FROM samba_order GROUP BY order_number HAVING COUNT(*) > 1` 실행.

---

### 원인 9: `_call_api` 에서 content-type 판별 오류로 토큰 발급 실패 (가능성: 낮음)

**위치**: `smartstore.py` 62행

```python
err = resp.json() if "json" in resp.headers.get("content-type", "") else {}
```

네이버 API가 `application/json;charset=UTF-8` 등으로 응답하면 `"json" in content_type`이 True가 되어 정상이지만, 다른 content-type이면 에러 메시지를 파싱하지 못한다. 다만 이 경우 에러가 raise되므로 "0건"이 아니라 에러 메시지가 로그에 나올 것이다.

---

## 해결 방법

### 즉시 확인 사항

1. **프론트엔드 동기화 로그 확인**: `fetched` 값과 `synced` 값, 그리고 `status`가 `success`/`skip`/`error` 중 무엇인지 확인
2. **백엔드 로그 확인**: `[스마트스토어]`, `[주문동기화]` 프리픽스 로그를 순서대로 추적
3. **DB 확인**: `samba_market_account` 테이블에서 `market_type`, `is_active`, `additional_fields` 값 확인

### 우선순위별 수정 제안

| 우선순위 | 원인 | 수정 방법 |
|---------|------|----------|
| 1 | 원인 7 (중복 주문) | 로그에 `fetched` 값이 양수면 정상 동작. 프론트에서 "기존 N건 업데이트" 표시 추가 |
| 2 | 원인 1 (인증 누락) | 계정 설정 화면에서 `clientId`/`clientSecret` 입력 여부 확인 |
| 3 | 원인 2 (market_type 불일치) | DB에서 `market_type` 값이 정확히 `"smartstore"`(소문자)인지 확인 |
| 4 | 원인 3 (API 응답 파싱) | `get_orders()` 1단계 API 호출 후 raw 응답 전체를 로깅하여 실제 구조 확인 |
| 5 | 원인 5 (토큰 실패) | `client_secret`이 bcrypt salt 형식인지 확인 (반드시 `$2b$` 또는 `$2a$`로 시작) |
| 6 | 원인 4 (기간 부족) | `days` 값을 90으로 늘려서 테스트 |
| 7 | 원인 6 (상세 조회 파싱) | 2단계 API raw 응답 로깅 추가 |
| 8 | 원인 8 (중복 레코드) | `order_number`에 UNIQUE 인덱스 추가 또는 `find_by_async` 대신 `filter_by_async` 사용 후 `[0]` 접근 |

### 디버깅용 로깅 강화 코드 (권장)

`smartstore.py`의 `get_orders()` 메서드에서 각 단계별 raw 응답을 로깅하면 원인을 즉시 파악할 수 있다:

```python
# 1단계 응답 전체 로깅
logger.info(f"[스마트스토어] 1단계 raw 응답: {result}")

# 2단계 응답 전체 로깅
logger.info(f"[스마트스토어] 2단계 raw 응답: {details_result}")
```

### 근본적 개선 사항

1. **`order_number` 컬럼에 UNIQUE 제약조건 추가**: 중복 레코드 방지 및 `find_by_async` 안전성 확보
2. **API 응답 구조 검증 강화**: `lastChangeStatuses` 키가 없을 때 대체 키(`lastChangedStatuses` 등) 시도
3. **동기화 결과에 "업데이트" 카운트 추가**: `fetched`와 `synced` 외에 `updated` 카운트도 리턴하여 실제 처리 건수 파악 가능하게 함
