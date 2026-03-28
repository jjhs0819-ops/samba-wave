# 소싱처 계정 관리 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 소싱처별 N개 로그인 계정을 관리하고, 크롬 프로필 기반 Playwright 자동화로 무신사머니 잔액을 조회한다.

**Architecture:** SambaMarketAccount와 동일한 DDD 패턴(model → repository → service → router). 크롬 프로필 목록은 `%LOCALAPPDATA%/Google/Chrome/User Data/Local State` JSON에서 파싱. 잔액 조회는 Playwright가 크롬 프로필로 브라우저를 열어 무신사 마이페이지 DOM을 읽는다.

**Tech Stack:** FastAPI, SQLModel, Alembic, Playwright (async), Next.js 15, TypeScript

**Spec:** `docs/superpowers/specs/2026-03-28-sourcing-account-design.md`

---

### Task 1: DB 모델 + 마이그레이션

**Files:**
- Create: `backend/backend/domain/samba/sourcing_account/__init__.py`
- Create: `backend/backend/domain/samba/sourcing_account/model.py`
- Create: `backend/alembic/versions/u9v0w1x2y3z4_add_samba_sourcing_account.py`

- [ ] **Step 1: 모델 파일 생성**

```python
# backend/backend/domain/samba/sourcing_account/__init__.py
# (빈 파일)
```

```python
# backend/backend/domain/samba/sourcing_account/model.py
"""소싱처 계정 모델."""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_sourcing_account_id() -> str:
    return f"sa_{ULID()}"


# 지원 소싱처 목록
SUPPORTED_SOURCING_SITES = [
    {"id": "MUSINSA", "name": "무신사", "group": "패션"},
    {"id": "KREAM", "name": "크림", "group": "리셀"},
    {"id": "Nike", "name": "나이키", "group": "스포츠"},
    {"id": "Adidas", "name": "아디다스", "group": "스포츠"},
    {"id": "ABCmart", "name": "ABC마트", "group": "신발"},
    {"id": "OliveYoung", "name": "올리브영", "group": "뷰티"},
    {"id": "FashionPlus", "name": "패션플러스", "group": "패션"},
    {"id": "GMARKET", "name": "G마켓", "group": "오픈마켓"},
    {"id": "SMARTSTORE", "name": "스마트스토어", "group": "오픈마켓"},
    {"id": "LOTTEON", "name": "롯데ON", "group": "오픈마켓"},
    {"id": "GSShop", "name": "GS샵", "group": "오픈마켓"},
    {"id": "SSG", "name": "SSG", "group": "오픈마켓"},
    {"id": "DANAWA", "name": "다나와", "group": "가격비교"},
]


class SambaSourcingAccount(SQLModel, table=True):
    """소싱처 로그인 계정 테이블."""

    __tablename__ = "samba_sourcing_account"

    id: str = Field(
        default_factory=generate_sourcing_account_id,
        primary_key=True,
        max_length=30,
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 소싱처 구분
    site_name: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )
    account_label: str = Field(sa_column=Column(Text, nullable=False))

    # 로그인 정보
    username: str = Field(sa_column=Column(Text, nullable=False))
    password: str = Field(sa_column=Column(Text, nullable=False))

    # 크롬 프로필
    chrome_profile: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 메모
    memo: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 잔액 (무신사머니 등)
    balance: Optional[float] = Field(default=None)
    balance_updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # 활성/비활성
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true", index=True)
    )

    # 확장 데이터
    additional_fields: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
```

- [ ] **Step 2: 마이그레이션 파일 생성**

```python
# backend/alembic/versions/u9v0w1x2y3z4_add_samba_sourcing_account.py
"""소싱처 계정 테이블 추가

Revision ID: u9v0w1x2y3z4
Revises: t8u9v0w1x2y3
Create Date: 2026-03-28 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'u9v0w1x2y3z4'
down_revision: Union[str, Sequence[str], None] = 't8u9v0w1x2y3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'samba_sourcing_account',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('tenant_id', sa.String(), nullable=True, index=True),
        sa.Column('site_name', sa.Text(), nullable=False, index=True),
        sa.Column('account_label', sa.Text(), nullable=False),
        sa.Column('username', sa.Text(), nullable=False),
        sa.Column('password', sa.Text(), nullable=False),
        sa.Column('chrome_profile', sa.Text(), nullable=True),
        sa.Column('memo', sa.Text(), nullable=True),
        sa.Column('balance', sa.Float(), nullable=True),
        sa.Column('balance_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', index=True),
        sa.Column('additional_fields', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('samba_sourcing_account')
```

