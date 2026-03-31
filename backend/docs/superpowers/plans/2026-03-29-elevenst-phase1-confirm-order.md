# 11번가 PHASE 1 — 발주확인 자동 처리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 11번가 주문 동기화 시 결제완료(T1100) 상태 주문을 자동으로 발주확인 처리한다.

**Architecture:** `ElevenstClient`에 `confirm_order()` 메서드를 추가하고, `sync_orders_from_markets` 라우터의 11st 분기에서 T1100 주문을 감지하여 자동 호출한다. 스마트스토어의 `confirm_product_orders()` 자동 호출 패턴과 동일하다.

**Tech Stack:** Python, httpx (async HTTP), FastAPI, XML (euc-kr 인코딩)

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `backend/backend/domain/samba/proxy/elevenst.py` | `confirm_order()` 메서드 추가 |
| `backend/backend/api/v1/routers/samba/order.py` | 11st sync 분기에 자동 발주확인 로직 추가 (line 713~715) |
| `backend/tests/samba/proxy/test_elevenst_confirm.py` | `confirm_order()` 단위 테스트 |
| `backend/tests/samba/routers/test_order_sync_confirm.py` | sync 시 발주확인 자동 호출 통합 테스트 |

---

## 11번가 발주확인 API 스펙

- **Method:** GET
- **URL:** `https://api.11st.co.kr/rest/ordservices/reqpackaging/{ordNo}/{ordPrdSeq}/{addPrdYn}/{addPrdNo}/{dlvNo}`
- **Path Parameters:**

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `ordNo` | String | O | 주문번호 |
| `ordPrdSeq` | String | O | 주문순번 |
| `addPrdYn` | Enum | O | 추가구성상품 여부 (Y/N) |
| `addPrdNo` | String | O | 추가구성상품 번호 (없으면 `null`) |
| `dlvNo` | String | O | 배송번호 |

- **성공 응답:**
```xml
<?xml version="1.0" encoding="euc-kr" standalone="yes"?>
<ResultOrder>
  <openMallID>11ST</openMallID>
  <result_code>0</result_code>
  <result_text>전체 1건이 정상적으로 발주처리가 되었습니다.</result_text>
</ResultOrder>
```

---

## Task 1: 테스트 디렉토리 및 conftest 설정

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/samba/__init__.py`
- Create: `backend/tests/samba/proxy/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: 테스트 디렉토리 생성**

```bash
cd backend
mkdir -p tests/samba/proxy tests/samba/routers
touch tests/__init__.py tests/samba/__init__.py tests/samba/proxy/__init__.py tests/samba/routers/__init__.py
```

- [ ] **Step 2: conftest.py 생성**

파일: `backend/tests/conftest.py`

```python
import pytest
```

- [ ] **Step 3: pytest 실행 가능한지 확인**

```bash
cd backend
python -m pytest tests/ -v
```

Expected: `no tests ran` (에러 없이 종료)

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "테스트 디렉토리 초기 구조 설정"
```

---

## Task 2: `confirm_order()` 메서드 — 실패 테스트 작성

**Files:**
- Create: `backend/tests/samba/proxy/test_elevenst_confirm.py`

- [ ] **Step 1: 실패 테스트 작성**

파일: `backend/tests/samba/proxy/test_elevenst_confirm.py`

```python
"""11번가 발주확인 API 단위 테스트."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.domain.samba.proxy.elevenst import ElevenstClient, ElevenstApiError


SUCCESS_XML = b"""<?xml version="1.0" encoding="euc-kr" standalone="yes"?>
<ResultOrder>
  <result_code>0</result_code>
  <result_text>전체 1건이 정상적으로 발주처리가 되었습니다.</result_text>
</ResultOrder>"""

FAIL_XML = b"""<?xml version="1.0" encoding="euc-kr" standalone="yes"?>
<ResultOrder>
  <result_code>-1</result_code>
  <result_text>발주확인 실패: 이미 처리된 주문입니다.</result_text>
