# 스마트스토어 주문 동기화 0건 디버깅 분석

## 분석 대상 파일

- `backend/backend/api/v1/routers/samba/order.py` (sync-from-markets 엔드포인트 + _parse_smartstore_order)
- `backend/backend/domain/samba/proxy/smartstore.py` (SmartStoreClient.get_orders)
- `backend/backend/domain/samba/order/service.py` (create_order)
- `backend/backend/domain/samba/order/model.py` (SambaOrder)

---

## 주문 동기화 파이프라인 요약

```
POST /api/v1/samba/orders/sync-from-markets { days: 7 }
  ↓
[1] 활성 마켓 계정 조회 (SambaMarketAccountRepository)
  ↓
[2] 계정별 인증정보(clientId/clientSecret) 확보
  ↓
[3] SmartStoreClient.get_orders(days) 호출
  ↓  [3-1] GET last-changed-statuses → productOrderId 목록
  ↓  [3-2] POST product-orders/query → 상세 조회
  ↓
[4] _parse_smartstore_order()로 SambaOrder 형태로 변환
  ↓
[5] order_number 기준 중복 체크
  ↓
[6] 신규 → create_order / 기존 → update_order
```

---

## 주문이 0건 들어올 수 있는 원인 분석 (8가지)

### 원인 1: 활성 마켓 계정이 없음 (가능성: 높음)

**위치:** `order.py` 189~195행

```python
if body.account_id:
    target = await account_repo.get_async(body.account_id)
    active_accounts = [target] if target else []
else:
    active_accounts = await account_repo.filter_by_async(
        is_active=True, order_by="created_at", order_by_desc=True
    )
```

- `is_active=False`인 계정만 존재하면 `active_accounts`가 빈 리스트
- 특정 `account_id`를 전달했는데 해당 ID가 DB에 없으면 빈 리스트
- **결과:** for 루프를 아예 돌지 않아 `total_synced = 0` 반환

**확인 방법:** DB에서 `SELECT * FROM samba_market_account WHERE is_active = true AND market_type = 'smartstore'` 실행

**해결:** 계정을 활성화하거나, 올바른 account_id 전달

---

### 원인 2: 인증정보(clientId/clientSecret) 누락 (가능성: 높음)

**위치:** `order.py` 212~223행

```python
client_id = extras.get("clientId", "") or account.api_key or ""
client_secret = extras.get("clientSecret", "") or account.api_secret or ""
if not client_id or not client_secret:
    # fallback: 공유 설정
    settings_repo = SambaSettingsRepository(session)
    row = await settings_repo.find_by_async(key="store_smartstore")
    ...
if not client_id or not client_secret:
    results.append({"account": label, "status": "skip", "message": "인증정보 없음"})
    continue
```

- 계정의 `additional_fields.clientId`, `api_key` 모두 비어있고
- `samba_settings` 테이블의 `store_smartstore` 키도 없으면
- **"skip"으로 건너뜀** → 주문 0건

**확인 방법:** 응답의 `results` 배열에 `"status": "skip", "message": "인증정보 없음"`이 있는지 확인

**해결:** 마켓 계정의 `additional_fields`에 `clientId`/`clientSecret` 설정, 또는 `samba_settings` 테이블에 `store_smartstore` 키로 저장

---

### 원인 3: API 토큰 발급 실패 (가능성: 중간)

**위치:** `smartstore.py` 36~69행 (`_ensure_token`)

```python
hashed = bcrypt.hashpw(
    password.encode("utf-8"),
    self.client_secret.encode("utf-8"),
)
```

- `client_secret`이 유효한 bcrypt salt 형식이 아니면 `ValueError` 발생
- 네이버 커머스 API의 client_secret은 `$2a$04$...` 형태의 bcrypt salt여야 함
- 잘못된 형식의 secret을 넣으면 토큰 발급 자체가 실패

**확인 방법:** 로그에 `"토큰 발급 실패"` 또는 bcrypt 관련 에러가 있는지 확인

**해결:** 네이버 커머스 API 애플리케이션에서 올바른 client_id/client_secret 발급

---

### 원인 4: API 응답 구조 불일치 — lastChangeStatuses 파싱 실패 (가능성: 중간)

**위치:** `smartstore.py` 362~373행

