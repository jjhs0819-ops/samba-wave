# 플러그인 아키텍처 + 멀티테넌시 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마켓/소싱처를 플러그인으로 분리하여 파일 1개 추가로 확장 가능하게 하고, 멀티테넌시로 외부 고객 SaaS 대응

**Architecture:** ABC base 클래스가 공통 전처리(인증/정책/에러분류) 담당, 각 플러그인은 execute/transform만 구현. 기존 proxy/ 클라이언트 재사용. 멀티테넌시는 컬럼 격리(tenant_id) + JWT 확장.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, PostgreSQL, alembic, asyncio

**Spec:** `docs/superpowers/specs/2026-03-24-plugin-architecture-design.md`

---

## Phase A: 플러그인 기반 구조

### Task 1: 플러그인 디렉토리 + base 클래스 생성

**Files:**
- Create: `backend/backend/domain/samba/plugins/__init__.py`
- Create: `backend/backend/domain/samba/plugins/market_base.py`
- Create: `backend/backend/domain/samba/plugins/sourcing_base.py`
- Create: `backend/backend/domain/samba/plugins/markets/__init__.py`
- Create: `backend/backend/domain/samba/plugins/sourcing/__init__.py`

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p backend/backend/domain/samba/plugins/markets
mkdir -p backend/backend/domain/samba/plugins/sourcing
touch backend/backend/domain/samba/plugins/markets/__init__.py
touch backend/backend/domain/samba/plugins/sourcing/__init__.py
```

- [ ] **Step 2: MarketPlugin base 클래스 작성**

`backend/backend/domain/samba/plugins/market_base.py` — 스펙 162~292줄의 코드 그대로 작성.
핵심 메서드: `handle()`, `_load_auth()`, `_validate_category()`, `_apply_market_settings()`, `_classify_error()`
추상 메서드: `execute()`, `transform()`

- [ ] **Step 3: SourcingPlugin base 클래스 작성**

`backend/backend/domain/samba/plugins/sourcing_base.py` — 스펙 296~359줄의 코드 그대로 작성.
핵심 메서드: `safe_call()`, `_get_semaphore()`
추상 메서드: `search()`, `get_detail()`, `refresh()`

- [ ] **Step 4: Registry 작성 (자동 등록)**

`backend/backend/domain/samba/plugins/__init__.py` — 스펙 363~417줄.
`discover_plugins()`: markets/, sourcing/ 하위 스캔, import 실패 시 스킵, 앱 시작 시 자동 실행.

- [ ] **Step 5: 커밋**

```bash
git add backend/backend/domain/samba/plugins/
git commit -m "플러그인 base 클래스 + registry 생성"
```

---

### Task 2: 스마트스토어 마켓 플러그인 (첫 번째)

**Files:**
- Create: `backend/backend/domain/samba/plugins/markets/smartstore.py`
- Modify: `backend/backend/domain/samba/shipment/dispatcher.py` — dispatch_to_market에 플러그인 우선 호출 + 폴백 추가

- [ ] **Step 1: SmartStorePlugin 작성**

`plugins/markets/smartstore.py` — dispatcher.py의 `_handle_smartstore` (라인 124~480) 로직을 `execute()` 메서드로 이동.
`transform()` → `SmartStoreClient.transform_product` 위임.
`delete()` → statusType: SUSPENSION.

핵심 이동 대상:
- 인증정보 로드: base `_load_auth`로 대체 (계정별 추가 설정은 execute 내에서)
- 이미지 업로드 로직 (`_upload_safe`, `_upload_images`)
- 카탈로그/브랜드/속성 조회
- skip_image 판단 + 가격/재고 모드 분기
- `_try_send` (PUT/POST 전환 로직)

주의: 기존 `_handle_smartstore`의 account extras 주입 (라인 211~252)은 execute 내에서 유지. base `_apply_market_settings`는 배송비/재고 제한만 담당.

- [ ] **Step 2: dispatcher.py에 플러그인 우선 호출 추가**

`dispatch_to_market()` 함수 상단에 플러그인 체크 추가 (폴백 유지):

```python
from backend.domain.samba.plugins import MARKET_PLUGINS

async def dispatch_to_market(session, market_type, product, category_id, account, existing_product_no):
    # 플러그인 우선
    plugin = MARKET_PLUGINS.get(market_type)
    if plugin:
        return await plugin.handle(session, product, category_id, account, existing_product_no)
    # 레거시 폴백
    missing = validate_transform(market_type, product)
    ...  # 기존 코드 유지
