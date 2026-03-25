# 플러그인 아키텍처 + 멀티테넌시 설계

> 마켓/소싱처 플러그인 인터페이스 + SaaS 멀티테넌시 — 외부 유료 서비스 대응

## 목표

1. **플러그인**: 새 마켓/소싱처 = 파일 1개 추가 (기존 코드 수정 0)
2. **멀티테넌시**: 외부 고객이 각자 마켓 계정 연결, 본인 상품만 관리
3. **과금 준비**: tenant.plan + limits 구조만 선 설계, 결제 연동은 추후

## 현재 문제

| 파일 | 줄 수 | 문제 |
|------|-------|------|
| dispatcher.py | 1,600 | 17개 마켓 핸들러가 한 파일에 인라인 |
| refresher.py | 613 | 소싱처별 갱신 함수가 한 파일에 인라인 |
| collector.py | 3,187 | 수집 로직이 라우터에 직접 작성 |
| 전체 | - | tenant 개념 없음, 데이터 격리 없음, 단일 사용자 전제 |

## 설계 방향

**플러그인**: ABC 인터페이스 + base 공통 전처리 + 각 플러그인은 변환/API 호출만 구현.
**멀티테넌시**: 컬럼 격리 (`tenant_id` on every table) + 기존 JWT 인증 확장.
**과금**: `Tenant.plan`, `Tenant.limits` 필드만 선 설계, PG 연동은 고객 확보 후.

기존 `proxy/` 클라이언트(smartstore.py, musinsa.py 등)는 **그대로 유지**. 플러그인이 클라이언트를 import해서 사용.

---

## 멀티테넌시 설계

### Tenant 모델

```python
# domain/samba/tenant/model.py

class SambaTenant(SQLModel, table=True):
    __tablename__ = "samba_tenants"

    id: str = Field(default_factory=lambda: f"tn_{ulid.new().str}", primary_key=True)
    name: str                          # 사업자명 / 상호
    owner_user_id: str                 # 최초 생성 User ID (FK)
    plan: str = "free"                 # free / basic / pro / enterprise
    limits: dict = Field(default_factory=lambda: {
        "max_products": 1000,          # 상품 수 제한
        "max_markets": 3,              # 마켓 계정 수 제한
        "max_sourcing": 2,             # 소싱처 수 제한
    })
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
```

### User 모델 확장

```python
# 기존 User 모델에 추가
class User(SQLModel, table=True):
    # ... 기존 필드 ...
    tenant_id: Optional[str] = Field(default=None, foreign_key="samba_tenants.id")
    role: str = "member"               # owner / admin / member
```

### 테넌트 격리 — 모든 samba 테이블에 tenant_id 추가

```python
# 영향받는 테이블 (컬럼 추가)
SambaCollectedProduct.tenant_id   # 상품
SambaSearchFilter.tenant_id       # 검색필터
SambaMarketAccount.tenant_id      # 마켓 계정
SambaPolicy.tenant_id             # 정책
SambaShipment.tenant_id           # 전송 이력
SambaOrder.tenant_id              # 주문
SambaNameRule.tenant_id           # 상품명 규칙
SambaCategoryMapping.tenant_id    # 카테고리 매핑
SambaDetailTemplate.tenant_id     # 상세 템플릿
SambaForbiddenWord.tenant_id      # 금지어 (글로벌 + 테넌트별)
SambaSettings.tenant_id           # 설정 (글로벌 + 테넌트별)
```

### API 미들웨어 — 자동 tenant 필터링

```python
# middleware/tenant.py

async def get_current_tenant(request: Request) -> str:
    """JWT에서 user_id → tenant_id 추출. 모든 samba API에 의존성 주입."""
    user = await get_current_user(request)  # 기존 JWT 인증
    if not user.tenant_id:
        raise HTTPException(403, "테넌트 미설정")
    return user.tenant_id

# 사용 예시 — 모든 samba 라우터에 적용
@router.get("/products/scroll")
async def scroll_products(
    tenant_id: str = Depends(get_current_tenant),  # 자동 주입
    session: AsyncSession = Depends(get_read_session_dependency),
):
    # 쿼리에 자동으로 .where(tenant_id == tenant_id) 추가
    ...
```