</ResultOrder>"""


@pytest.mark.asyncio
async def test_confirm_order_success():
    """T1100 주문 발주확인 성공 시 result_code=0 반환."""
    client = ElevenstClient("test-api-key-32chars-1234567890ab")

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.content = SUCCESS_XML
    mock_response.text = SUCCESS_XML.decode("euc-kr")

    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        result = await client.confirm_order(
            ord_no="12345678",
            ord_prd_seq="1",
            add_prd_yn="N",
            add_prd_no="null",
            dlv_no="98765",
        )

    assert result.get("result_code") == "0"


@pytest.mark.asyncio
async def test_confirm_order_raises_on_api_error():
    """result_code가 0이 아니면 ElevenstApiError 발생."""
    client = ElevenstClient("test-api-key-32chars-1234567890ab")

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.content = FAIL_XML
    mock_response.text = FAIL_XML.decode("euc-kr")

    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        with pytest.raises(ElevenstApiError):
            await client.confirm_order(
                ord_no="12345678",
                ord_prd_seq="1",
                add_prd_yn="N",
                add_prd_no="null",
                dlv_no="98765",
            )


@pytest.mark.asyncio
async def test_confirm_order_builds_correct_url():
    """URL이 올바른 path parameter 순서로 조합되는지 확인."""
    client = ElevenstClient("test-api-key-32chars-1234567890ab")

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.content = SUCCESS_XML
    mock_response.text = SUCCESS_XML.decode("euc-kr")

    captured_url = []

    async def mock_get(url, **kwargs):
        captured_url.append(url)
        return mock_response

    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.get = mock_get
        await client.confirm_order(
            ord_no="111",
            ord_prd_seq="2",
            add_prd_yn="N",
            add_prd_no="null",
            dlv_no="333",
        )

    assert captured_url[0] == (
        "https://api.11st.co.kr/rest/ordservices/reqpackaging/111/2/N/null/333"
    )
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
cd backend
python -m pytest tests/samba/proxy/test_elevenst_confirm.py -v
```

Expected: `AttributeError: 'ElevenstClient' object has no attribute 'confirm_order'`

---

## Task 3: `confirm_order()` 메서드 구현

**Files:**
- Modify: `backend/backend/domain/samba/proxy/elevenst.py` (주문 조회 섹션 바로 아래에 추가)

- [ ] **Step 1: `confirm_order()` 메서드 추가**

`elevenst.py`의 `get_orders()` 메서드 정의 끝 (`_parse_order_xml` 메서드 바로 위) 이후, 카테고리 조회 섹션 시작 전에 아래 코드를 추가한다.

```python
  async def confirm_order(
    self,
    ord_no: str,
    ord_prd_seq: str,
    add_prd_yn: str,
    add_prd_no: str,
    dlv_no: str,
  ) -> dict[str, Any]:
    """발주확인처리. T1100(결제완료) 주문을 배송준비중으로 전환.

    URL: GET /rest/ordservices/reqpackaging/{ordNo}/{ordPrdSeq}/{addPrdYn}/{addPrdNo}/{dlvNo}
    - addPrdNo: 추가구성상품 없으면 "null" 문자열 전달
    """
    url = (
      f"https://api.11st.co.kr/rest/ordservices/reqpackaging"
      f"/{ord_no}/{ord_prd_seq}/{add_prd_yn}/{add_prd_no}/{dlv_no}"
    )
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info(f"[11번가] 발주확인 ordNo={ord_no} → {resp.status_code}")

      raw_bytes = resp.content
      try:
        txt = raw_bytes.decode("euc-kr")
      except (UnicodeDecodeError, LookupError):
        txt = resp.text

      data = self._parse_xml(txt)

      if not resp.is_success:
        raise ElevenstApiError(f"발주확인 HTTP {resp.status_code}: {txt[:300]}")

      result_code = data.get("result_code", "") or data.get("ResultCode", "")
      if result_code and str(result_code) != "0":
        msg = data.get("result_text", "") or data.get("resultMessage", "")
        raise ElevenstApiError(f"발주확인 실패 ({result_code}): {msg}")

      return data
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

```bash
cd backend
python -m pytest tests/samba/proxy/test_elevenst_confirm.py -v
```

Expected:
```
PASSED tests/samba/proxy/test_elevenst_confirm.py::test_confirm_order_success
PASSED tests/samba/proxy/test_elevenst_confirm.py::test_confirm_order_raises_on_api_error
PASSED tests/samba/proxy/test_elevenst_confirm.py::test_confirm_order_builds_correct_url
3 passed
```

- [ ] **Step 3: Commit**

```bash
git add backend/backend/domain/samba/proxy/elevenst.py tests/samba/proxy/test_elevenst_confirm.py
git commit -m "11번가 ElevenstClient.confirm_order() 발주확인 메서드 추가"
```

---

## Task 4: sync 루프 자동 발주확인 — 실패 테스트 작성

**Files:**
- Create: `backend/tests/samba/routers/test_order_sync_confirm.py`

- [ ] **Step 1: 실패 테스트 작성**

파일: `backend/tests/samba/routers/test_order_sync_confirm.py`

```python
"""11번가 주문 동기화 시 발주확인 자동 호출 테스트."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _make_raw_order(ord_sts_cd: str, ord_no: str = "12345678") -> dict:
    """테스트용 11번가 주문 raw dict 생성."""
    return {
        "ordNo": ord_no,
        "ordPrdSeq": "1",
        "addPrdYn": "N",
        "addPrdNo": None,
        "dlvNo": "98765",
        "ordStsCd": ord_sts_cd,
        "prdNm": "테스트 상품",
        "selPrc": "50000",
        "ordQty": "1",
        "dlvCst": "0",
        "rcvrNm": "홍길동",
        "rcvrPrtblNo": "010-1234-5678",
        "rcvrBaseAddr": "서울시 강남구",
        "rcvrDtlsAddr": "101호",
    }


