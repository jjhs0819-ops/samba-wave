# 상품수집 그룹별 카테고리 매핑 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 상품수집 페이지에서 검색그룹별로 전마켓 카테고리를 직접 매핑(수동+AI)하고, 이 매핑이 카테고리매핑 페이지보다 우선 적용되도록 한다.

**Architecture:** SambaSearchFilter에 target_mappings JSON 필드를 추가하여 그룹 단위로 매핑 저장. 마켓 전송 시 이 값이 있으면 SambaCategoryMapping 테이블보다 우선 적용. 프론트에서는 매핑 컬럼 + 모달로 수동/AI 매핑 제공.

**Tech Stack:** FastAPI, SQLModel, Alembic, Next.js 15, TypeScript

---

### Task 1: DB 모델 + 마이그레이션

**Files:**
- Modify: `backend/backend/domain/samba/collector/model.py`
- Create: `backend/alembic/versions/v1a2b3c4d5e6_add_target_mappings_to_search_filter.py`

- [ ] **Step 1: SambaSearchFilter에 target_mappings 필드 추가**

`backend/backend/domain/samba/collector/model.py`의 `SambaSearchFilter` 클래스에 `ss_manufacturer_name` 필드 뒤에 추가:

```python
    # 그룹별 카테고리 매핑 (카테고리매핑 페이지보다 우선 적용)
    # 예: {"smartstore": "패션의류>남성의류>티셔츠", "coupang": "남성패션/상의/티셔츠"}
    target_mappings: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
```

- [ ] **Step 2: 마이그레이션 파일 생성**

```python
# backend/alembic/versions/v1a2b3c4d5e6_add_target_mappings_to_search_filter.py
"""검색그룹에 target_mappings 컬럼 추가

Revision ID: v1a2b3c4d5e6
Revises: u9v0w1x2y3z4
Create Date: 2026-03-28 23:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'v1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'u9v0w1x2y3z4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('samba_search_filter', sa.Column('target_mappings', sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column('samba_search_filter', 'target_mappings')
```

- [ ] **Step 3: 마이그레이션 실행**

Run: `cd backend && .venv/Scripts/python.exe -m alembic upgrade head`

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/domain/samba/collector/model.py backend/alembic/versions/v1a2b3c4d5e6_add_target_mappings_to_search_filter.py
git commit -m "검색그룹에 target_mappings 컬럼 추가"
```

---

### Task 2: 백엔드 API — 매핑 저장 엔드포인트

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/collector.py`

- [ ] **Step 1: 매핑 저장 엔드포인트 추가**

기존 `update_filter` 엔드포인트는 이미 JSON 필드 업데이트를 지원하므로, `SearchFilterUpdate` DTO에 `target_mappings`를 추가하면 됨.

`backend/backend/api/v1/routers/samba/collector.py`에서 `SearchFilterUpdate` 클래스를 찾아 `target_mappings` 필드 추가:

```python
class SearchFilterUpdate(BaseModel):
    # ... 기존 필드들 ...
    target_mappings: Optional[dict] = None
```

별도 엔드포인트 없이 기존 `PUT /collector/filters/{filter_id}`로 매핑 저장 가능.

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/api/v1/routers/samba/collector.py
git commit -m "SearchFilterUpdate에 target_mappings 필드 추가"
```

---

### Task 3: 마켓 전송 시 그룹 매핑 우선 적용

**Files:**
- Modify: `backend/backend/domain/samba/shipment/service.py`

- [ ] **Step 1: _resolve_category_mappings에 그룹 매핑 우선순위 추가**

`_resolve_category_mappings` 메서드에 `group_mappings` 파라미터를 추가하고, 이 값이 있으면 DB 매핑보다 우선 적용:

```python
async def _resolve_category_mappings(
    self,
    source_site: str,
    source_category: str,
    target_account_ids: list[str],
    group_mappings: dict[str, str] | None = None,  # 그룹별 매핑 (우선 적용)
) -> dict[str, str]:
```

메서드 내부에서 각 market_type 처리 시:
```python
for market_type in market_types:
    # 1순위: 그룹별 매핑 (상품수집에서 설정)
    if group_mappings and group_mappings.get(market_type):
        result[market_type] = group_mappings[market_type]
        continue

    # 2순위: DB 매핑 (카테고리매핑 페이지에서 설정)
    if mapping and mapping.target_mappings:
        target = mapping.target_mappings.get(market_type, "")
        if target:
            result[market_type] = target
            continue

    logger.info(f"[카테고리] {market_type} 매핑 없음 — 전송 대상에서 제외")
