# SSG 브랜드 스캔 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SSG 수집 시 무신사 "카테고리 스캔"과 동일한 UX로, 브랜드명 입력 → 브랜드 목록 스캔 → 브랜드 선택 → 그룹 생성 흐름을 구현한다.

**Architecture:** SSGSourcingClient에 `get_brand_filters()` 메서드 추가 → 백엔드 신규 엔드포인트 2개(스캔/그룹생성) → 프론트엔드 SSG 전용 브랜드 스캔 UI 추가. 무신사 카테고리 스캔 패턴을 SSG 브랜드 스캔으로 그대로 재현한다.

**Tech Stack:** Python httpx, SSGSourcingClient, Next.js React state, Tailwind-less inline styles (기존 패턴 유지)

---

## 파일 변경 범위

| 파일 | 변경 유형 | 내용 |
|------|---------|------|
| `backend/domain/samba/proxy/ssg_sourcing.py` | 수정 | `get_brand_filters(keyword)` 메서드 추가 |
| `backend/api/v1/routers/samba/collector_collection.py` | 수정 | `POST /ssg-brand-scan`, `POST /ssg-brand-create-groups` 엔드포인트 추가 |
| `frontend/src/lib/samba/api.ts` | 수정 | `ssgBrandScan()`, `ssgBrandCreateGroups()` API 함수 추가 |
| `frontend/src/app/samba/collector/page.tsx` | 수정 | SSG 브랜드 스캔 UI 추가 |

---

### Task 1: SSGSourcingClient에 `get_brand_filters` 메서드 추가

**Files:**
- Modify: `backend/backend/domain/samba/proxy/ssg_sourcing.py`

기존 `_extract_matching_brand_ids` 바로 아래에 새 메서드 추가. 기존 메서드는 keyword로 시작하는 브랜드만 반환하지만, 이 메서드는 **전체 브랜드 + 상품 수** 반환.

- [ ] **Step 1: `get_brand_filters` 메서드 추가**

`_extract_matching_brand_ids` 메서드(line 178) 아래에 삽입:

```python
async def get_brand_filters(self, keyword: str) -> list[dict[str, Any]]:
    """키워드 검색 결과의 브랜드 필터 목록 전체 반환.

    SSG 검색 페이지 좌측 '브랜드' 섹션의 모든 항목을 반환한다.
    반환값: [{name, value, count}]
    """
    _client_kwargs: dict[str, Any] = {
        "timeout": self._timeout,
        "follow_redirects": True,
    }
    if self.proxy_url:
        _client_kwargs["proxy"] = self.proxy_url

    search_url = f"{self.SEARCH_URL}?query={quote(keyword)}&page=1"
    try:
        async with httpx.AsyncClient(**_client_kwargs) as client:
            resp = await client.get(search_url, headers=self._headers())
            if resp.status_code in (429, 403):
                raise RateLimitError(int(resp.status_code))
            if resp.status_code != 200:
                logger.warning(f"[SSG] 브랜드 스캔 HTTP {resp.status_code}")
                return []
            html = resp.text
    except RateLimitError:
        raise
    except Exception as e:
        logger.error(f"[SSG] 브랜드 스캔 실패: {keyword} — {e}")
        return []

    return self._extract_all_brand_filters(html)

def _extract_all_brand_filters(self, html: str) -> list[dict[str, Any]]:
    """__NEXT_DATA__에서 브랜드 필터 전체 목록 추출.

    반환값: [{name: str, value: str, count: int}]
    """
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return []

    try:
        next_data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    queries = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )

    brands: list[dict[str, Any]] = []
    seen: set[str] = set()

    for q in queries:
        if "useTemplateFilterQuery" not in (q.get("queryKey") or []):
            continue
        filters_data = q.get("state", {}).get("data") or []
        for f in filters_data:
            if f.get("filterType") != "brandFilter":
                continue
            for unit in f.get("unitList", []):
                for item in unit.get("dataList", []):
                    name = item.get("name", "")
                    value = item.get("value", "")
                    count = int(item.get("count", 0))
                    if value and value not in seen:
                        brands.append({"name": name, "value": value, "count": count})
                        seen.add(value)

    return brands
```