```

- [ ] **Step 3: 동작 검증**

스마트스토어 계정으로 테스트 상품 1개 전송 → 기존과 동일하게 동작하는지 확인.
확인 사항: 이미지 업로드, 카탈로그 매칭, 등록/수정, 에러 메시지.

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/domain/samba/plugins/markets/smartstore.py
git add backend/backend/domain/samba/shipment/dispatcher.py
git commit -m "스마트스토어 마켓 플러그인 추출 + dispatcher 폴백 연동"
```

---

### Task 3: 나머지 마켓 플러그인 추출

**Files:**
- Create: `backend/backend/domain/samba/plugins/markets/coupang.py`
- Create: `backend/backend/domain/samba/plugins/markets/elevenst.py`
- Create: `backend/backend/domain/samba/plugins/markets/lotteon.py`
- Create: `backend/backend/domain/samba/plugins/markets/lottehome.py`
- Create: `backend/backend/domain/samba/plugins/markets/gsshop.py`
- Create: `backend/backend/domain/samba/plugins/markets/ssg.py`
- Create: `backend/backend/domain/samba/plugins/markets/kream.py`
- Create: `backend/backend/domain/samba/plugins/markets/toss.py`
- Create: `backend/backend/domain/samba/plugins/markets/rakuten.py`
- Create: `backend/backend/domain/samba/plugins/markets/amazon.py`
- Create: `backend/backend/domain/samba/plugins/markets/buyma.py`
- Create: `backend/backend/domain/samba/plugins/markets/stub.py` (ebay, lazada, qoo10, shopee, shopify, zoom — 각각 별도 클래스)

각 플러그인의 패턴:
```python
class CoupangPlugin(MarketPlugin):
    market_type = "coupang"
    policy_key = "쿠팡"

    def transform(self, product, category_id, **kwargs):
        return CoupangClient.transform_product(product, category_id, **kwargs)

    async def execute(self, session, product, creds, category_id, account, existing_no):
        # dispatcher.py의 _handle_coupang 로직 이동
        ...
```

- [ ] **Step 1: 쿠팡 플러그인** — `_handle_coupang` (dispatcher.py 581~680) → `plugins/markets/coupang.py`
- [ ] **Step 2: 11번가 플러그인** — `_handle_11st` → `plugins/markets/elevenst.py`
- [ ] **Step 3: 롯데ON 플러그인** — `_handle_lotteon` → `plugins/markets/lotteon.py`
- [ ] **Step 4: 롯데홈쇼핑 플러그인** — `_handle_lottehome` → `plugins/markets/lottehome.py`
- [ ] **Step 5: GS샵 플러그인** — `_handle_gsshop` → `plugins/markets/gsshop.py`
- [ ] **Step 6: SSG 플러그인** — `_handle_ssg` → `plugins/markets/ssg.py`
- [ ] **Step 7: KREAM 플러그인** — `_handle_kream` → `plugins/markets/kream.py`
- [ ] **Step 8: 토스/라쿠텐/아마존/바이마** — 각각 plugins/markets/에 파일 생성
- [ ] **Step 9: 스텁 마켓** — `plugins/markets/stub.py`에 ebay, lazada, qoo10, shopee, shopify, zoom 각각 별도 클래스

```python
# stub.py 예시
class EbayPlugin(MarketPlugin):
    market_type = "ebay"
    policy_key = "eBay"
    async def execute(self, ...): return {"success": False, "message": "eBay 미구현"}
    def transform(self, ...): return {}
```

- [ ] **Step 10: 각 플러그인 전송 테스트** — 계정이 있는 마켓부터 실제 전송 확인
- [ ] **Step 11: 커밋** — 마켓별 또는 3~4개 단위로 나누어 커밋

---

### Task 4: 무신사 소싱 플러그인

**Files:**
- Create: `backend/backend/domain/samba/plugins/sourcing/musinsa.py`

- [ ] **Step 1: MusinsaPlugin 작성**

refresher.py의 `_parse_musinsa` (라인 140~280 추정) → `refresh()` 메서드.
`search()` → `MusinsaClient.search_products` 위임.
`get_detail()` → `MusinsaClient.get_goods_detail` 위임.

```python
class MusinsaPlugin(SourcingPlugin):
    site_name = "MUSINSA"
    concurrency = 1
    request_interval = 0.2

    async def refresh(self, product):
        client = MusinsaClient()
        return await self.safe_call(client.get_goods_detail(product.site_product_id))
        # + RefreshResult 변환 로직 (기존 _parse_musinsa에서 이동)
```