### 플랜별 제한 체크

```python
# middleware/limits.py

async def check_product_limit(tenant_id: str, session):
    """상품 생성 전 플랜 제한 체크."""
    tenant = await get_tenant(session, tenant_id)
    current = await count_products(session, tenant_id)
    max_allowed = tenant.limits.get("max_products", 1000)
    if current >= max_allowed:
        raise HTTPException(
            403,
            f"상품 수 제한 초과 ({current}/{max_allowed}). 플랜을 업그레이드해주세요."
        )
```

### 과도기 전략 (기존 데이터 마이그레이션)

```
1. 기본 테넌트 생성: tenant_id = "tn_default" (기존 데이터 귀속)
2. 모든 기존 행에 tenant_id = "tn_default" 일괄 업데이트
3. tenant_id NOT NULL + 인덱스 추가
4. API 미들웨어 활성화
```

---

## 디렉토리 구조

```
backend/domain/samba/plugins/
├── __init__.py              # 자동 등록 (registry)
├── market_base.py           # MarketPlugin ABC + 공통 전처리
├── sourcing_base.py         # SourcingPlugin ABC + 공통 갱신
├── markets/
│   ├── __init__.py
│   ├── smartstore.py        # dispatcher._handle_smartstore → 이동
│   ├── coupang.py
│   ├── elevenst.py
│   ├── lotteon.py
│   ├── lottehome.py
│   ├── gsshop.py
│   ├── ssg.py
│   ├── kream.py
│   ├── toss.py
│   ├── rakuten.py
│   ├── amazon.py
│   ├── buyma.py
│   └── stub.py              # ebay, lazada, qoo10, shopee, shopify, zoom
└── sourcing/
    ├── __init__.py
    ├── musinsa.py            # refresher._parse_musinsa + 수집 로직
    ├── kream.py              # refresher._parse_kream + 확장앱 큐
    └── stub.py               # 미구현 소싱처 공통 스텁
```

## MarketPlugin 인터페이스