```python
result = await self._call_api("GET", "/v1/pay-order/seller/product-orders/last-changed-statuses", ...)
data = result.get("data", result) if isinstance(result, dict) else {}
statuses = data.get("lastChangeStatuses", []) if isinstance(data, dict) else []
```

- API 응답이 `{"data": {"lastChangeStatuses": [...]}}` 구조가 아니면 빈 리스트
- 네이버 API 버전 변경으로 응답 키가 바뀌었을 가능성 (예: `lastChangedStatuses` vs `lastChangeStatuses` — 오타 주의)
- **실제 네이버 API 문서에서는 `lastChangeStatuses`가 맞지만**, 일부 버전에서는 응답 구조가 다를 수 있음

**확인 방법:** 로그에 `"변경된 주문 수: 0"`이 찍히는지 확인. 0이면 이 단계에서 실패

**해결:** API 호출 시 raw 응답을 로깅하여 실제 키 이름 확인

---

### 원인 5: 해당 기간에 주문이 실제로 없음 (가능성: 중간)

**위치:** `order.py` 173행, `smartstore.py` 336행

```python
# 기본값 days=7
effective_days = min(days, 89)
```

- 기본 7일 이내에 주문이 없으면 당연히 0건
- `last-changed-statuses` API는 **상태가 변경된** 주문만 반환하므로, 오래 전 주문이고 최근에 상태 변경이 없으면 조회 안 됨

**확인 방법:** `days`를 30이나 60으로 늘려서 재시도

**해결:** 요청 시 `days` 파라미터를 충분히 크게 설정 (최대 89)

---

### 원인 6: market_type이 "smartstore"가 아닌 경우 (가능성: 낮음)

**위치:** `order.py` 210, 242~252행

```python
if market_type == "smartstore":
    ...
elif market_type == "coupang":
    results.append({..., "message": "쿠팡 주문 조회 미구현"})
    continue
elif market_type == "11st":
    results.append({..., "message": "11번가 주문 조회 미구현"})
    continue
else:
    results.append({..., "message": f"{market_type} 주문 조회 미지원"})
    continue
```

- 계정의 `market_type`이 `"smartstore"` 정확히 일치하지 않으면 (`"Smartstore"`, `"smart_store"` 등) else 분기로 빠져 skip
- 현재 주문 수집은 스마트스토어만 구현되어 있음

**확인 방법:** 응답 results에 `"미지원"` 또는 `"미구현"` 메시지 확인

**해결:** DB에서 계정의 `market_type` 값이 정확히 `"smartstore"`인지 확인

---

### 원인 7: 모든 주문이 이미 동기화되어 synced=0 (가능성: 중간)

**위치:** `order.py` 256~297행

```python
existing = await svc.repo.find_by_async(order_number=order_data["order_number"])
if existing:
    # 기존 주문: 업데이트만 수행
    ...
    continue  # ← 신규가 아니므로 synced 카운트 증가 안 함
await svc.create_order(order_data)
synced += 1
```

- API에서 주문은 정상적으로 가져왔지만 (`fetched > 0`)
- 이미 DB에 해당 `order_number`로 저장된 주문이면 `synced` 카운트가 0
- **이 경우 응답의 `fetched`는 양수이고 `synced`만 0이므로**, 진짜 0건과 구분 가능

**확인 방법:** 응답에서 `fetched` vs `synced` 값 비교. fetched > 0이고 synced == 0이면 이 원인

**해결:** 이것은 정상 동작. 기존 주문은 업데이트만 수행되고 있음

---

### 원인 8: 예외 발생 후 error로 처리 (가능성: 낮음)

**위치:** `order.py` 315~317행

```python
except Exception as e:
    logger.error(f"[주문동기화] {label} 실패: {e}")
    results.append({"account": label, "status": "error", "message": str(e)})
```

- API 호출, 파싱, DB 저장 중 어디서든 예외가 발생하면 해당 계정은 "error"로 처리
- total_synced에 더해지지 않음

**확인 방법:** 응답 results에 `"status": "error"` 항목이 있는지, 서버 로그에 `[주문동기화] ... 실패:` 메시지가 있는지 확인

**해결:** 에러 메시지에 따라 개별 대응

---

## _parse_smartstore_order 함수 분석

### status_map 불일치 문제

```python
# order.py 326~335행 (현재 코드)
status_map = {
    "PAYED": "pending",
    ...
    "CANCEL_REQUESTED": "pending",  # ← 문제: 스마트스토어는 CANCEL_REQUESTED가 아님
}
```