- [ ] **Step 2: refresher.py에 플러그인 우선 호출 추가**

```python
from backend.domain.samba.plugins import SOURCING_PLUGINS

async def refresh_product(product, ...):
    plugin = SOURCING_PLUGINS.get(product.source_site)
    if plugin:
        return await plugin.refresh(product)
    # 레거시 폴백
    ...
```

- [ ] **Step 3: 동작 검증** — 무신사 상품 가격/재고 갱신 테스트
- [ ] **Step 4: 커밋**

---

### Task 5: KREAM 소싱 플러그인 + 스텁

**Files:**
- Create: `backend/backend/domain/samba/plugins/sourcing/kream.py`
- Create: `backend/backend/domain/samba/plugins/sourcing/stub.py`

- [ ] **Step 1: KreamPlugin 작성** — refresher.py `_parse_kream` → `refresh()`, 확장앱 큐 대기 로직 포함
- [ ] **Step 2: 스텁 소싱처** — `stub.py`에 GenericStubPlugin (미구현 소싱처 공통)
- [ ] **Step 3: 동작 검증**
- [ ] **Step 4: 커밋**

---

### Task 6: 레거시 핸들러 정리

**Files:**
- Modify: `backend/backend/domain/samba/shipment/dispatcher.py` — 인라인 핸들러 제거, ~50줄로 축소
- Modify: `backend/backend/domain/samba/collector/refresher.py` — 소싱처별 함수 제거

- [ ] **Step 1: 모든 마켓이 플러그인으로 동작하는지 확인**

```python
# 검증 코드
from backend.domain.samba.plugins import MARKET_PLUGINS, SOURCING_PLUGINS
print(f"마켓: {list(MARKET_PLUGINS.keys())}")
print(f"소싱: {list(SOURCING_PLUGINS.keys())}")
```

- [ ] **Step 2: dispatcher.py에서 레거시 핸들러 제거**

`_handle_smartstore`, `_handle_coupang` 등 인라인 함수 + `MARKET_HANDLERS` 딕셔너리 삭제.
`dispatch_to_market()`은 플러그인 호출만 유지 (스펙 419~452줄).

- [ ] **Step 3: refresher.py에서 레거시 함수 제거**

`_parse_musinsa`, `_parse_kream`, `_parse_generic_stub` 삭제.
`refresh_product()`은 플러그인 호출만 유지.

- [ ] **Step 4: 전체 테스트** — 수집 → 갱신 → 전송 E2E 확인
- [ ] **Step 5: 커밋**

```bash
git commit -m "레거시 핸들러 제거 — dispatcher 1600줄→50줄, refresher 소싱처 함수 제거"
```

---

## Phase B: 멀티테넌시

### Task 7: Tenant 모델 + alembic 마이그레이션

**Files:**
- Create: `backend/backend/domain/samba/tenant/__init__.py`
- Create: `backend/backend/domain/samba/tenant/model.py`
- Create: `backend/backend/domain/samba/tenant/repository.py`
- Create: `backend/backend/domain/samba/tenant/service.py`
- Create: alembic 마이그레이션 파일

- [ ] **Step 1: SambaTenant 모델 작성**

```python
# domain/samba/tenant/model.py
class SambaTenant(SQLModel, table=True):
    __tablename__ = "samba_tenants"
    id: str = Field(default_factory=lambda: f"tn_{ulid.new().str}", primary_key=True)
    name: str
    owner_user_id: str
    plan: str = Field(default="free")
    limits: dict = Field(default_factory=lambda: {
        "max_products": 1000,
        "max_markets": 3,
        "max_sourcing": 2,
    }, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

- [ ] **Step 2: Repository + Service 작성**

CRUD 기본 (get, create, update, list).

- [ ] **Step 3: alembic 마이그레이션 — samba_tenants 테이블 생성**

```bash
cd backend && alembic revision --autogenerate -m "samba_tenants 테이블 생성"
alembic upgrade head
```

- [ ] **Step 4: 모든 samba 모델에 tenant_id 컬럼 추가**

영향 모델: SambaCollectedProduct, SambaSearchFilter, SambaMarketAccount, SambaPolicy, SambaShipment, SambaOrder, SambaNameRule, SambaCategoryMapping, SambaDetailTemplate, SambaForbiddenWord, SambaSettings.

```python
# 각 모델에 추가
tenant_id: Optional[str] = Field(
    default=None, sa_column=Column(String, ForeignKey("samba_tenants.id"), index=True)
)
```

- [ ] **Step 5: User 모델에 tenant_id + role 추가**

```python
tenant_id: Optional[str] = Field(default=None, foreign_key="samba_tenants.id")
role: str = Field(default="member")  # owner / admin / member
```

- [ ] **Step 6: alembic 마이그레이션 — tenant_id 컬럼 추가**

```bash
alembic revision --autogenerate -m "전체 samba 테이블 tenant_id 추가"
alembic upgrade head
```

- [ ] **Step 7: 기존 데이터 마이그레이션**

기본 테넌트 생성 + 기존 행에 tenant_id 일괄 업데이트:

```sql
INSERT INTO samba_tenants (id, name, owner_user_id, plan)
VALUES ('tn_default', '기본 테넌트', '', 'pro');