```python
# plugins/market_base.py

from abc import ABC, abstractmethod
from typing import Any

class MarketPlugin(ABC):
    """마켓 플러그인 기본 클래스.

    새 마켓 추가 시 execute()와 transform() 2개만 구현.
    인증 로드, 정책 주입, 에러 분류는 base가 처리.
    """
    market_type: str                    # "smartstore"
    policy_key: str                     # "스마트스토어" (정책 한글키)
    required_fields: list[str] = ["name", "sale_price"]

    # ── base 공통 전처리 ──

    async def handle(
        self, session, product: dict, category_id: str,
        account, existing_no: str = "",
    ) -> dict[str, Any]:
        """마켓 전송 진입점. dispatcher.dispatch_to_market() 대체."""
        # 1. 인증정보 로드 (account.additional_fields → settings 폴백)
        creds = await self._load_auth(session, account)
        if not creds:
            return {"success": False, "message": f"{self.market_type} 인증정보 없음"}

        # 2. 카테고리 검증
        category_id = self._validate_category(category_id)

        # 3. 정책에서 마켓별 설정 주입 (배송비, 재고제한, AS전화 등)
        product = await self._apply_market_settings(session, product, account)

        # 4. 카테고리 없으면 조기 반환
        if not category_id:
            return {"success": False, "message": f"{self.market_type} 카테고리 코드 없음"}

        # 5. 플러그인 실행 + 에러 분류
        try:
            return await self.execute(session, product, creds, category_id, account, existing_no)
        except Exception as e:
            return {"success": False, "error_type": self._classify_error(e), "message": str(e)}

    def _classify_error(self, exc: Exception) -> str:
        """에러 분류 — 프론트 UI에서 사용."""
        msg = str(exc).lower()
        if "401" in msg or "403" in msg or "token" in msg:
            return "auth_failed"
        if "timeout" in msg or "connect" in msg:
            return "network"
        if "400" in msg or "invalid" in msg:
            return "schema_changed"
        return "unknown"

    async def _load_auth(self, session, account) -> dict | None:
        """인증정보 로드 — account → settings 폴백. 마켓별 오버라이드 가능."""
        creds = {}
        if account:
            extras = account.additional_fields or {}
            creds = {k: v for k, v in extras.items() if v}
        if not creds:
            # dispatcher.py의 _get_setting 패턴 참조
            from backend.domain.samba.forbidden.model import SambaSettings
            from sqlmodel import select
            stmt = select(SambaSettings).where(SambaSettings.key == f"store_{self.market_type}")
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row and isinstance(row.value, dict):
                creds = row.value
        return creds or None

    def _validate_category(self, category_id: str) -> str:
        """카테고리 코드 검증. 비숫자면 빈 문자열 반환 → handle에서 조기 반환."""
        if category_id and not category_id.isdigit():
            return ""
        return category_id

    async def _apply_market_settings(self, session, product: dict, account) -> dict:
        """정책에서 마켓별 설정 읽어서 product에 주입."""
        policy_id = product.get("applied_policy_id")
        if not policy_id:
            return product
        from backend.domain.samba.policy.repository import SambaPolicyRepository
        policy_repo = SambaPolicyRepository(session)
        policy = await policy_repo.get_async(policy_id)
        if policy and policy.market_policies:
            mp = policy.market_policies.get(self.policy_key, {})
            if mp.get("shippingCost"):
                product["_delivery_fee_type"] = "PAID"
                product["_delivery_base_fee"] = int(mp["shippingCost"])
            if mp.get("maxStock"):
                product["_max_stock"] = mp["maxStock"]
        # 계정별 추가 설정 (AS전화, 반품안심 등)
        if account:
            extras = account.additional_fields or {}
            if extras.get("asPhone"):
                product["_as_phone"] = extras["asPhone"]
        return product

    # ── 각 마켓이 구현 ──

    @abstractmethod
    async def execute(
        self, session, product: dict, creds: dict,
        category_id: str, account, existing_no: str,
    ) -> dict[str, Any]:
        """마켓 API 호출. 현재 _handle_smartstore 본체에 해당.

        Returns:
            {"success": bool, "message": str, "data": dict}
            실패 시 {"success": False, "error_type": str, "message": str}
        """
        ...

    @abstractmethod
    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → 마켓 API 포맷 변환.
        현재 SmartStoreClient.transform_product에 해당."""
        ...

    # ── 선택 구현 ──

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        """판매중지/삭제. 기본: 미지원."""
        return {"success": False, "message": f"{self.market_type} 삭제 미지원"}

    async def test_auth(self, session, account) -> bool:
        """인증 테스트. 기본: True."""
        return True
```

## SourcingPlugin 인터페이스

```python
# plugins/sourcing_base.py

from abc import ABC, abstractmethod
from typing import Any

class SourcingPlugin(ABC):
    """소싱처 플러그인 기본 클래스.

    새 소싱처 추가 시 search(), get_detail(), refresh() 3개 구현.
    동시성 제어, 에러 로깅은 base가 처리.
    """
    site_name: str              # "MUSINSA"
    concurrency: int = 5        # 동시 요청 수 (무신사=1)
    request_interval: float = 0 # 요청 간 딜레이(초)

    # ── base가 처리하는 동시성 제어 ──

    def _get_semaphore(self) -> "asyncio.Semaphore":
        """사이트별 세마포어 반환 (싱글턴)."""
        import asyncio
        if not hasattr(self, "_sem"):
            self._sem = asyncio.Semaphore(self.concurrency)
        return self._sem

    async def safe_call(self, coro):
        """동시성 제어 + 요청 간 딜레이 적용. search/get_detail/refresh 내에서 사용."""
        import asyncio
        async with self._get_semaphore():
            if self.request_interval > 0:
                await asyncio.sleep(self.request_interval)
            return await coro

    # ── 각 소싱처가 구현 ──

    @abstractmethod
    async def search(self, keyword: str, **filters) -> list[dict]:
        """키워드 검색 → 상품 목록 반환.

        Returns: [{site_product_id, name, sale_price, images, ...}, ...]
        """
        ...

    @abstractmethod
    async def get_detail(self, site_product_id: str) -> dict:
        """상품 상세 조회.

        Returns: {name, images[], detail_images[], options[],
                  sale_price, original_price, category, ...}
        """
        ...

    @abstractmethod
    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신. 현재 refresher._parse_musinsa에 해당.

        Returns: RefreshResult(new_sale_price, new_cost, new_options, ...)
        """
        ...

    async def test_auth(self) -> bool:
        """인증 테스트. 기본: True."""
        return True
```