- [ ] **Step 2: ruff 포맷 + 린트**

```bash
cd backend
.venv/Scripts/python.exe -m ruff format backend/domain/samba/proxy/ssg_sourcing.py
.venv/Scripts/python.exe -m ruff check --fix backend/domain/samba/proxy/ssg_sourcing.py
```

Expected: 오류 없음

---

### Task 2: 백엔드 API 엔드포인트 2개 추가

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/collector_collection.py`

기존 `brand_scan` 엔드포인트(`/brand-scan`) 바로 아래에 SSG 전용 2개 추가.

- [ ] **Step 1: Pydantic 모델 + 엔드포인트 추가**

`collector_collection.py`의 `brand_scan` 함수 끝(`return { "categories": ... }`) 바로 다음 줄에 삽입:

```python


class SSGBrandScanRequest(BaseModel):
    keyword: str


@router.post("/ssg-brand-scan")
async def ssg_brand_scan(req: SSGBrandScanRequest):
    """SSG 키워드 검색 → 브랜드 필터 목록 반환."""
    from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

    client = SSGSourcingClient()
    try:
        brands = await client.get_brand_filters(req.keyword)
    except Exception as e:
        raise HTTPException(500, f"SSG 브랜드 스캔 실패: {e}")

    if not brands:
        raise HTTPException(404, f"'{req.keyword}' 검색 결과에서 브랜드를 찾을 수 없습니다")

    return {"brands": brands, "total": len(brands)}


class SSGBrandGroup(BaseModel):
    name: str    # 브랜드명 (표시용)
    value: str   # repBrandId


class SSGBrandCreateGroupsRequest(BaseModel):
    keyword: str              # 검색 키워드
    brands: list[SSGBrandGroup]
    max_discount: bool = True