```

- [ ] **Step 2: 전송 호출부에서 group_mappings 전달**

`_resolve_category_mappings` 호출하는 곳에서 상품의 `search_filter_id`로 SambaSearchFilter를 조회하여 `target_mappings`를 전달:

```python
# search_filter의 target_mappings 조회
group_mappings = None
if product.search_filter_id:
    from backend.domain.samba.collector.repository import SambaSearchFilterRepository
    sf_repo = SambaSearchFilterRepository(self.session)
    sf = await sf_repo.get_async(product.search_filter_id)
    if sf and sf.target_mappings:
        group_mappings = sf.target_mappings

cat_map = await self._resolve_category_mappings(
    source_site, source_category, target_account_ids, group_mappings=group_mappings,
)
```

- [ ] **Step 3: 커밋**

```bash
git add backend/backend/domain/samba/shipment/service.py
git commit -m "마켓 전송 시 그룹별 매핑 우선 적용"
```

---

### Task 4: 프론트엔드 API + 타입

**Files:**
- Modify: `frontend/src/lib/samba/api.ts`

- [ ] **Step 1: SambaSearchFilter 인터페이스에 target_mappings 추가**

```typescript
export interface SambaSearchFilter {
  // ... 기존 필드들 ...
  target_mappings?: Record<string, string>;  // 추가
}
```

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/lib/samba/api.ts
git commit -m "SambaSearchFilter에 target_mappings 타입 추가"
```

---

### Task 5: 프론트엔드 — 매핑 컬럼 + 모달

**Files:**
- Modify: `frontend/src/app/samba/collector/page.tsx`

- [ ] **Step 1: 테이블 컬럼 너비 조정 + 매핑 컬럼 추가**

컬럼 너비를 `['8%', '8%', '12%', '32%', '10%', '8%', '6%', '8%', '8%']`로 변경.
헤더에 `'매핑'` 추가 (생성일/최근수집 우측).

- [ ] **Step 2: 매핑 상태 변수 추가**

```typescript
const [showMappingModal, setShowMappingModal] = useState(false)
const [mappingFilter, setMappingFilter] = useState<SambaSearchFilter | null>(null)
const [mappingData, setMappingData] = useState<Record<string, string>>({})
const [mappingLoading, setMappingLoading] = useState(false)
```

- [ ] **Step 3: 매핑 컬럼 데이터 렌더링**

생성일/최근수집 컬럼 뒤에 매핑 컬럼 추가:
```tsx
<div style={{ ...detColStyle(8), borderRight: 'none' }}>
  {selectedFilter ? (() => {
    const tm = (selectedFilter as SambaSearchFilter).target_mappings || {}
    const mappedCount = Object.keys(tm).length
    return (
      <button
        onClick={() => {
          setMappingFilter(selectedFilter)
          setMappingData({ ...tm })
          setShowMappingModal(true)
        }}
        style={{
          padding: '0.2rem 0.5rem', fontSize: '0.7rem', borderRadius: '4px', cursor: 'pointer',
          background: mappedCount > 0 ? 'rgba(81,207,102,0.1)' : 'rgba(255,140,0,0.1)',
          border: `1px solid ${mappedCount > 0 ? 'rgba(81,207,102,0.3)' : 'rgba(255,140,0,0.3)'}`,
          color: mappedCount > 0 ? '#51CF66' : '#FF8C00',
        }}
      >{mappedCount > 0 ? `${mappedCount}개 매핑` : '매핑'}</button>
    )
  })() : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
</div>
```

- [ ] **Step 4: 매핑 모달 구현**

모달 내용:
- 활성 마켓 계정 목록 표시
- 각 마켓별 카테고리 입력 (텍스트 인풋 또는 드롭다운)
- AI매핑 버튼 → `categoryApi.aiSuggest()` 호출
- 저장 → `collectorApi.updateFilter(id, { target_mappings: mappingData })`