## 자동 등록 (Registry)

```python
# plugins/__init__.py

import importlib
import pkgutil
from pathlib import Path

MARKET_PLUGINS: dict[str, "MarketPlugin"] = {}
SOURCING_PLUGINS: dict[str, "SourcingPlugin"] = {}

def discover_plugins():
    """plugins/markets/, plugins/sourcing/ 하위 파일을 스캔하여 자동 등록.

    import 실패해도 앱 기동을 막지 않음 — 해당 플러그인만 스킵.
    """
    import logging
    log = logging.getLogger(__name__)
    from .market_base import MarketPlugin
    from .sourcing_base import SourcingPlugin

    # markets/ 디렉토리 스캔
    markets_dir = Path(__file__).parent / "markets"
    for _, name, _ in pkgutil.iter_modules([str(markets_dir)]):
        try:
            mod = importlib.import_module(f".markets.{name}", package=__package__)
        except Exception as e:
            log.warning(f"[플러그인] markets/{name} 로드 실패 — 스킵: {e}")
            continue
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if (isinstance(cls, type) and issubclass(cls, MarketPlugin)
                and cls is not MarketPlugin and hasattr(cls, "market_type")):
                instance = cls()
                MARKET_PLUGINS[instance.market_type] = instance

    # sourcing/ 디렉토리 스캔
    sourcing_dir = Path(__file__).parent / "sourcing"
    for _, name, _ in pkgutil.iter_modules([str(sourcing_dir)]):
        try:
            mod = importlib.import_module(f".sourcing.{name}", package=__package__)
        except Exception as e:
            log.warning(f"[플러그인] sourcing/{name} 로드 실패 — 스킵: {e}")
            continue
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if (isinstance(cls, type) and issubclass(cls, SourcingPlugin)
                and cls is not SourcingPlugin and hasattr(cls, "site_name")):
                instance = cls()
                SOURCING_PLUGINS[instance.site_name] = instance

    log.info(f"[플러그인] 마켓 {len(MARKET_PLUGINS)}개, 소싱 {len(SOURCING_PLUGINS)}개 등록 완료")

# 앱 시작 시 자동 실행
discover_plugins()
```

## dispatcher.py 변경 (1,600줄 → ~50줄)

```python
# 변경 후 dispatcher.py

from backend.domain.samba.plugins import MARKET_PLUGINS

SUPPORTED_MARKETS = list(MARKET_PLUGINS.keys())

def validate_transform(market_type: str, product: dict) -> list[str]:
    plugin = MARKET_PLUGINS.get(market_type)
    if not plugin:
        return [f"미지원 마켓: {market_type}"]
    missing = [f for f in plugin.required_fields if not product.get(f)]
    return missing

async def dispatch_to_market(
    session, market_type: str, product: dict,
    category_id: str = "", account=None, existing_product_no: str = "",
) -> dict:
    plugin = MARKET_PLUGINS.get(market_type)
    if not plugin:
        return {"success": False, "message": f"미지원 마켓: {market_type}"}

    missing = validate_transform(market_type, product)
    if missing:
        return {"success": False, "error_type": "schema_changed",
                "message": f"필수필드 누락: {', '.join(missing)}"}

    try:
        return await plugin.handle(session, product, category_id, account, existing_product_no)
    except Exception as e:
        return {"success": False, "message": str(e)}
```

## refresher.py 변경

```python
# 변경 후 — 소싱처별 함수 제거, 플러그인 호출로 교체

from backend.domain.samba.plugins import SOURCING_PLUGINS

async def refresh_product(product) -> RefreshResult:
    plugin = SOURCING_PLUGINS.get(product.source_site)
    if not plugin:
        return RefreshResult(product_id=product.id, error="미지원 소싱처")
    return await plugin.refresh(product)
```

## 마켓 플러그인 예시 (스마트스토어)