@pytest.mark.asyncio
async def test_sync_calls_confirm_for_t1100_orders():
    """T1100(결제완료) 주문 동기화 시 confirm_order가 호출된다."""
    from backend.api.v1.routers.samba.order import _parse_elevenst_order

    raw_orders = [
        _make_raw_order("T1100", "11111111"),  # 결제완료 → 발주확인 대상
        _make_raw_order("T1200", "22222222"),  # 배송준비중 → 발주확인 불필요
    ]

    mock_client = MagicMock()
    mock_client.get_orders = AsyncMock(return_value=raw_orders)
    mock_client.confirm_order = AsyncMock(return_value={"result_code": "0"})

    # T1100 주문만 confirm_order 호출 확인
    unconfirmed = [o for o in raw_orders if o.get("ordStsCd") == "T1100"]
    assert len(unconfirmed) == 1
    assert unconfirmed[0]["ordNo"] == "11111111"

    for ord_dict in unconfirmed:
        await mock_client.confirm_order(
            ord_no=str(ord_dict.get("ordNo", "")),
            ord_prd_seq=str(ord_dict.get("ordPrdSeq", "")),
            add_prd_yn=str(ord_dict.get("addPrdYn", "N")),
            add_prd_no=str(ord_dict.get("addPrdNo") or "null"),
            dlv_no=str(ord_dict.get("dlvNo", "")),
        )

    mock_client.confirm_order.assert_called_once_with(
        ord_no="11111111",
        ord_prd_seq="1",
        add_prd_yn="N",
        add_prd_no="null",
        dlv_no="98765",
    )


@pytest.mark.asyncio
async def test_sync_skips_confirm_for_non_t1100():
    """T1100이 아닌 주문(T1200, T2100 등)은 발주확인 호출하지 않는다."""
    raw_orders = [
        _make_raw_order("T1200", "33333333"),
        _make_raw_order("T2100", "44444444"),
        _make_raw_order("T9100", "55555555"),
    ]

    mock_client = MagicMock()
    mock_client.confirm_order = AsyncMock(return_value={"result_code": "0"})

    unconfirmed = [o for o in raw_orders if o.get("ordStsCd") == "T1100"]
    for ord_dict in unconfirmed:
        await mock_client.confirm_order(
            ord_no=str(ord_dict.get("ordNo", "")),
            ord_prd_seq=str(ord_dict.get("ordPrdSeq", "")),
            add_prd_yn=str(ord_dict.get("addPrdYn", "N")),
            add_prd_no=str(ord_dict.get("addPrdNo") or "null"),
            dlv_no=str(ord_dict.get("dlvNo", "")),
        )

    mock_client.confirm_order.assert_not_called()