UPDATE samba_collected_products SET tenant_id = 'tn_default' WHERE tenant_id IS NULL;
UPDATE samba_search_filters SET tenant_id = 'tn_default' WHERE tenant_id IS NULL;
-- ... 나머지 테이블 동일
```

- [ ] **Step 8: 커밋**

```bash
git commit -m "Tenant 모델 + 전체 samba 테이블 tenant_id 마이그레이션"
```

---

### Task 8: Tenant 미들웨어 + API 적용

**Files:**
- Create: `backend/backend/domain/samba/tenant/middleware.py`
- Modify: 모든 samba 라우터 — tenant_id Depends 추가

- [ ] **Step 1: tenant 미들웨어 작성**

```python
# domain/samba/tenant/middleware.py

from fastapi import Depends, HTTPException, Request
from backend.domain.auth.service import get_current_user

async def get_current_tenant_id(request: Request) -> str:
    """JWT → user → tenant_id 추출."""
    user = await get_current_user(request)
    if not user or not user.tenant_id:
        raise HTTPException(403, "테넌트 미설정")
    return user.tenant_id

async def get_optional_tenant_id(request: Request) -> str | None:
    """테넌트 ID 선택적 추출 (인증 없이도 동작하는 API용)."""
    try:
        return await get_current_tenant_id(request)
    except Exception:
        return None
```

- [ ] **Step 2: 플랜 제한 체크 헬퍼**

```python
# domain/samba/tenant/middleware.py에 추가

async def check_product_limit(tenant_id: str, session):
    tenant = await SambaTenantRepository(session).get_async(tenant_id)
    if not tenant:
        raise HTTPException(403, "테넌트 없음")
    max_products = (tenant.limits or {}).get("max_products", 1000)
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlalchemy import func
    count = (await session.execute(
        select(func.count()).where(SambaCollectedProduct.tenant_id == tenant_id)
    )).scalar() or 0
    if count >= max_products:
        raise HTTPException(403, f"상품 수 제한 초과 ({count}/{max_products})")
```

- [ ] **Step 3: 주요 samba 라우터에 tenant_id 적용 (과도기)**

초기에는 `get_optional_tenant_id`로 선택적 적용 (기존 인증 없는 API 호환):

```python
# collector.py 예시
@router.get("/products/scroll")
async def scroll_products(
    tenant_id: str | None = Depends(get_optional_tenant_id),
    ...
):
    if tenant_id:
        conditions.append(_CP.tenant_id == tenant_id)
```

대상 라우터: collector.py, shipment.py, policy.py, account.py, category.py, order.py

- [ ] **Step 4: 상품 생성 시 플랜 제한 체크**

collector.py의 `create_collected_product`, `bulk_create_collected_products`에서 `check_product_limit` 호출.

- [ ] **Step 5: 동작 검증** — 기존 API가 tenant_id 없이도 동작하는지 확인 (하위호환)
- [ ] **Step 6: 커밋**

```bash
git commit -m "Tenant 미들웨어 + samba 라우터 tenant_id 선택적 필터링"
```

---

## 구현 순서 요약

```
Phase A (플러그인):
  Task 1: base + registry          ← 의존성 없음, 바로 시작
  Task 2: 스마트스토어 플러그인     ← Task 1 완료 후
  Task 3: 나머지 마켓 플러그인      ← Task 2 검증 후
  Task 4: 무신사 소싱 플러그인      ← Task 1 완료 후 (Task 2와 병렬 가능)
  Task 5: KREAM + 스텁             ← Task 4 완료 후
  Task 6: 레거시 정리               ← Task 3, 5 완료 후

Phase B (멀티테넌시):
  Task 7: Tenant 모델 + 마이그레이션 ← Phase A 완료 후 (또는 병렬)
  Task 8: 미들웨어 + API 적용       ← Task 7 완료 후
```