```tsx
{showMappingModal && mappingFilter && (
  <div style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    onClick={() => setShowMappingModal(false)}>
    <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '28px 32px', minWidth: '500px', maxWidth: '700px', maxHeight: '80vh', overflowY: 'auto' }}
      onClick={e => e.stopPropagation()}>
      <h3 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 600, color: '#E5E5E5' }}>카테고리 매핑</h3>
      <p style={{ margin: '0 0 20px', fontSize: '0.75rem', color: '#888' }}>
        {mappingFilter.name} — 각 마켓별 카테고리를 지정하세요
      </p>

      {/* AI 매핑 버튼 */}
      <button
        disabled={mappingLoading}
        onClick={async () => {
          setMappingLoading(true)
          try {
            const products = await collectorApi.scrollProducts({ skip: 0, limit: 5, search_filter_id: mappingFilter.id })
            const rep = products.items[0]
            if (!rep) { showAlert('상품이 없습니다', 'error'); return }
            const res = await categoryApi.aiSuggest({
              source_site: rep.source_site || mappingFilter.source_site,
              source_category: [rep.category1, rep.category2, rep.category3, rep.category4].filter(Boolean).join(' > ') || rep.category || '',
              sample_products: products.items.slice(0, 5).map(p => p.name || ''),
              sample_tags: rep.tags?.filter(t => !t.startsWith('__')) || [],
              target_markets: accounts.filter(a => a.is_active).map(a => a.market_type),
            })
            if (res.suggestions) {
              const newMapping: Record<string, string> = { ...mappingData }
              for (const [market, cat] of Object.entries(res.suggestions)) {
                if (cat) newMapping[market] = cat as string
              }
              setMappingData(newMapping)
              showAlert('AI 매핑 추천 완료', 'success')
            }
          } catch (e) { showAlert(e instanceof Error ? e.message : 'AI 매핑 실패', 'error') }
          finally { setMappingLoading(false) }
        }}
        style={{ marginBottom: '16px', padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: mappingLoading ? 'not-allowed' : 'pointer', border: '1px solid rgba(255,140,0,0.5)', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600, opacity: mappingLoading ? 0.6 : 1 }}
      >{mappingLoading ? 'AI 분석중...' : 'AI 매핑'}</button>

      {/* 마켓별 카테고리 입력 */}
      {accounts.filter(a => a.is_active).map(a => (
        <div key={a.id} style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '0.8rem', color: '#888', minWidth: '100px' }}>{a.market_name}</span>
          <input
            type="text"
            value={mappingData[a.market_type] || ''}
            onChange={e => setMappingData(prev => ({ ...prev, [a.market_type]: e.target.value }))}
            placeholder="카테고리 경로 입력"
            style={{ flex: 1, fontSize: '0.78rem', padding: '5px 10px', background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px', color: '#E5E5E5', outline: 'none' }}
          />
          {mappingData[a.market_type] && (
            <button onClick={() => setMappingData(prev => { const n = { ...prev }; delete n[a.market_type]; return n })}
              style={{ color: '#666', cursor: 'pointer', background: 'none', border: 'none', fontSize: '1rem' }}>&times;</button>
          )}
        </div>
      ))}

      {/* 저장/취소 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
        <button onClick={() => setShowMappingModal(false)}
          style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid #3D3D3D', background: 'transparent', color: '#888' }}>취소</button>
        <button onClick={async () => {
          try {
            const clean = Object.fromEntries(Object.entries(mappingData).filter(([, v]) => v))
            await collectorApi.updateFilter(mappingFilter.id, { target_mappings: Object.keys(clean).length > 0 ? clean : null })
            setShowMappingModal(false)
            showAlert('매핑 저장 완료', 'success')
            load(); loadTree()
          } catch (e) { showAlert(e instanceof Error ? e.message : '저장 실패', 'error') }
        }}
          style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid rgba(81,207,102,0.5)', background: 'rgba(81,207,102,0.15)', color: '#51CF66', fontWeight: 600 }}>
          저장 ({Object.values(mappingData).filter(Boolean).length}개 마켓)
        </button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/app/samba/collector/page.tsx
git commit -m "상품수집 그룹별 카테고리 매핑 컬럼 + 모달 추가"
```
