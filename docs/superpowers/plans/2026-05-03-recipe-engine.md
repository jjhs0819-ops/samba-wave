# 서버 주도 수집 레시피 엔진 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 소싱처 수집 로직을 서버 DB에 저장된 JSON 레시피로 대체해, 소싱처 DOM 변경 시 확장앱 리로드 없이 서버 수정만으로 대응 가능하게 한다.

**Architecture:** 서버가 `sourcing_recipes` 테이블에 소싱처별 수집 스텝(goto/wait/extract/click/scroll/loop/evaluate)을 JSON으로 저장하고 API로 제공한다. 확장앱은 5분마다 버전을 비교해 변경된 레시피만 다운로드하며, `recipe-executor.js`가 스텝을 순서대로 실행한다. KREAM은 CDP 클릭이 필요하므로 기존 코드 유지.

**Tech Stack:** FastAPI, SQLModel, PostgreSQL (JSONB), Chrome Extension MV3 (importScripts, chrome.storage.local, chrome.alarms, chrome.scripting)

---

## 파일 맵

| 동작 | 경로 |
|------|------|
| 생성 | `backend/backend/domain/samba/sourcing_recipe/model.py` |
| 생성 | `backend/backend/domain/samba/sourcing_recipe/repository.py` |
| 생성 | `backend/backend/api/v1/routers/samba/sourcing_recipe.py` |
| 생성 | `backend/alembic/versions/<hash>_add_sourcing_recipes.py` |
| 수정 | `backend/backend/app_factory.py` |
| 생성 | `extension/recipe-cache.js` |
| 생성 | `extension/recipe-executor.js` |
| 수정 | `extension/background.js` |
| 수정 | `extension/background-bootstrap.js` |
| 수정 | `extension/manifest.json` |

---

## Task 1: DB 모델 생성

**Files:**
- Create: `backend/backend/domain/samba/sourcing_recipe/model.py`
- Create: `backend/backend/domain/samba/sourcing_recipe/__init__.py`

- [ ] **Step 1: `__init__.py` 생성 (빈 파일)**

```python
# backend/backend/domain/samba/sourcing_recipe/__init__.py
```

- [ ] **Step 2: `model.py` 작성**

```python
# backend/backend/domain/samba/sourcing_recipe/model.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Column, Field, SQLModel
from sqlalchemy import DateTime, JSON


class SourcingRecipe(SQLModel, table=True):
    __tablename__ = "sourcing_recipes"

    id: int | None = Field(default=None, primary_key=True)
    site_name: str = Field(max_length=50, unique=True, index=True)
    version: str = Field(max_length=20)
    steps: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(default=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
```

- [ ] **Step 3: 마이그레이션 생성**

```bash
cd backend
python scripts/check_migrations.py
```

출력에서 `sourcing_recipes` 테이블 누락 확인 후:

```bash
cd backend
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add_sourcing_recipes"
```

- [ ] **Step 4: 마이그레이션 파일 육안 검토**