스킬 레퍼런스(`references/smartstore.md`)에서 정의한 매핑과 비교:

| 상태 | 스킬 레퍼런스 기준 | 실제 코드 | 차이 |
|------|---------------------|-----------|------|
| `CANCEL_DONE` | `cancelled` | **미포함** (status_map에 없음) | status_map에서 누락, `pending`으로 fallback |
| `RETURN_DONE` | `returned` | **미포함** | status_map에서 누락, `pending`으로 fallback |
| `CANCEL_REQUEST` | `cancel_requested` | 클레임 로직에서 처리 | 정상 (클레임 우선) |
| `CANCEL_REQUESTED` | 존재하지 않는 상태 | `pending`으로 매핑 | 오타 가능성. 실제 API는 `CANCEL_REQUEST` 사용 |

`status_map`에 `CANCEL_DONE`, `RETURN_DONE`, `CANCEL_REQUEST`, `COLLECTING`, `COLLECT_DONE` 등이 빠져있지만, 클레임 상태 분기 로직(422~427행)에서 별도로 처리하므로 **큰 문제는 아님**. 단, 클레임 필드가 없는 취소완료/반품완료 주문은 `pending`으로 잘못 매핑될 수 있음.

### market_status_map 불일치

```python
# order.py 370~381행
market_status_map = {
    "PAYED": "결제완료",  # ← 스킬에서는 "발송대기" (placeOrderStatus=OK일 때)
    ...
}
```

- `PAYED` 상태일 때 `market_status_map`에서 `"결제완료"`로 매핑하지만, 바로 아래 분기에서 `placeOrderStatus`에 따라 `"발주미확인"` 또는 `"발송대기"`로 덮어씌움 → 실질적 문제 없음

---

## 디버깅 체크리스트 (순서대로 확인)

| # | 체크 항목 | 확인 방법 | 예상 결과 |
|---|----------|-----------|-----------|
| 1 | 응답 JSON의 `results` 배열 확인 | `POST /sync-from-markets` 응답 확인 | results가 비어있으면 원인1, skip이면 원인2/6, error면 원인8 |
| 2 | results에 `fetched` 값 확인 | 응답의 `fetched` vs `synced` | fetched>0, synced=0이면 원인7 (이미 동기화됨) |
| 3 | 서버 로그 확인 | `[주문동기화]`, `[스마트스토어]` 로그 | 토큰/API 에러 추적 |
| 4 | DB 계정 확인 | `samba_market_account` 테이블 조회 | is_active=true, market_type='smartstore' 확인 |
| 5 | 인증정보 확인 | 계정의 additional_fields 또는 samba_settings | clientId/clientSecret 존재 여부 |
| 6 | days 확대 | `{"days": 30}` 으로 재요청 | 기간 부족 배제 |

---

## 가장 유력한 원인 TOP 3

1. **인증정보 누락** (원인 2) — clientId/clientSecret이 계정에도 settings에도 없어서 skip
2. **활성 계정 없음** (원인 1) — is_active=false이거나 계정 자체가 없음
3. **이미 동기화됨** (원인 7) — fetched는 있지만 모두 기존 주문이라 synced=0으로 보고

이 3가지를 순서대로 확인하면 대부분의 0건 문제를 해결할 수 있다.

---

## 권장 조치

### 즉시 확인

```sql
-- 1. 활성 스마트스토어 계정 존재 여부
SELECT id, market_type, market_name, is_active, additional_fields
FROM samba_market_account
WHERE market_type = 'smartstore' AND is_active = true;

-- 2. 공유 인증정보 존재 여부
SELECT key, value FROM samba_settings WHERE key = 'store_smartstore';

-- 3. 기존 동기화된 주문 확인
SELECT COUNT(*) FROM samba_order WHERE source = 'smartstore';
```

### 코드 개선 제안

1. **로깅 강화:** `get_orders()` 내부에서 raw API 응답을 DEBUG 레벨로 로깅
2. **응답에 fetched 명확화:** 현재도 `fetched`를 반환하지만, 프론트엔드에서 "0건 동기화" 메시지만 보여줄 경우 `fetched`와 `synced`를 구분하여 표시
3. **status_map 보완:** `CANCEL_DONE`, `RETURN_DONE` 등을 status_map에도 추가하여 클레임 필드 없이도 올바르게 매핑