```python
# plugins/markets/smartstore.py

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.domain.samba.proxy.smartstore import SmartStoreClient

class SmartStorePlugin(MarketPlugin):
    market_type = "smartstore"
    policy_key = "스마트스토어"
    required_fields = ["name", "sale_price"]

    def transform(self, product, category_id, **kwargs):
        """기존 SmartStoreClient.transform_product 호출."""
        return SmartStoreClient.transform_product(product, category_id)

    async def execute(self, session, product, creds, category_id, account, existing_no):
        """기존 _handle_smartstore 본체 — 이미지 업로드 + 등록/수정."""
        client = SmartStoreClient(creds["clientId"], creds["clientSecret"])

        # 이미지 업로드 (skip_image 판단 포함)
        # 카탈로그/브랜드/속성 조회
        # transform → register/update
        # ... (기존 _handle_smartstore 로직 이동)

    async def delete(self, session, product_no, account):
        creds = await self._load_auth(session, account)
        client = SmartStoreClient(creds["clientId"], creds["clientSecret"])
        data = {"originProduct": {"statusType": "SUSPENSION"}}
        await client.update_product(product_no, data)
        return {"success": True, "message": "판매중지 완료"}
```

## 소싱처 플러그인 예시 (무신사)

```python
# plugins/sourcing/musinsa.py

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin
from backend.domain.samba.proxy.musinsa import MusinsaClient

class MusinsaPlugin(SourcingPlugin):
    site_name = "MUSINSA"
    concurrency = 1          # Rate limit 대응
    request_interval = 0.2   # 요청 간 딜레이

    async def search(self, keyword, **filters):
        """기존 collector.py 무신사 검색 로직 이동."""
        client = MusinsaClient()
        return await client.search_products(keyword, **filters)

    async def get_detail(self, site_product_id):
        """기존 collector.py 무신사 상세 조회 이동."""
        client = MusinsaClient()
        return await client.get_goods_detail(site_product_id)

    async def refresh(self, product):
        """기존 refresher._parse_musinsa 이동."""
        client = MusinsaClient()
        # ... 가격/재고/옵션 갱신 로직
```

## 전환 전략 (점진적)

기존 코드를 한 번에 교체하지 않고 점진적으로 전환:

1. **Step 1**: plugins/ 디렉토리 + base 클래스 + registry 생성
2. **Step 2**: 스마트스토어 플러그인 1개 작성 → dispatcher에서 플러그인 우선 호출, 없으면 기존 핸들러 폴백
3. **Step 3**: 동작 검증 후 나머지 마켓 순차 이동
4. **Step 4**: 무신사 소싱 플러그인 작성 → refresher에서 플러그인 우선 호출
5. **Step 5**: 기존 인라인 핸들러 제거
6. **Step 6**: Tenant 모델 + alembic 마이그레이션 (tenant_id 컬럼 추가)
7. **Step 7**: API 미들웨어 (JWT → tenant_id 자동 주입)
8. **Step 8**: 플랜 제한 체크 미들웨어

```python
# Step 2 과도기 — dispatcher.py
async def dispatch_to_market(...):
    plugin = MARKET_PLUGINS.get(market_type)
    if plugin:
        return await plugin.handle(...)
    # 폴백: 기존 핸들러
    handler = MARKET_HANDLERS.get(market_type)
    if handler:
        return await handler(...)
    return {"success": False, "message": "미지원"}
```

## 변경 영향 범위

| 파일 | 변경 내용 |
|------|----------|
| `plugins/` (신규) | 디렉토리 + base + registry + 마켓 17개 + 소싱 2개 |
| `tenant/` (신규) | Tenant 모델 + 서비스 + 리포지토리 |
| `middleware/` (신규) | tenant 미들웨어 + 플랜 제한 체크 |
| `dispatcher.py` | 1,600줄 → ~50줄 (핸들러 제거, 플러그인 호출) |
| `refresher.py` | 소싱처별 함수 제거, 플러그인 호출 |
| `service.py` | tenant_id 파라미터 추가 |
| `proxy/` | 변경 없음 (클라이언트 그대로 유지) |
| `collector.py` | 점진적 — 수집 로직을 소싱 플러그인으로 이동 + tenant_id 필터 |
| samba 전체 모델 | `tenant_id` 컬럼 + 인덱스 추가 |
| User 모델 | `tenant_id`, `role` 필드 추가 |
| alembic | 마이그레이션 파일 (tenant_id 일괄 추가) |