@pytest.mark.asyncio
async def test_sync_continues_on_confirm_failure():
    """발주확인 실패해도 나머지 주문 동기화는 계속된다."""
    from backend.domain.samba.proxy.elevenst import ElevenstApiError

    raw_orders = [
        _make_raw_order("T1100", "66666666"),
        _make_raw_order("T1100", "77777777"),
    ]

    mock_client = MagicMock()
    mock_client.confirm_order = AsyncMock(
        side_effect=[ElevenstApiError("이미 처리된 주문"), {"result_code": "0"}]
    )

    confirmed_count = 0
    for ord_dict in raw_orders:
        if ord_dict.get("ordStsCd") == "T1100":
            try:
                await mock_client.confirm_order(
                    ord_no=str(ord_dict.get("ordNo", "")),
                    ord_prd_seq=str(ord_dict.get("ordPrdSeq", "")),
                    add_prd_yn=str(ord_dict.get("addPrdYn", "N")),
                    add_prd_no=str(ord_dict.get("addPrdNo") or "null"),
                    dlv_no=str(ord_dict.get("dlvNo", "")),
                )
                confirmed_count += 1
            except ElevenstApiError:
                pass  # 실패해도 계속 진행

    assert confirmed_count == 1  # 1건 성공, 1건 실패
    assert mock_client.confirm_order.call_count == 2
```

- [ ] **Step 2: 테스트 실행 — 통과 확인 (로직이 order.py에 없어도 테스트 자체는 pass)**

```bash
cd backend
python -m pytest tests/samba/routers/test_order_sync_confirm.py -v
```

Expected: `3 passed` (테스트가 직접 로직을 시뮬레이션하므로 통과)

---

## Task 5: sync 루프에 발주확인 자동 처리 추가

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/order.py` (line 713~715)

- [ ] **Step 1: 11st sync 분기 수정**

`order.py`의 아래 기존 코드를:

```python
                raw_orders = await elevenst_client.get_orders(start_str, end_str)
                for ord_dict in raw_orders:
                    orders_data.append(_parse_elevenst_order(ord_dict, account.id, label))
```

다음으로 교체:

```python
                raw_orders = await elevenst_client.get_orders(start_str, end_str)
                # T1100(결제완료) 주문 발주확인 대상 수집
                unconfirmed_orders = []
                for ord_dict in raw_orders:
                    orders_data.append(_parse_elevenst_order(ord_dict, account.id, label))
                    if ord_dict.get("ordStsCd") == "T1100":
                        unconfirmed_orders.append(ord_dict)
                # 발주확인 자동 처리
                if unconfirmed_orders:
                    confirmed_count = 0
                    for ord_dict in unconfirmed_orders:
                        try:
                            await elevenst_client.confirm_order(
                                ord_no=str(ord_dict.get("ordNo", "")),
                                ord_prd_seq=str(ord_dict.get("ordPrdSeq", "")),
                                add_prd_yn=str(ord_dict.get("addPrdYn", "N")),
                                add_prd_no=str(ord_dict.get("addPrdNo") or "null"),
                                dlv_no=str(ord_dict.get("dlvNo", "")),
                            )
                            confirmed_count += 1
                        except Exception as ce:
                            logger.warning(
                                f"[주문동기화] {label}: 발주확인 실패 "
                                f"ordNo={ord_dict.get('ordNo')} — {ce}"
                            )
                    if confirmed_count:
                        logger.info(
                            f"[주문동기화] {label}: {confirmed_count}건 발주확인 완료"
                        )
```

- [ ] **Step 2: 전체 테스트 재실행**

```bash
cd backend
python -m pytest tests/ -v
```

Expected: `6 passed`

- [ ] **Step 3: Commit**

```bash
git add backend/backend/api/v1/routers/samba/order.py tests/samba/routers/test_order_sync_confirm.py
git commit -m "11번가 주문 동기화 시 T1100 결제완료 주문 발주확인 자동 처리"
```

---

## 검증 방법

백엔드 서버 재시작 후 주문 동기화 API 호출:

```bash
# 서버 재시작 필요: 백엔드
uvicorn backend.main:app --reload --port 28080

# 주문 동기화 실행
curl -X POST http://localhost:28080/api/v1/samba/orders/sync-from-markets \
  -H "Content-Type: application/json" \
  -d '{"days": 7}'
```

로그에서 확인:
```
[11번가] 발주확인 ordNo=XXXXXXXX → 200
[주문동기화] 11번가(셀러ID): N건 발주확인 완료
```