생성된 `backend/alembic/versions/*_add_sourcing_recipes.py` 열어서:
- `op.create_table('sourcing_recipes', ...)` 있는지 확인
- `op.drop_table` / `op.drop_index` 없는지 확인
- upgrade 함수를 IF NOT EXISTS raw SQL로 교체 (idempotent 보장):

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sourcing_recipes (
            id SERIAL PRIMARY KEY,
            site_name VARCHAR(50) NOT NULL UNIQUE,
            version VARCHAR(20) NOT NULL,
            steps JSON NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sourcing_recipes_site_name
        ON sourcing_recipes (site_name)
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sourcing_recipes")
```

- [ ] **Step 5: 로컬 마이그레이션 적용**

```bash
cd backend
.venv/Scripts/python.exe -m alembic upgrade head
```

예상 출력: `Running upgrade ... -> <hash>, add_sourcing_recipes`

- [ ] **Step 6: 커밋**

```bash
git add backend/backend/domain/samba/sourcing_recipe/ backend/alembic/versions/
git commit -m "feat(recipe): sourcing_recipes DB 모델 + 마이그레이션 추가"
```

---

## Task 2: Repository 생성

**Files:**
- Create: `backend/backend/domain/samba/sourcing_recipe/repository.py`

- [ ] **Step 1: `repository.py` 작성**

```python
# backend/backend/domain/samba/sourcing_recipe/repository.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .model import SourcingRecipe


class SourcingRecipeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all_versions(self) -> list[dict[str, str]]:
        """활성 레시피 버전 목록만 반환 (site_name, version)."""
        result = await self.session.exec(
            select(SourcingRecipe.site_name, SourcingRecipe.version)
            .where(SourcingRecipe.is_active == True)
        )
        return [{"site": row[0], "version": row[1]} for row in result.all()]

    async def get_by_site(self, site_name: str) -> SourcingRecipe | None:
        result = await self.session.exec(
            select(SourcingRecipe).where(
                SourcingRecipe.site_name == site_name,
                SourcingRecipe.is_active == True,
            )
        )
        return result.first()

    async def upsert(
        self, site_name: str, version: str, steps: list[dict[str, Any]]
    ) -> SourcingRecipe:
        existing = await self.session.exec(
            select(SourcingRecipe).where(SourcingRecipe.site_name == site_name)
        )
        recipe = existing.first()
        if recipe:
            recipe.version = version
            recipe.steps = steps
            recipe.updated_at = datetime.now(timezone.utc)
        else:
            recipe = SourcingRecipe(site_name=site_name, version=version, steps=steps)
        self.session.add(recipe)
        await self.session.commit()
        await self.session.refresh(recipe)
        return recipe
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/sourcing_recipe/repository.py
git commit -m "feat(recipe): SourcingRecipeRepository 추가"
```

---

## Task 3: API 라우터 + app_factory 등록

**Files:**
- Create: `backend/backend/api/v1/routers/samba/sourcing_recipe.py`
- Modify: `backend/backend/app_factory.py`

- [ ] **Step 1: 라우터 작성**

```python
# backend/backend/api/v1/routers/samba/sourcing_recipe.py
"""소싱처 수집 레시피 API — GET은 확장앱(X-Api-Key), PUT은 관리자(JWT)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.sourcing_recipe.repository import SourcingRecipeRepository

# JWT 면제 라우터 (확장앱 X-Api-Key만으로 호출)
extension_router = APIRouter(prefix="/sourcing-recipes", tags=["sourcing-recipe"])
# JWT 필요 라우터 (관리자 수정용, app_factory에서 samba_auth 주입)
router = APIRouter(prefix="/sourcing-recipes", tags=["sourcing-recipe"])


class RecipeUpsertRequest(BaseModel):
    version: str
    steps: list[dict[str, Any]]


@extension_router.get("")
async def list_recipe_versions(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """활성 레시피 버전 목록 반환 (확장앱 캐시 비교용)."""
    repo = SourcingRecipeRepository(session)
    recipes = await repo.get_all_versions()
    return {"recipes": recipes}


@extension_router.get("/{site}")
async def get_recipe(
    site: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """특정 소싱처 레시피 풀 내용 반환."""
    repo = SourcingRecipeRepository(session)
    recipe = await repo.get_by_site(site)
    if not recipe:
        raise HTTPException(status_code=404, detail=f"레시피 없음: {site}")
    return {"site": recipe.site_name, "version": recipe.version, "steps": recipe.steps}


@router.put("/{site}")
async def upsert_recipe(
    site: str,
    body: RecipeUpsertRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """레시피 추가/수정 (관리자 전용)."""
    repo = SourcingRecipeRepository(session)
    recipe = await repo.upsert(site, body.version, body.steps)
    return {"site": recipe.site_name, "version": recipe.version}
```

- [ ] **Step 2: app_factory.py에 import 추가**

`backend/backend/app_factory.py` 상단 import 블록에 추가:

```python
from backend.api.v1.routers.samba.sourcing_recipe import (
    extension_router as samba_sourcing_recipe_extension_router,
    router as samba_sourcing_recipe_router,
)
```

- [ ] **Step 3: app_factory.py에 라우터 등록**

`app_factory.py`의 `app.include_router(samba_sourcing_account_extension_router, ...)` 줄 근처(JWT 면제 라우터 모음 아래)에 추가:

```python
# JWT 면제 — 확장앱 X-Api-Key 전용
app.include_router(samba_sourcing_recipe_extension_router, prefix="/api/v1/samba")
# JWT 필요 — 관리자 수정 전용
app.include_router(
    samba_sourcing_recipe_router, prefix="/api/v1/samba", dependencies=samba_auth
)
```

- [ ] **Step 4: 서버 재시작 후 엔드포인트 동작 확인**

```bash
cd backend && .venv/Scripts/python.exe run.py
```

브라우저에서 `http://localhost:28080/docs` 열어 `/api/v1/samba/sourcing-recipes` GET/PUT 노출 확인.

- [ ] **Step 5: ruff 포맷 + 커밋**

```bash
cd backend
.venv/Scripts/python.exe -m ruff format .
.venv/Scripts/python.exe -m ruff check --fix .
git add backend/backend/api/v1/routers/samba/sourcing_recipe.py backend/backend/app_factory.py
git commit -m "feat(recipe): 레시피 API 라우터 + app_factory 등록"
```

---

## Task 4: 무신사 초기 레시피 DB 삽입

**Files:**
- Create: `backend/scripts/seed_recipes.py`

- [ ] **Step 1: `background-sourcing.js` 무신사 수집 흐름 파악**

`extension/background-sourcing.js`에서 무신사 관련 수집 로직을 읽고, 어떤 URL로 이동하는지, 어떤 셀렉터에서 데이터를 추출하는지 확인한다.

- [ ] **Step 2: seed 스크립트 작성**

아래는 뼈대다. **Step 1에서 파악한 실제 셀렉터**로 채운다.

```python
# backend/scripts/seed_recipes.py
"""로컬 DB에 무신사 초기 레시피를 삽입한다."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.config import settings
from backend.db.orm import get_write_session
from backend.domain.samba.sourcing_recipe.repository import SourcingRecipeRepository

MUSINSA_RECIPE = {
    "version": "1.0.0",
    "steps": [
        {"type": "goto", "url": "{{productUrl}}"},
        {"type": "wait", "selector": "STEP1에서_확인한_셀렉터", "timeout": 5000},
        {
            "type": "extract",
            "fields": {
                "name":   {"selector": "STEP1에서_확인한_셀렉터", "attr": "text"},
                "price":  {"selector": "STEP1에서_확인한_셀렉터", "attr": "text", "transform": "removeComma"},
                "images": {"selector": "STEP1에서_확인한_셀렉터", "attr": "src", "multiple": True},
            },
        },
        # 옵션 클릭 → 옵션 추출 스텝
    ],
}


async def main():
    async with get_write_session() as session:
        repo = SourcingRecipeRepository(session)
        recipe = await repo.upsert("musinsa", MUSINSA_RECIPE["version"], MUSINSA_RECIPE["steps"])
        print(f"삽입 완료: {recipe.site_name} v{recipe.version}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: seed 실행**

```bash
cd backend
.venv/Scripts/python.exe scripts/seed_recipes.py
```

예상 출력: `삽입 완료: musinsa v1.0.0`

- [ ] **Step 4: GET API로 확인**

```bash
curl http://localhost:28080/api/v1/samba/sourcing-recipes
# {"recipes":[{"site":"musinsa","version":"1.0.0"}]}

curl http://localhost:28080/api/v1/samba/sourcing-recipes/musinsa
# {"site":"musinsa","version":"1.0.0","steps":[...]}
```

- [ ] **Step 5: 커밋**

```bash
git add backend/scripts/seed_recipes.py
git commit -m "feat(recipe): 무신사 초기 레시피 seed 스크립트 추가"
```

---

## Task 5: 확장앱 `recipe-cache.js` 구현

**Files:**
- Create: `extension/recipe-cache.js`

- [ ] **Step 1: `recipe-cache.js` 작성**

```js
// extension/recipe-cache.js
// 서버 레시피 버전 체크 및 chrome.storage 캐시 관리

;(function () {
  const { apiFetch } = globalThis.SambaBackgroundCore

  const CACHE_KEY = 'recipeCache'  // chrome.storage.local 키

  // 버전 비교 후 변경된 사이트만 풀 다운로드
  async function syncRecipes(proxyUrl) {
    try {
      const res = await apiFetch(`${proxyUrl}/api/v1/samba/sourcing-recipes`)
      if (!res.ok) return
      const { recipes } = await res.json()  // [{site, version}, ...]

      const stored = await chrome.storage.local.get(CACHE_KEY)
      const cache = stored[CACHE_KEY] || {}

      for (const { site, version } of recipes) {
        if (cache[site]?.version === version) continue  // 변경 없음

        try {
          const detail = await apiFetch(`${proxyUrl}/api/v1/samba/sourcing-recipes/${site}`)
          if (!detail.ok) continue
          const recipe = await detail.json()
          cache[site] = recipe
          console.log(`[레시피] ${site} v${version} 캐시 갱신`)
        } catch (e) {
          console.warn(`[레시피] ${site} 다운로드 실패:`, e.message)
        }
      }

      await chrome.storage.local.set({ [CACHE_KEY]: cache })
    } catch (e) {
      console.warn('[레시피] 버전 체크 실패:', e.message)
    }
  }

  // 캐시에서 특정 사이트 레시피 반환
  async function getRecipe(site) {
    const stored = await chrome.storage.local.get(CACHE_KEY)
    return stored[CACHE_KEY]?.[site] || null
  }

  globalThis.SambaRecipeCache = { syncRecipes, getRecipe }
})()
```

- [ ] **Step 2: 커밋**

```bash
git add extension/recipe-cache.js
git commit -m "feat(recipe): recipe-cache.js — 서버 버전 체크 + 로컬 캐시 관리"
```

---

## Task 6: 확장앱 `recipe-executor.js` 구현

**Files:**
- Create: `extension/recipe-executor.js`

- [ ] **Step 1: `recipe-executor.js` 작성**

```js
// extension/recipe-executor.js
// 레시피 스텝을 순서대로 실행하는 엔진

;(function () {

  // 변수 치환: "{{productUrl}}" → 실제 값
  function interpolate(str, vars) {
    return str.replace(/\{\{(\w+)\}\}/g, (_, k) => vars[k] ?? '')
  }

  // 페이지에서 executeScript로 DOM 조작
  function inPage(tabId, func, args = []) {
    return chrome.scripting.executeScript({
      target: { tabId },
      func,
      args,
    }).then(r => r?.[0]?.result)
  }

  // transform 적용
  function applyTransform(value, transform) {
    if (!transform || !value) return value
    if (transform === 'parseInt') return parseInt(value.replace(/[^0-9]/g, ''), 10) || 0
    if (transform === 'parseFloat') return parseFloat(value.replace(/[^0-9.]/g, '')) || 0
    if (transform === 'trim') return value.trim()
    if (transform === 'removeComma') return parseInt(value.replace(/,/g, ''), 10) || 0
    return value
  }

  // --- 스텝 핸들러 ---

  async function stepGoto(step, ctx) {
    const url = interpolate(step.url, ctx.vars)
    await chrome.tabs.update(ctx.tabId, { url })
    // 페이지 로드 완료 대기
    await new Promise((resolve) => {
      function listener(tabId, info) {
        if (tabId === ctx.tabId && info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener)
          resolve()
        }
      }
      chrome.tabs.onUpdated.addListener(listener)
      setTimeout(resolve, 15000)  // 15초 타임아웃
    })
  }

  async function stepWait(step, ctx) {
    const timeout = step.timeout ?? 5000
    const start = Date.now()
    while (Date.now() - start < timeout) {
      const found = await inPage(ctx.tabId, (sel) => !!document.querySelector(sel), [step.selector])
      if (found) return
      await new Promise(r => setTimeout(r, 300))
    }
    console.warn(`[레시피] wait 타임아웃: ${step.selector}`)
  }

  async function stepExtract(step, ctx) {
    const fields = step.fields
    const result = await inPage(ctx.tabId, (fields) => {
      const out = {}
      for (const [key, cfg] of Object.entries(fields)) {
        const els = cfg.multiple
          ? Array.from(document.querySelectorAll(cfg.selector))
          : [document.querySelector(cfg.selector)]
        const values = els
          .filter(Boolean)
          .map(el => cfg.attr === 'text' ? el.textContent?.trim() : el.getAttribute(cfg.attr))
          .filter(Boolean)
        out[key] = cfg.multiple ? values : values[0] ?? null
      }
      return out
    }, [fields])

    // transform 적용
    if (result) {
      for (const [key, cfg] of Object.entries(fields)) {
        if (cfg.transform && result[key] !== undefined) {
          if (Array.isArray(result[key])) {
            result[key] = result[key].map(v => applyTransform(v, cfg.transform))
          } else {
            result[key] = applyTransform(result[key], cfg.transform)
          }
        }
      }
      Object.assign(ctx.result, result)
    }
  }

  async function stepClick(step, ctx) {
    await inPage(ctx.tabId, (sel) => document.querySelector(sel)?.click(), [step.selector])
    await new Promise(r => setTimeout(r, 500))
  }

  async function stepScroll(step, ctx) {
    if (step.target === 'bottom') {
      await inPage(ctx.tabId, () => window.scrollTo(0, document.body.scrollHeight))
    } else {
      await inPage(ctx.tabId, (sel) => document.querySelector(sel)?.scrollIntoView(), [step.target])
    }
    await new Promise(r => setTimeout(r, 500))
  }

  async function stepEvaluate(step, ctx) {
    const result = await inPage(ctx.tabId, (expr) => {
      try { return eval(expr) } catch { return null }
    }, [step.expression])
    if (step.resultKey && result !== null) {
      ctx.result[step.resultKey] = result
    }
  }

  async function stepLoop(step, ctx) {
    const count = await inPage(ctx.tabId, (sel) => document.querySelectorAll(sel).length, [step.selector])
    const items = []
    for (let i = 0; i < (count || 0); i++) {
      const itemCtx = { ...ctx, result: {}, loopIndex: i }
      for (const subStep of step.steps) {
        await executeStep(subStep, itemCtx)
      }
      items.push(itemCtx.result)
    }
    if (step.resultKey) ctx.result[step.resultKey] = items
  }

  async function executeStep(step, ctx) {
    switch (step.type) {
      case 'goto':     return stepGoto(step, ctx)
      case 'wait':     return stepWait(step, ctx)
      case 'extract':  return stepExtract(step, ctx)
      case 'click':    return stepClick(step, ctx)
      case 'scroll':   return stepScroll(step, ctx)
      case 'evaluate': return stepEvaluate(step, ctx)
      case 'loop':     return stepLoop(step, ctx)
      default: console.warn(`[레시피] 알 수 없는 스텝: ${step.type}`)
    }
  }

  // 레시피 전체 실행 진입점
  // vars: { productUrl, ... } 등 치환 변수
  // tabId: 기존 탭 재사용 가능. null이면 새 탭 열고 수집 후 닫음
  async function executeRecipe(recipe, vars, tabId = null) {
    const ownTab = tabId === null
    if (ownTab) {
      const tab = await chrome.tabs.create({ url: 'about:blank', active: false })
      tabId = tab.id
    }
    const ctx = { tabId, vars, result: {} }
    try {
      for (const step of recipe.steps) {
        await executeStep(step, ctx)
      }
      return ctx.result
    } finally {
      if (ownTab) {
        try { await chrome.tabs.remove(tabId) } catch {}
      }
    }
  }

  globalThis.SambaRecipeExecutor = { executeRecipe }
})()
```

- [ ] **Step 2: 커밋**

```bash
git add extension/recipe-executor.js
git commit -m "feat(recipe): recipe-executor.js — 스텝 실행 엔진 구현"
```

---

## Task 7: 확장앱 연결 (background.js + background-bootstrap.js + manifest.json)

**Files:**
- Modify: `extension/background.js`
- Modify: `extension/background-bootstrap.js`
- Modify: `extension/manifest.json`

- [ ] **Step 1: `background.js`에 import 추가**

`extension/background.js` 상단 importScripts 블록 끝(`importScripts('background-messages.js')` 직전)에 추가:

```js
importScripts('recipe-cache.js')
importScripts('recipe-executor.js')
```

전체 import 순서 (background.js 맨 위):
```js
importScripts('config.js')
importScripts('background-core.js')
// ... 기존 코드 ...
importScripts('background-kream.js')
importScripts('background-autologin.js')
importScripts('recipe-cache.js')       // ← 추가
importScripts('recipe-executor.js')    // ← 추가
importScripts('background-sourcing.js')
importScripts('background-bootstrap.js')
importScripts('background-messages.js')
```

- [ ] **Step 2: `background-bootstrap.js`에 recipeSync 알람 추가**

`background-bootstrap.js`의 `setupCookieSyncAlarm` 함수 바로 아래에 추가:

```js
function setupRecipeSyncAlarm() {
  chrome.alarms.get('recipeSync', (alarm) => {
    if (!alarm) {
      chrome.alarms.create('recipeSync', { periodInMinutes: 5 })
      console.log('[레시피] chrome.alarms 설정: 5분 주기 동기화')
    }
  })
}
```

`chrome.alarms.onAlarm.addListener` 핸들러 내부에 추가:

```js
if (alarm.name === 'recipeSync') {
  const data = await chrome.storage.local.get('proxyUrl')
  const proxyUrl = data.proxyUrl || DEFAULT_PROXY_URL
  globalThis.SambaRecipeCache.syncRecipes(proxyUrl).catch(() => {})
}
```

그리고 서비스 워커 초기화 위치(기존 `setupCookieSyncAlarm()` 호출 옆)에 추가:

```js
setupRecipeSyncAlarm()
// 즉시 1회 동기화
chrome.storage.local.get('proxyUrl').then(data => {
  const proxyUrl = data.proxyUrl || DEFAULT_PROXY_URL
  globalThis.SambaRecipeCache.syncRecipes(proxyUrl).catch(() => {})
})
```

- [ ] **Step 3: `manifest.json` 버전 bump**

`extension/manifest.json`에서:
```json
"version": "2.11.21"
```
→
```json
"version": "2.12.0"
```

- [ ] **Step 4: 확장앱 리로드 후 동작 확인**

1. chrome://extensions 에서 확장앱 수동 리로드 (이번이 마지막 수동 리로드)
2. 백그라운드 서비스 워커 콘솔 열기
3. 아래 로그 확인:
   ```
   [레시피] chrome.alarms 설정: 5분 주기 동기화
   [레시피] musinsa v1.0.0 캐시 갱신
   ```
4. `chrome.storage.local`에 `recipeCache.musinsa` 존재 확인

- [ ] **Step 5: 커밋**

```bash
git add extension/background.js extension/background-bootstrap.js extension/manifest.json
git commit -m "feat(recipe): 확장앱 레시피 캐시 자동 동기화 연결 (v2.12.0)"
```

---

## Task 8: 무신사 수집 로직 레시피 방식으로 전환

> 이 태스크는 Task 4에서 작성한 무신사 레시피 seed가 실제 수집 결과와 동일한지 검증 후 진행한다.

**Files:**
- Modify: `extension/background-sourcing.js`

- [ ] **Step 1: background-sourcing.js에서 무신사 수집 함수 위치 파악**

`extension/background-sourcing.js`에서 무신사 수집을 담당하는 함수(예: `collectMusinsa`, `handleMusinsaCollect` 등)를 찾는다.

- [ ] **Step 2: 해당 함수를 레시피 실행기 호출로 교체**

기존 무신사 수집 함수의 본문을 아래 패턴으로 교체:

```js
async function collectMusinsa(productUrl) {  // 기존 함수명 유지
  const recipe = await globalThis.SambaRecipeCache.getRecipe('musinsa')
  if (!recipe) {
    console.warn('[레시피] 무신사 레시피 없음 — 서버 연결 확인 필요')
    return null
  }
  return globalThis.SambaRecipeExecutor.executeRecipe(recipe, { productUrl })
}
```

- [ ] **Step 3: 로컬에서 무신사 상품 1개 수집 테스트**

백그라운드 서비스 워커 콘솔에서:

```js
const recipe = await globalThis.SambaRecipeCache.getRecipe('musinsa')
const result = await globalThis.SambaRecipeExecutor.executeRecipe(recipe, { productUrl: 'https://www.musinsa.com/products/XXXXXX' })
console.log(JSON.stringify(result, null, 2))
```

기존 수집 결과와 필드(name, price, images, options)가 동일한지 비교 확인.

- [ ] **Step 4: 커밋**

```bash
git add extension/background-sourcing.js
git commit -m "feat(recipe): 무신사 수집 로직 레시피 실행기로 전환"
```

---

## 완료 기준

- [ ] `GET /api/v1/samba/sourcing-recipes` → `{"recipes":[{"site":"musinsa","version":"1.0.0"}]}`
- [ ] 확장앱 백그라운드 콘솔에 5분마다 `[레시피] ... 캐시 갱신` 로그 없음 (변경 없으면 조용히 통과)
- [ ] 서버에서 무신사 레시피 version을 `1.0.1`로 바꾸면 → 확장앱이 다음 폴링에 자동 반영 (리로드 없음)
- [ ] 무신사 상품 수집 결과가 레시피 방식과 기존 방식에서 동일