- [ ] **Step 3: 마이그레이션 실행**

Run: `cd backend && .venv/Scripts/python.exe -m alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade t8u9v0w1x2y3 -> u9v0w1x2y3z4`

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/domain/samba/sourcing_account/ backend/alembic/versions/u9v0w1x2y3z4_add_samba_sourcing_account.py
git commit -m "소싱처 계정 모델 + 마이그레이션 추가"
```

---

### Task 2: Repository + Service

**Files:**
- Create: `backend/backend/domain/samba/sourcing_account/repository.py`
- Create: `backend/backend/domain/samba/sourcing_account/service.py`

- [ ] **Step 1: Repository 생성**

```python
# backend/backend/domain/samba/sourcing_account/repository.py
"""소싱처 계정 Repository."""

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.sourcing_account.model import SambaSourcingAccount


class SambaSourcingAccountRepository(BaseRepository[SambaSourcingAccount]):
    def __init__(self, session):
        super().__init__(session, SambaSourcingAccount)
```

- [ ] **Step 2: Service 생성**

```python
# backend/backend/domain/samba/sourcing_account/service.py
"""소싱처 계정 Service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.domain.samba.sourcing_account.model import (
    SambaSourcingAccount,
    SUPPORTED_SOURCING_SITES,
)
from backend.domain.samba.sourcing_account.repository import SambaSourcingAccountRepository
from backend.utils.logger import logger


class SambaSourcingAccountService:
    def __init__(self, repo: SambaSourcingAccountRepository):
        self.repo = repo

    async def list_accounts(
        self, site_name: Optional[str] = None, skip: int = 0, limit: int = 100,
    ) -> List[SambaSourcingAccount]:
        if site_name:
            return await self.repo.filter_by_async(
                site_name=site_name, order_by="created_at", order_by_desc=True,
            )
        return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

    async def get_account(self, account_id: str) -> Optional[SambaSourcingAccount]:
        return await self.repo.get_async(account_id)

    async def create_account(self, data: Dict[str, Any]) -> SambaSourcingAccount:
        return await self.repo.create_async(**data)

    async def update_account(
        self, account_id: str, data: Dict[str, Any],
    ) -> Optional[SambaSourcingAccount]:
        data["updated_at"] = datetime.now(timezone.utc)
        return await self.repo.update_async(account_id, **data)

    async def delete_account(self, account_id: str) -> bool:
        return await self.repo.delete_async(account_id)

    async def toggle_active(self, account_id: str) -> Optional[SambaSourcingAccount]:
        account = await self.repo.get_async(account_id)
        if not account:
            return None
        return await self.repo.update_async(account_id, is_active=not account.is_active)

    async def update_balance(
        self, account_id: str, balance: float,
    ) -> Optional[SambaSourcingAccount]:
        """잔액 업데이트."""
        return await self.repo.update_async(
            account_id,
            balance=balance,
            balance_updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def get_supported_sites() -> List[Dict[str, str]]:
        return SUPPORTED_SOURCING_SITES
```

- [ ] **Step 3: 커밋**

```bash
git add backend/backend/domain/samba/sourcing_account/repository.py backend/backend/domain/samba/sourcing_account/service.py
git commit -m "소싱처 계정 repository + service 추가"
```

---

### Task 3: DTO + API 라우터

**Files:**
- Create: `backend/backend/dtos/samba/sourcing_account.py`
- Create: `backend/backend/api/v1/routers/samba/sourcing_account.py`
- Modify: `backend/backend/main.py` (라우터 등록)

- [ ] **Step 1: DTO 생성**

```python
# backend/backend/dtos/samba/sourcing_account.py
"""소싱처 계정 DTO."""

from typing import Any, Optional

from pydantic import BaseModel


class SourcingAccountCreate(BaseModel):
    site_name: str
    account_label: str
    username: str
    password: str
    chrome_profile: Optional[str] = None
    memo: Optional[str] = None
    additional_fields: Optional[Any] = None


class SourcingAccountUpdate(BaseModel):
    account_label: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    chrome_profile: Optional[str] = None
    memo: Optional[str] = None
    is_active: Optional[bool] = None
    additional_fields: Optional[Any] = None
```

- [ ] **Step 2: 라우터 생성**

```python
# backend/backend/api/v1/routers/samba/sourcing_account.py
"""소싱처 계정 API 라우터."""

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.dtos.samba.sourcing_account import SourcingAccountCreate, SourcingAccountUpdate
from backend.utils.logger import logger

router = APIRouter(prefix="/sourcing-accounts", tags=["samba-sourcing-accounts"])


def _read_service(session: AsyncSession):
    from backend.domain.samba.sourcing_account.repository import SambaSourcingAccountRepository
    from backend.domain.samba.sourcing_account.service import SambaSourcingAccountService
    return SambaSourcingAccountService(SambaSourcingAccountRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.sourcing_account.repository import SambaSourcingAccountRepository
    from backend.domain.samba.sourcing_account.service import SambaSourcingAccountService
    return SambaSourcingAccountService(SambaSourcingAccountRepository(session))


# ── CRUD ──

@router.get("")
async def list_sourcing_accounts(
    site_name: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _read_service(session).list_accounts(site_name=site_name)


@router.get("/sites")
async def get_supported_sites():
    from backend.domain.samba.sourcing_account.service import SambaSourcingAccountService
    return SambaSourcingAccountService.get_supported_sites()


@router.get("/chrome-profiles")
async def get_chrome_profiles():
    """PC에 존재하는 크롬 프로필 목록 반환."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    local_state_path = Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Local State"
    if not local_state_path.exists():
        return []

    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        profiles_info = data.get("profile", {}).get("info_cache", {})
        results = []
        for directory, info in profiles_info.items():
            results.append({
                "directory": directory,
                "name": info.get("name", directory),
                "gaia_name": info.get("gaia_name", ""),
            })
        return sorted(results, key=lambda x: x["directory"])
    except Exception as e:
        logger.warning(f"크롬 프로필 목록 조회 실패: {e}")
        return []