@router.post("/ssg-brand-create-groups")
async def ssg_brand_create_groups(
    req: SSGBrandCreateGroupsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """선택한 SSG 브랜드별 검색그룹 생성."""
    from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

    svc = _get_services(session)
    created = 0

    for brand in req.brands:
        # 브랜드 필터가 적용된 SSG 검색 URL을 keyword로 저장
        brand_url = (
            f"https://department.ssg.com/search?query={req.keyword}"
            f"&repBrandId={brand.value}"
        )
        if req.max_discount:
            brand_url += "&maxDiscount=1"

        group_name = f"{req.keyword} - {brand.name}"
        await svc.create_filter(
            {
                "source_site": "SSG",
                "name": group_name,
                "keyword": brand_url,
                "requested_count": 100,
            }
        )
        created += 1

    await session.commit()
    return {"created": created}
```

- [ ] **Step 2: ruff 포맷 + 린트**

```bash
cd backend
.venv/Scripts/python.exe -m ruff format backend/api/v1/routers/samba/collector_collection.py
.venv/Scripts/python.exe -m ruff check --fix backend/api/v1/routers/samba/collector_collection.py
```

Expected: 오류 없음

---

### Task 3: 프론트엔드 API 클라이언트 함수 추가

**Files:**
- Modify: `frontend/src/lib/samba/api.ts`

`collectorApi` 객체 내에 추가.

- [ ] **Step 1: `collectorApi`에 2개 함수 추가**

`api.ts`의 `collectorApi` 객체에서 마지막 항목 바로 앞에 추가:

```typescript
  ssgBrandScan: (keyword: string) =>
    request<{ brands: { name: string; value: string; count: number }[]; total: number }>(
      `${SAMBA_PREFIX}/collector/ssg-brand-scan`,
      { method: 'POST', body: JSON.stringify({ keyword }) }
    ),
  ssgBrandCreateGroups: (data: {
    keyword: string;
    brands: { name: string; value: string }[];
    max_discount?: boolean;
  }) =>
    request<{ created: number }>(
      `${SAMBA_PREFIX}/collector/ssg-brand-create-groups`,
      { method: 'POST', body: JSON.stringify(data) }
    ),
```

---

### Task 4: 프론트엔드 SSG 브랜드 스캔 UI 추가

**Files:**
- Modify: `frontend/src/app/samba/collector/page.tsx`

무신사 카테고리 스캔과 동일한 패턴으로 SSG 브랜드 스캔 UI 추가.

- [ ] **Step 1: SSG 브랜드 상태 변수 추가**

기존 `brandScanning` 상태 선언 부근(line ~167)에 추가:

```tsx
const [ssgBrandScanning, setSsgBrandScanning] = useState(false)
const [ssgBrands, setSsgBrands] = useState<{ name: string; value: string; count: number }[]>([])
const [ssgSelectedBrands, setSsgSelectedBrands] = useState<Set<string>>(new Set())
```

- [ ] **Step 2: URL 입력창 placeholder에 SSG 추가**

현재 코드 (line ~953):
```tsx
placeholder={
  selectedSite === "MUSINSA" ? "브랜드명 또는 URL (예: 나이키, https://www.musinsa.com/search/goods?keyword=나이키)" :
  selectedSite === "KREAM" ? "https://kream.co.kr/search?keyword=나이키" :
  "URL을 입력하세요"
}
```

변경 후:
```tsx
placeholder={
  selectedSite === "MUSINSA" ? "브랜드명 또는 URL (예: 나이키, https://www.musinsa.com/search/goods?keyword=나이키)" :
  selectedSite === "KREAM" ? "https://kream.co.kr/search?keyword=나이키" :
  selectedSite === "SSG" ? "브랜드명 입력 (예: 다이나핏, 나이키)" :
  "URL을 입력하세요"
}
```

- [ ] **Step 3: SSG 브랜드 스캔 버튼 추가**

기존 MUSINSA 카테고리 스캔 버튼 블록 (`{selectedSite === 'MUSINSA' && (`) 바로 다음에 SSG 버튼 블록 추가:

```tsx
          {selectedSite === 'SSG' && (
            <button onClick={async () => {
              const keyword = collectUrl.trim()
              if (!keyword) { showAlert('브랜드명을 입력하세요'); return }
              setSsgBrandScanning(true)
              setSsgBrands([]); setSsgSelectedBrands(new Set())
              try {
                const res = await collectorApi.ssgBrandScan(keyword)
                setSsgBrands(res.brands)
                setSsgSelectedBrands(new Set(res.brands.map(b => b.value)))
                addLog(`[SSG 브랜드스캔] "${keyword}": ${res.total}개 브랜드 발견`)
              } catch (e) { showAlert(e instanceof Error ? e.message : '브랜드 스캔 실패', 'error') }
              setSsgBrandScanning(false)
            }} disabled={ssgBrandScanning}
              style={{ padding: '0.6rem 1rem', background: ssgBrandScanning ? '#333' : 'transparent', border: '1px solid #FF8C00', borderRadius: '6px', color: '#FF8C00', fontSize: '0.82rem', fontWeight: 600, cursor: ssgBrandScanning ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>
              {ssgBrandScanning ? '스캔 중...' : '브랜드 스캔'}
            </button>
          )}
```

- [ ] **Step 4: "그룹 생성" 버튼에 SSG 분기 추가**

기존 "그룹 생성" 버튼 onClick 내부에서, `brandCategories.length > 0` 분기 **앞**에 SSG 분기 추가:

현재 코드:
```tsx
onClick={async () => {
  // 카테고리 스캔 결과가 있으면 선택된 카테고리별 그룹 생성
  if (brandCategories.length > 0 && brandSelectedCats.size > 0) {
```

변경 후:
```tsx
onClick={async () => {
  // SSG 브랜드 스캔 결과가 있으면 선택된 브랜드별 그룹 생성
  if (selectedSite === 'SSG' && ssgBrands.length > 0) {
    const selected = ssgBrands.filter(b => ssgSelectedBrands.has(b.value))
    if (selected.length === 0) { showAlert('브랜드를 선택하세요'); return }
    try {
      const res = await collectorApi.ssgBrandCreateGroups({
        keyword: collectUrl.trim(),
        brands: selected,
        max_discount: checkedOptions['maxDiscount'] ?? true,
      })
      addLog(`[SSG 브랜드] ${res.created}개 그룹 생성 완료`)
      showAlert(`${res.created}개 그룹이 생성되었습니다`, 'success')
      setSsgBrands([]); setSsgSelectedBrands(new Set())
      load(); loadTree()
    } catch (e) { showAlert(e instanceof Error ? e.message : '그룹 생성 실패', 'error') }
    return
  }
  // 카테고리 스캔 결과가 있으면 선택된 카테고리별 그룹 생성
  if (brandCategories.length > 0 && brandSelectedCats.size > 0) {
```

- [ ] **Step 5: SSG 브랜드 목록 표시 UI 추가**

기존 무신사 카테고리 스캔 결과 블록 (`{brandCategories.length > 0 && (`) **바로 앞**에 SSG 브랜드 목록 UI 추가:

```tsx
        {/* SSG 브랜드 스캔 결과 */}
        {ssgBrands.length > 0 && (
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.75rem', maxHeight: '350px', overflowY: 'auto' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <span style={{ fontSize: '0.78rem', color: '#888' }}>
                  {ssgBrands.length}개 브랜드 (선택 {ssgSelectedBrands.size}개)
                </span>
                <div style={{ display: 'flex', gap: '0.25rem' }}>
                  <button onClick={() => setSsgSelectedBrands(new Set(ssgBrands.map(b => b.value)))}
                    style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>전체선택</button>
                  <button onClick={() => setSsgSelectedBrands(new Set())}
                    style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>전체해제</button>
                  <button onClick={() => { setSsgBrands([]); setSsgSelectedBrands(new Set()) }}
                    style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>초기화</button>
                </div>
              </div>
              {ssgBrands.map(brand => (
                <label key={brand.value} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.2rem 0', cursor: 'pointer', fontSize: '0.78rem' }}>
                  <input type="checkbox" checked={ssgSelectedBrands.has(brand.value)}
                    onChange={e => {
                      const next = new Set(ssgSelectedBrands)
                      if (e.target.checked) next.add(brand.value); else next.delete(brand.value)
                      setSsgSelectedBrands(next)
                    }} style={{ accentColor: '#FF8C00' }} />
                  <span style={{ color: '#E5E5E5', flex: 1 }}>{brand.name}</span>
                  <span style={{ color: '#FF8C00', fontWeight: 600, fontSize: '0.72rem' }}>{brand.count.toLocaleString()}건</span>
                </label>
              ))}
            </div>
          </div>
        )}
```

- [ ] **Step 6: "그룹 생성" 버튼 텍스트에 SSG 분기 추가**

현재:
```tsx
{collecting ? "생성중..." : brandCategories.length > 0 ? `그룹 생성 (${brandSelectedCats.size}개)` : "그룹 생성"}
```

변경 후:
```tsx
{collecting ? "생성중..." :
  ssgBrands.length > 0 ? `그룹 생성 (${ssgSelectedBrands.size}개)` :
  brandCategories.length > 0 ? `그룹 생성 (${brandSelectedCats.size}개)` :
  "그룹 생성"}
```

---

### Task 5: ruff 포맷 + 커밋

- [ ] **Step 1: 백엔드 최종 ruff 확인**

```bash
cd backend
.venv/Scripts/python.exe -m ruff format .
.venv/Scripts/python.exe -m ruff check --fix .
```

- [ ] **Step 2: 커밋**

```bash
cd ..
git add backend/backend/domain/samba/proxy/ssg_sourcing.py
git add backend/backend/api/v1/routers/samba/collector_collection.py
git add frontend/src/lib/samba/api.ts
git add frontend/src/app/samba/collector/page.tsx
git commit -m "SSG 브랜드 스캔 — 무신사 카테고리 스캔과 동일한 UX로 브랜드 선택 후 그룹 생성"
```

---

## 테스트 방법

1. 상품수집 페이지에서 `신세계몰` 버튼 ON
2. URL 입력창에 `다이나핏` 입력
3. `브랜드 스캔` 버튼 클릭
4. 브랜드 목록 표시 확인 (예: DYNAMIC FIT 234건, ...)
5. 원하는 브랜드 체크 → `그룹 생성` 클릭
6. 좌측 트리에 `다이나핏 - DYNAMIC FIT` 그룹 생성 확인
7. 수집 버튼 클릭 → 배치 수집 진행 확인