@router.get("/{account_id}")
async def get_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _read_service(session)
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return account


@router.post("", status_code=201)
async def create_sourcing_account(
    body: SourcingAccountCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    return await _write_service(session).create_account(body.model_dump(exclude_unset=True))


@router.put("/{account_id}")
async def update_sourcing_account(
    account_id: str,
    body: SourcingAccountUpdate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _write_service(session)
    result = await svc.update_account(account_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return result


@router.put("/{account_id}/toggle")
async def toggle_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    result = await _write_service(session).toggle_active(account_id)
    if not result:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return result


@router.delete("/{account_id}")
async def delete_sourcing_account(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    if not await _write_service(session).delete_account(account_id):
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    return {"ok": True}


# ── 잔액 조회 ──

@router.post("/{account_id}/fetch-balance")
async def fetch_balance(
    account_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """단건 잔액 조회 — Playwright로 크롬 프로필 열어서 무신사 마이페이지 파싱."""
    svc = _write_service(session)
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(404, "소싱처 계정을 찾을 수 없습니다")
    if not account.chrome_profile:
        raise HTTPException(400, "크롬 프로필이 설정되지 않았습니다")

    try:
        balance = await _fetch_musinsa_balance(account)
        updated = await svc.update_balance(account_id, balance)
        return {"balance": balance, "account": updated}
    except Exception as e:
        logger.error(f"잔액 조회 실패 [{account.account_label}]: {e}")
        raise HTTPException(500, f"잔액 조회 실패: {str(e)}")


@router.post("/fetch-all-balances")
async def fetch_all_balances(
    site_name: str = Query("MUSINSA"),
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """특정 소싱처의 전체 활성 계정 잔액 일괄 조회."""
    svc = _write_service(session)
    accounts = await svc.list_accounts(site_name=site_name)
    active = [a for a in accounts if a.is_active and a.chrome_profile]

    results = []
    for account in active:
        try:
            balance = await _fetch_musinsa_balance(account)
            await svc.update_balance(account.id, balance)
            results.append({"id": account.id, "label": account.account_label, "balance": balance, "status": "success"})
        except Exception as e:
            logger.error(f"잔액 조회 실패 [{account.account_label}]: {e}")
            results.append({"id": account.id, "label": account.account_label, "balance": None, "status": "error", "message": str(e)})

    return {"results": results}


async def _fetch_musinsa_balance(account) -> float:
    """Playwright로 무신사 마이페이지에서 무신사머니 잔액을 파싱한다."""
    from playwright.async_api import async_playwright

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    user_data_dir = str(Path(local_app_data) / "Google" / "Chrome" / "User Data")

    async with async_playwright() as p:
        # 크롬 프로필로 브라우저 실행
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="chrome",
            headless=True,
            args=[
                f"--profile-directory={account.chrome_profile}",
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            # 무신사 마이페이지 접속
            await page.goto("https://www.musinsa.com/my-page", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)

            # 로그인 필요 여부 체크 (로그인 페이지로 리다이렉트되면)
            if "login" in page.url:
                # 저장된 계정으로 자동 로그인 시도
                await page.fill('input[name="id"], input[type="email"], #login-id', account.username)
                await page.fill('input[name="pw"], input[type="password"], #login-pw', account.password)
                await page.click('button[type="submit"], .login-btn, #btn-login')
                await page.wait_for_timeout(3000)

                if "login" in page.url:
                    raise Exception("로그인 실패 — 캡챠 또는 인증 필요")

                await page.goto("https://www.musinsa.com/my-page", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)

            # 무신사머니 잔액 파싱
            # 무신사 마이페이지에서 잔액 텍스트를 찾는다
            selectors = [
                'text=무신사머니',         # 텍스트 기반
                '.my-benefit-item',       # 혜택 항목
                '[class*="point"]',       # 포인트 관련
                '[class*="money"]',       # 머니 관련
            ]

            balance_text = ""
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        # 해당 요소 근처에서 숫자를 찾는다
                        parent = el.locator("..").first
                        text = await parent.text_content()
                        if text:
                            balance_text = text
                            break
                except Exception:
                    continue

            if not balance_text:
                # 전체 페이지에서 "무신사머니" 근처 숫자 추출
                content = await page.content()
                import re
                match = re.search(r'무신사머니[^0-9]*?([\d,]+)\s*원?', content)
                if match:
                    balance_text = match.group(1)
                else:
                    raise Exception("무신사머니 잔액을 찾을 수 없습니다")

            # 숫자 추출
            import re
            numbers = re.findall(r'[\d,]+', balance_text)
            if not numbers:
                raise Exception(f"잔액 파싱 실패: {balance_text}")

            # 가장 큰 숫자를 잔액으로 사용
            balance = max(int(n.replace(',', '')) for n in numbers)
            logger.info(f"[잔액조회] {account.account_label}: {balance:,}원")
            return float(balance)
        finally:
            await context.close()
```

- [ ] **Step 3: main.py에 라우터 등록**

`backend/backend/main.py` 수정:

import 추가 (기존 import 블록에):
```python
from backend.api.v1.routers.samba.sourcing_account import router as samba_sourcing_account_router
```

include_router 추가 (기존 include_router 블록 끝에):
```python
app.include_router(samba_sourcing_account_router, prefix="/api/v1/samba")
```

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/dtos/samba/sourcing_account.py backend/backend/api/v1/routers/samba/sourcing_account.py backend/backend/main.py
git commit -m "소싱처 계정 DTO + API 라우터 + 잔액 조회 엔드포인트"
```

---

### Task 4: 프론트엔드 API 클라이언트

**Files:**
- Modify: `frontend/src/lib/samba/api.ts`

- [ ] **Step 1: SambaSourcingAccount 인터페이스 + sourcingAccountApi 추가**

`frontend/src/lib/samba/api.ts` 파일 끝(기존 export 블록 이후)에 추가:

```typescript
// ── Sourcing Accounts ──

export interface SambaSourcingAccount {
  id: string
  site_name: string
  account_label: string
  username: string
  password: string
  chrome_profile?: string
  memo?: string
  balance?: number
  balance_updated_at?: string
  is_active: boolean
  additional_fields?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ChromeProfile {
  directory: string
  name: string
  gaia_name: string
}

export interface BalanceResult {
  id: string
  label: string
  balance: number | null
  status: string
  message?: string
}

export const sourcingAccountApi = {
  list: (siteName?: string) => {
    const p = new URLSearchParams()
    if (siteName) p.set('site_name', siteName)
    return request<SambaSourcingAccount[]>(`${SAMBA_PREFIX}/sourcing-accounts?${p}`)
  },
  getSites: () => request<{ id: string; name: string; group: string }[]>(`${SAMBA_PREFIX}/sourcing-accounts/sites`),
  getChromeProfiles: () => request<ChromeProfile[]>(`${SAMBA_PREFIX}/sourcing-accounts/chrome-profiles`),
  get: (id: string) => request<SambaSourcingAccount>(`${SAMBA_PREFIX}/sourcing-accounts/${id}`),
  create: (data: Partial<SambaSourcingAccount>) =>
    request<SambaSourcingAccount>(`${SAMBA_PREFIX}/sourcing-accounts`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<SambaSourcingAccount>) =>
    request<SambaSourcingAccount>(`${SAMBA_PREFIX}/sourcing-accounts/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  toggle: (id: string) =>
    request<SambaSourcingAccount>(`${SAMBA_PREFIX}/sourcing-accounts/${id}/toggle`, { method: 'PUT' }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/sourcing-accounts/${id}`, { method: 'DELETE' }),
  fetchBalance: (id: string) =>
    request<{ balance: number; account: SambaSourcingAccount }>(`${SAMBA_PREFIX}/sourcing-accounts/${id}/fetch-balance`, { method: 'POST' }),
  fetchAllBalances: (siteName = 'MUSINSA') =>
    request<{ results: BalanceResult[] }>(`${SAMBA_PREFIX}/sourcing-accounts/fetch-all-balances?site_name=${siteName}`, { method: 'POST' }),
}
```

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/lib/samba/api.ts
git commit -m "소싱처 계정 프론트엔드 API 클라이언트 추가"
```

---

### Task 5: 설정 페이지 UI — 소싱처 계정 섹션

**Files:**
- Modify: `frontend/src/app/samba/settings/page.tsx`

- [ ] **Step 1: import에 sourcingAccountApi 추가**

기존 import 문에 추가:
```typescript
import { ..., sourcingAccountApi, type SambaSourcingAccount, type ChromeProfile } from '@/lib/samba/api'
```

- [ ] **Step 2: 상태 변수 추가**

설정 페이지 컴포넌트 내부, 기존 state 선언부에 추가:

```typescript
// 소싱처 계정 상태
const [sourcingAccounts, setSourcingAccounts] = useState<SambaSourcingAccount[]>([])
const [sourcingSites, setSourcingSites] = useState<{ id: string; name: string; group: string }[]>([])
const [chromeProfiles, setChromeProfiles] = useState<ChromeProfile[]>([])
const [sourcingTab, setSourcingTab] = useState('MUSINSA')
const [sourcingFormOpen, setSourcingFormOpen] = useState(false)
const [sourcingEditId, setSourcingEditId] = useState<string | null>(null)
const [sourcingForm, setSourcingForm] = useState({ site_name: 'MUSINSA', account_label: '', username: '', password: '', chrome_profile: '', memo: '' })
const [balanceLoading, setBalanceLoading] = useState<Record<string, boolean>>({})
```

- [ ] **Step 3: 데이터 로드 함수 추가**

```typescript
const loadSourcingAccounts = useCallback(async () => {
  try {
    const [accounts, sites, profiles] = await Promise.all([
      sourcingAccountApi.list(),
      sourcingAccountApi.getSites(),
      sourcingAccountApi.getChromeProfiles(),
    ])
    setSourcingAccounts(accounts)
    setSourcingSites(sites)
    setChromeProfiles(profiles)
  } catch { /* ignore */ }
}, [])
```

기존 `useEffect`에 `loadSourcingAccounts()` 호출 추가.

- [ ] **Step 4: 핸들러 함수 추가**

```typescript
const handleSourcingSave = async () => {
  if (!sourcingForm.account_label || !sourcingForm.username || !sourcingForm.password) {
    showAlert('별칭, 아이디, 비밀번호는 필수입니다', 'error')
    return
  }
  try {
    if (sourcingEditId) {
      await sourcingAccountApi.update(sourcingEditId, sourcingForm)
    } else {
      await sourcingAccountApi.create({ ...sourcingForm, site_name: sourcingTab })
    }
    setSourcingFormOpen(false)
    setSourcingEditId(null)
    setSourcingForm({ site_name: 'MUSINSA', account_label: '', username: '', password: '', chrome_profile: '', memo: '' })
    loadSourcingAccounts()
  } catch (err) { showAlert(err instanceof Error ? err.message : '저장 실패', 'error') }
}

const handleSourcingDelete = async (id: string) => {
  if (!await showConfirm('삭제하시겠습니까?')) return
  await sourcingAccountApi.delete(id)
  loadSourcingAccounts()
}

const handleSourcingEdit = (a: SambaSourcingAccount) => {
  setSourcingEditId(a.id)
  setSourcingForm({
    site_name: a.site_name,
    account_label: a.account_label,
    username: a.username,
    password: a.password,
    chrome_profile: a.chrome_profile || '',
    memo: a.memo || '',
  })
  setSourcingFormOpen(true)
}

const handleFetchBalance = async (id: string) => {
  setBalanceLoading(prev => ({ ...prev, [id]: true }))
  try {
    const res = await sourcingAccountApi.fetchBalance(id)
    showAlert(`잔액: ${res.balance.toLocaleString()}원`, 'success')
    loadSourcingAccounts()
  } catch (err) { showAlert(err instanceof Error ? err.message : '잔액 조회 실패', 'error') }
  setBalanceLoading(prev => ({ ...prev, [id]: false }))
}

const handleFetchAllBalances = async () => {
  setBalanceLoading(prev => {
    const next = { ...prev }
    sourcingAccounts.filter(a => a.site_name === sourcingTab && a.is_active).forEach(a => { next[a.id] = true })
    return next
  })
  try {
    const res = await sourcingAccountApi.fetchAllBalances(sourcingTab)
    const failed = res.results.filter(r => r.status === 'error')
    if (failed.length) showAlert(`${failed.length}건 조회 실패`, 'error')
    else showAlert('전체 잔액 조회 완료', 'success')
    loadSourcingAccounts()
  } catch (err) { showAlert(err instanceof Error ? err.message : '전체 잔액 조회 실패', 'error') }
  setBalanceLoading({})
}
```

- [ ] **Step 5: UI 렌더링 — "소싱처 계정" 섹션**

기존 스토어 연결 섹션 아래에 추가:

```tsx
{/* ═══════ 소싱처 계정 관리 ═══════ */}
<div style={{ ...card, padding: '1.5rem' }}>
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
    <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>소싱처 계정</h3>
    <div style={{ display: 'flex', gap: '0.5rem' }}>
      <button
        onClick={handleFetchAllBalances}
        style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem', background: 'rgba(76,154,255,0.15)', border: '1px solid rgba(76,154,255,0.3)', color: '#4C9AFF', borderRadius: '6px', cursor: 'pointer' }}
      >전체 잔액 조회</button>
      <button
        onClick={() => { setSourcingEditId(null); setSourcingForm({ site_name: sourcingTab, account_label: '', username: '', password: '', chrome_profile: '', memo: '' }); setSourcingFormOpen(true) }}
        style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem', background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', border: 'none', color: '#fff', borderRadius: '6px', cursor: 'pointer' }}
      >계정 추가</button>
    </div>
  </div>

  {/* 소싱처 탭 */}
  <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
    {sourcingSites.map(site => {
      const count = sourcingAccounts.filter(a => a.site_name === site.id).length
      const active = sourcingTab === site.id
      return (
        <button
          key={site.id}
          onClick={() => setSourcingTab(site.id)}
          style={{
            padding: '0.3rem 0.625rem', fontSize: '0.72rem', borderRadius: '6px', cursor: 'pointer',
            background: active ? 'rgba(255,140,0,0.15)' : 'rgba(40,40,40,0.8)',
            color: active ? '#FF8C00' : '#888',
            border: active ? '1px solid #FF8C00' : '1px solid #2D2D2D',
          }}
        >{site.name}{count > 0 && ` (${count})`}</button>
      )
    })}
  </div>

  {/* 계정 리스트 */}
  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
    {sourcingAccounts.filter(a => a.site_name === sourcingTab).length === 0 ? (
      <div style={{ fontSize: '0.8rem', color: '#555', padding: '1rem 0', textAlign: 'center' }}>등록된 계정이 없습니다</div>
    ) : sourcingAccounts.filter(a => a.site_name === sourcingTab).map(a => (
      <div key={a.id} style={{
        display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.625rem 0.75rem',
        background: a.is_active ? 'rgba(255,255,255,0.02)' : 'rgba(100,100,100,0.1)',
        borderRadius: '8px', border: '1px solid #2D2D2D',
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#E5E5E5' }}>{a.account_label}</span>
            <span style={{ fontSize: '0.7rem', color: '#888', fontFamily: 'monospace' }}>{a.username}</span>
            {a.chrome_profile && <span style={{ fontSize: '0.65rem', color: '#666', background: '#1A1A1A', padding: '0.1rem 0.375rem', borderRadius: '4px' }}>{chromeProfiles.find(p => p.directory === a.chrome_profile)?.name || a.chrome_profile}</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', fontSize: '0.72rem' }}>
            {a.balance != null && (
              <span style={{ color: '#51CF66', fontWeight: 600 }}>{a.balance.toLocaleString()}원</span>
            )}
            {a.balance_updated_at && (
              <span style={{ color: '#666' }}>{new Date(a.balance_updated_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
            )}
            {a.memo && <span style={{ color: '#888' }}>{a.memo}</span>}
          </div>
        </div>
        <button
          onClick={() => handleFetchBalance(a.id)}
          disabled={balanceLoading[a.id]}
          style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', background: 'rgba(81,207,102,0.1)', border: '1px solid rgba(81,207,102,0.3)', color: '#51CF66', borderRadius: '4px', cursor: 'pointer', opacity: balanceLoading[a.id] ? 0.5 : 1 }}
        >{balanceLoading[a.id] ? '조회중' : '잔액'}</button>
        <button
          onClick={() => sourcingAccountApi.toggle(a.id).then(() => loadSourcingAccounts())}
          style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', background: a.is_active ? 'rgba(76,154,255,0.1)' : 'rgba(100,100,100,0.2)', border: `1px solid ${a.is_active ? 'rgba(76,154,255,0.3)' : '#555'}`, color: a.is_active ? '#4C9AFF' : '#888', borderRadius: '4px', cursor: 'pointer' }}
        >{a.is_active ? 'ON' : 'OFF'}</button>
        <button onClick={() => handleSourcingEdit(a)} style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', background: 'rgba(60,60,60,0.8)', color: '#C5C5C5', border: '1px solid #3D3D3D', borderRadius: '4px', cursor: 'pointer' }}>수정</button>
        <button onClick={() => handleSourcingDelete(a.id)} style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', background: 'rgba(255,80,80,0.15)', color: '#FF6B6B', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '4px', cursor: 'pointer' }}>삭제</button>
      </div>
    ))}
  </div>
</div>

{/* 소싱처 계정 추가/수정 모달 */}
{sourcingFormOpen && (
  <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
    <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '1.5rem', width: '400px', maxWidth: '90%' }}>
      <h4 style={{ fontSize: '0.95rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '1rem' }}>
        {sourcingEditId ? '소싱처 계정 수정' : '소싱처 계정 추가'}
      </h4>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
        {!sourcingEditId && (
          <select
            value={sourcingForm.site_name}
            onChange={e => setSourcingForm(prev => ({ ...prev, site_name: e.target.value }))}
            style={{ ...inputStyle, fontSize: '0.8rem' }}
          >
            {sourcingSites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
        <input style={{ ...inputStyle, fontSize: '0.8rem' }} placeholder="별칭 (예: 무신사-기현)" value={sourcingForm.account_label} onChange={e => setSourcingForm(prev => ({ ...prev, account_label: e.target.value }))} />
        <input style={{ ...inputStyle, fontSize: '0.8rem' }} placeholder="아이디" value={sourcingForm.username} onChange={e => setSourcingForm(prev => ({ ...prev, username: e.target.value }))} />
        <input style={{ ...inputStyle, fontSize: '0.8rem' }} type="password" placeholder="비밀번호" value={sourcingForm.password} onChange={e => setSourcingForm(prev => ({ ...prev, password: e.target.value }))} />
        <select
          value={sourcingForm.chrome_profile}
          onChange={e => setSourcingForm(prev => ({ ...prev, chrome_profile: e.target.value }))}
          style={{ ...inputStyle, fontSize: '0.8rem' }}
        >
          <option value="">크롬 프로필 선택</option>
          {chromeProfiles.map(p => <option key={p.directory} value={p.directory}>{p.name} ({p.directory})</option>)}
        </select>
        <textarea style={{ ...inputStyle, fontSize: '0.8rem', resize: 'none', height: '3rem' }} placeholder="메모 (쿠폰, 용도 등)" value={sourcingForm.memo} onChange={e => setSourcingForm(prev => ({ ...prev, memo: e.target.value }))} />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem', justifyContent: 'flex-end' }}>
        <button onClick={() => { setSourcingFormOpen(false); setSourcingEditId(null) }} style={{ padding: '0.4rem 1rem', fontSize: '0.8rem', background: '#333', color: '#ccc', border: '1px solid #555', borderRadius: '6px', cursor: 'pointer' }}>취소</button>
        <button onClick={handleSourcingSave} style={{ padding: '0.4rem 1rem', fontSize: '0.8rem', background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer' }}>
          {sourcingEditId ? '수정' : '추가'}
        </button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/app/samba/settings/page.tsx
git commit -m "설정 페이지에 소싱처 계정 관리 UI 추가"
```

---

### Task 6: Playwright 의존성 설치

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: playwright 패키지 추가**

`backend/pyproject.toml`의 dependencies에 `playwright` 추가:

```toml
"playwright>=1.40.0",
```

- [ ] **Step 2: 설치**

Run: `cd backend && uv pip install playwright && playwright install chromium`

- [ ] **Step 3: 커밋**

```bash
git add backend/pyproject.toml
git commit -m "playwright 의존성 추가 (소싱처 자동화)"
```

---

### Task 7: 통합 테스트

- [ ] **Step 1: 백엔드 서버 재시작**

Run: `cd backend && .venv/Scripts/python.exe run.py`

- [ ] **Step 2: API 테스트 — 크롬 프로필 목록**

Run: `curl http://localhost:28080/api/v1/samba/sourcing-accounts/chrome-profiles`
Expected: 크롬 프로필 JSON 배열 반환

- [ ] **Step 3: API 테스트 — 계정 CRUD**

```bash
# 생성
curl -X POST http://localhost:28080/api/v1/samba/sourcing-accounts \
  -H "Content-Type: application/json" \
  -d '{"site_name":"MUSINSA","account_label":"테스트","username":"test","password":"test123"}'

# 목록
curl http://localhost:28080/api/v1/samba/sourcing-accounts?site_name=MUSINSA

# 삭제 (id를 생성 응답에서 가져옴)
curl -X DELETE http://localhost:28080/api/v1/samba/sourcing-accounts/{id}
```

- [ ] **Step 4: 프론트 확인**

프론트 서버 재시작 후 설정 페이지에서:
- 소싱처 계정 섹션 표시 확인
- 소싱처 탭 전환
- 계정 추가 모달 동작
- 크롬 프로필 드롭다운 로드

- [ ] **Step 5: 커밋 (테스트 데이터 정리 후)**

```bash
git add -A
git commit -m "소싱처 계정 관리 기능 완성 — 모델/API/UI/잔액조회"
```
