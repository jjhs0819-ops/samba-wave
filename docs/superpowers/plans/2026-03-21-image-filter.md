# 상품 이미지 자동 필터링 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집된 상품 이미지에서 순수 이미지컷만 남기고 모델컷/연출컷/배너 등을 자동 제거하는 기능 구현

**Architecture:** Claude Vision API로 이미지를 "product"(이미지컷) vs "other"(나머지)로 분류한 뒤, 이미지컷이 있으면 나머지 삭제, 없으면 Fireworks AI로 배경제거 변환. 기존 `ImageTransformService`의 다운로드/저장 유틸을 재사용.

**Tech Stack:** Python/FastAPI, Anthropic Claude Vision API, Fireworks AI, Next.js/TypeScript

**Spec:** `docs/superpowers/specs/2026-03-21-model-cut-filter-design.md`

---

## 파일 구조

| 파일 | 역할 | 변경 |
|------|------|------|
| `backend/domain/samba/image/image_filter_service.py` | 이미지 분류/필터링 서비스 | 신규 |
| `backend/api/v1/routers/samba/proxy.py` | API 엔드포인트 추가 | 수정 |
| `frontend/src/lib/samba/api.ts` | API 함수 추가 | 수정 |
| `frontend/src/app/samba/collector/page.tsx` | 이미지 필터링 UI 버튼 | 수정 |

---

### Task 1: 이미지 분류 서비스 — `_download_and_encode` + `classify_images`

**Files:**
- Create: `backend/domain/samba/image/image_filter_service.py`

- [ ] **Step 1: 서비스 클래스 기본 구조 + `_download_and_encode` 작성**

```python
# backend/domain/samba/image/image_filter_service.py
"""상품 이미지 자동 필터링 — Claude Vision 분류 + Fireworks 변환."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.core.config import settings

logger = logging.getLogger(__name__)

# Claude Vision 분류 프롬프트
CLASSIFY_PROMPT = """아래 상품 이미지들을 각각 분류하세요:

- "product": 단색 또는 단순 배경에 상품만 단독 촬영된 사진
  (행거컷, 평놓기, 마네킹, 각도별 촬영, 디테일 클로즈업, 밑창 등)
- "other": 그 외 모든 이미지
  (모델 착용, 연출/라이프스타일, 야외 배경, 브랜드 배너, 사이즈표, 스펙표, 로고 등)

주의:
- 상품 자체에 사람이 프린팅된 경우는 "product"로 분류
- 배경이 단색(흰색, 회색, 검정 등)이고 상품만 있으면 "product"
- 배경에 소품, 자연환경, 실내 인테리어 등이 보이면 "other"

이미지 순서대로 JSON 배열로만 답변 (다른 텍스트 없이):
[{"index": 0, "type": "product"}, {"index": 1, "type": "other"}, ...]"""


class ImageFilterService:
  """Claude Vision으로 이미지 분류 후 필터링."""

  def __init__(self, session: AsyncSession) -> None:
    self.session = session

  async def _download_and_encode(self, url: str) -> tuple[str, str]:
    """이미지 URL → 바이트 다운로드 → base64 인코딩.

    Returns:
      (base64_data, media_type) 튜플
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
      resp = await client.get(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": url,
      })
      resp.raise_for_status()

    content_type = resp.headers.get("content-type", "image/jpeg")
    # content-type에서 media_type 추출 (예: "image/jpeg; charset=utf-8" → "image/jpeg")
    media_type = content_type.split(";")[0].strip()
    if not media_type.startswith("image/"):
      media_type = "image/jpeg"

    b64 = base64.b64encode(resp.content).decode("ascii")
    return b64, media_type
```

- [ ] **Step 2: `classify_images` 작성 — Claude Vision API 호출**

같은 파일에 이어서 추가:

```python
  async def classify_images(self, urls: list[str]) -> list[dict[str, str]]:
    """이미지 URL 리스트를 Claude Vision으로 분류.

    최대 20장을 1회 요청에 묶어 전송한다.
    다운로드 실패한 이미지는 "product"로 분류 (원본 유지).

    Returns:
      [{"url": "...", "type": "product"/"other"}, ...]
    """
    import anthropic

    api_key = settings.anthropic_api_key
    if not api_key:
      raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다")

    # 이미지 다운로드 + base64 인코딩
    encoded: list[tuple[int, str, str, str]] = []  # (index, url, b64, media_type)
    failed_indices: set[int] = set()

    for idx, url in enumerate(urls):
      try:
        b64, media_type = await self._download_and_encode(url)
        encoded.append((idx, url, b64, media_type))
      except Exception as e:
        logger.warning(f"[이미지필터] 다운로드 실패 (원본 유지): {url[:80]} — {e}")
        failed_indices.add(idx)

    if not encoded:
      # 모든 이미지 다운로드 실패 → 전부 product로 분류 (원본 유지)
      return [{"url": u, "type": "product"} for u in urls]

    # Claude Vision 요청 (최대 20장씩 묶음)
    results: list[dict[str, str]] = []
    client = anthropic.AsyncAnthropic(api_key=api_key)

    for chunk_start in range(0, len(encoded), 20):
      chunk = encoded[chunk_start:chunk_start + 20]

      # 이미지 content 블록 구성
      content: list[dict[str, Any]] = []
      for _, _, b64, media_type in chunk:
        content.append({
          "type": "image",
          "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
      content.append({"type": "text", "text": CLASSIFY_PROMPT})

      try:
        response = await client.messages.create(
          model="claude-sonnet-4-20250514",
          max_tokens=1024,
          messages=[{"role": "user", "content": content}],
        )
        # 응답 파싱
        text = response.content[0].text.strip()
        # JSON 배열 추출 (앞뒤 마크다운 코드블록 제거)
        if text.startswith("```"):
          text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        classifications = json.loads(text)

        for item in classifications:
          ci = item["index"]
          real_idx = chunk[ci][0]  # 원본 인덱스
          real_url = chunk[ci][1]
          results.append({"url": real_url, "type": item.get("type", "product")})

      except Exception as e:
        logger.error(f"[이미지필터] Claude Vision 호출 실패: {e}")
        # 실패 시 해당 청크 전부 product로 분류
        for _, url, _, _ in chunk:
          results.append({"url": url, "type": "product"})

    # 다운로드 실패한 이미지도 product로 추가
    for idx in failed_indices:
      results.append({"url": urls[idx], "type": "product"})

    # 원본 순서대로 정렬
    url_order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r["url"], 999))
    return results
```

- [ ] **Step 3: 커밋**

```bash
git add backend/domain/samba/image/image_filter_service.py
git commit -m "이미지 필터링 서비스 기본 구조 — 다운로드/인코딩 + Claude Vision 분류"
```

---

### Task 2: 필터링 로직 — `filter_product` + `batch_filter` + `filter_by_group`

**Files:**
- Modify: `backend/domain/samba/image/image_filter_service.py`

- [ ] **Step 1: `filter_product` 작성**

`ImageFilterService` 클래스에 추가:

```python
  async def filter_product(self, product_id: str) -> dict[str, Any]:
    """단일 상품 이미지 필터링.

    이미지컷이 있으면 나머지 삭제, 없으면 Fireworks AI로 변환.
    """
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    repo = SambaCollectedProductRepository(self.session)
    product = await repo.get_async(product_id)
    if not product:
      return {"action": "skipped", "reason": "not_found"}

    images = product.images or []
    if not images:
      return {"action": "skipped", "reason": "no_images"}

    # 1. 이미지 분류
    classifications = await self.classify_images(images)
    product_cuts = [c["url"] for c in classifications if c["type"] == "product"]
    others = [c["url"] for c in classifications if c["type"] == "other"]

    # 2. 분기 처리
    if product_cuts:
      # 이미지컷 존재 → 나머지 삭제
      await repo.update_async(product_id, images=product_cuts)
      return {"action": "filtered", "removed": len(others), "kept": len(product_cuts)}
    else:
      # 이미지컷 없음 → Fireworks AI로 변환
      transformed = await self._transform_to_product_cuts(others)
      if transformed:
        await repo.update_async(product_id, images=transformed)
        return {"action": "transformed", "count": len(transformed)}
      else:
        # 변환도 실패 → 원본 유지
        return {"action": "skipped", "reason": "transform_failed"}
```

- [ ] **Step 2: `_transform_to_product_cuts` 작성 — Fireworks AI 연동**

```python
  async def _transform_to_product_cuts(self, urls: list[str]) -> list[str]:
    """모델컷/연출컷을 Fireworks AI background 모드로 변환.

    기존 ImageTransformService의 메서드를 재사용한다.
    """
    from backend.domain.samba.image.service import ImageTransformService

    svc = ImageTransformService(self.session)
    try:
      api_key, model = await svc._get_fireworks_config()
    except ValueError as e:
      logger.warning(f"[이미지필터] Fireworks 설정 없음: {e}")
      return []

    transformed_urls: list[str] = []
    for url in urls:
      try:
        img_bytes = await svc._download_image(url)
        result_bytes = await svc._transform_image(api_key, model, img_bytes, "background")
        new_url = await svc._save_image(result_bytes, url)
        transformed_urls.append(new_url)
      except Exception as e:
        logger.error(f"[이미지필터] Fireworks 변환 실패: {url[:80]} — {e}")
        transformed_urls.append(url)  # 실패 시 원본 유지
    return transformed_urls
```

- [ ] **Step 3: `batch_filter` + `filter_by_group` 작성**

```python
  async def batch_filter(self, product_ids: list[str]) -> dict[str, Any]:
    """다중 상품 일괄 필터링. 상품 단위 커밋 (부분 성공 허용)."""
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for pid in product_ids:
      try:
        result = await self.filter_product(pid)
        results[pid] = result
      except Exception as e:
        logger.error(f"[이미지필터] 상품 {pid} 처리 실패: {e}")
        errors[pid] = str(e)

    return {
      "success": True,
      "results": results,
      "total": len(results),
      "errors": errors,
    }

  async def filter_by_group(self, filter_id: str) -> dict[str, Any]:
    """수집 그룹(search_filter_id) 단위 필터링."""
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    repo = SambaCollectedProductRepository(self.session)
    products = await repo.list_by_filter(filter_id, skip=0, limit=10000)
    product_ids = [p.id for p in products]

    if not product_ids:
      return {"success": True, "results": {}, "total": 0, "errors": {}, "message": "해당 그룹에 상품이 없습니다."}

    return await self.batch_filter(product_ids)
```

- [ ] **Step 4: 커밋**

```bash
git add backend/domain/samba/image/image_filter_service.py
git commit -m "이미지 필터링 — filter_product/batch_filter/filter_by_group + Fireworks 변환 연동"
```

---

### Task 3: API 엔드포인트

**Files:**
- Modify: `backend/api/v1/routers/samba/proxy.py`

- [ ] **Step 1: 엔드포인트 추가**

`proxy.py`의 fireworks_transform_images 엔드포인트 바로 아래(L648 부근)에 추가:

```python
@router.post("/image-filter/filter")
async def filter_product_images(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """상품 이미지 자동 필터링 — 이미지컷만 남기고 모델컷/연출컷/배너 제거."""
    from backend.domain.samba.image.image_filter_service import ImageFilterService

    svc = ImageFilterService(session)
    product_ids: list[str] = request.get("product_ids", [])
    filter_id: str = request.get("filter_id", "")

    # filter_id로 요청 시 해당 그룹의 상품 ID 조회 (product_ids 우선)
    if filter_id and not product_ids:
      try:
        result = await svc.filter_by_group(filter_id)
        return result
      except Exception as exc:
        logger.error(f"[이미지필터] 그룹 필터링 실패: {exc}")
        return {"success": False, "message": str(exc)[:300]}

    if not product_ids:
      return {"success": False, "message": "product_ids 또는 filter_id를 입력하세요."}

    try:
      result = await svc.batch_filter(product_ids)
      return result
    except Exception as exc:
      logger.error(f"[이미지필터] 배치 필터링 실패: {exc}")
      return {"success": False, "message": str(exc)[:300]}
```

- [ ] **Step 2: 커밋**

```bash
git add backend/api/v1/routers/samba/proxy.py
git commit -m "이미지 필터링 API 엔드포인트 추가 — POST /image-filter/filter"
```

---

### Task 4: 프론트엔드 — API 함수 + 버튼 UI

**Files:**
- Modify: `frontend/src/lib/samba/api.ts`
- Modify: `frontend/src/app/samba/collector/page.tsx`

- [ ] **Step 1: API 함수 추가**

`api.ts`의 `transformByGroups` 아래(L514 부근)에 추가:

```typescript
  filterProductImages: (productIds: string[], filterId?: string) =>
    request<{ success: boolean; results: Record<string, { action: string; removed?: number; kept?: number; count?: number }>; total: number; errors: Record<string, string> }>(
      `${SAMBA_PREFIX}/proxy/image-filter/filter`, {
        method: 'POST',
        body: JSON.stringify({ product_ids: productIds, filter_id: filterId || '' }),
      }),
```

- [ ] **Step 2: collector/page.tsx — state + 핸들러 추가**

기존 `aiImgTransforming` state 근처에 추가:

```typescript
  // 이미지 필터링 (모델컷/연출컷 제거)
  const [imgFiltering, setImgFiltering] = useState(false)
```

핸들러 함수 추가 (기존 AI 이미지 변환 핸들러 근처):

```typescript
  // 이미지 필터링 핸들러
  const handleImageFilter = async (targetIds?: string[], filterId?: string) => {
    const ids = targetIds || selectedIds
    if (!ids.length && !filterId) return
    setImgFiltering(true)
    try {
      const res = await sambaApi.filterProductImages(ids, filterId)
      if (res.success) {
        const total = res.total || 0
        const errorCount = Object.keys(res.errors || {}).length
        if (errorCount > 0) {
          toast.warning(`이미지 필터링: ${total - errorCount}개 완료, ${errorCount}개 실패`)
        } else {
          toast.success(`이미지 필터링 완료 — ${total}개 상품 처리`)
        }
        fetchProducts()
      } else {
        toast.error(res.message || '이미지 필터링 실패')
      }
    } catch (e) {
      toast.error(`이미지 필터링 오류: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setImgFiltering(false)
    }
  }
```

- [ ] **Step 3: 상품 목록 — 체크박스 선택 시 "이미지 필터링" 버튼**

기존 "AI 이미지 변환" 섹션 바로 아래에 추가:

```tsx
      {/* 이미지 필터링 (모델컷/연출컷 제거) */}
      {selectedIds.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', borderRadius: '8px', marginTop: '0.5rem' }}>
          <span style={{ fontSize: '0.8125rem', color: '#818CF8', fontWeight: 600 }}>이미지 필터링</span>
          <span style={{ fontSize: '0.75rem', color: '#999' }}>모델컷·연출컷·배너 자동 제거</span>
          <button
            onClick={() => handleImageFilter()}
            disabled={imgFiltering}
            style={{ marginLeft: 'auto', padding: '0.375rem 1rem', background: imgFiltering ? '#555' : '#6366F1', color: '#fff', border: 'none', borderRadius: '6px', fontSize: '0.8125rem', cursor: imgFiltering ? 'not-allowed' : 'pointer' }}
          >
            {imgFiltering ? '처리중...' : `선택 ${selectedIds.length}개 필터링`}
          </button>
        </div>
      )}
```

- [ ] **Step 4: 수집 그룹 목록 — 그룹별 "이미지 필터링" 버튼**

수집 그룹 행에 버튼 추가. 기존 "상품보기" 버튼 옆에:

```tsx
<button
  onClick={(e) => { e.stopPropagation(); handleImageFilter([], f.id) }}
  disabled={imgFiltering}
  style={{ padding: '0.25rem 0.5rem', background: 'rgba(99,102,241,0.15)', color: '#818CF8', border: '1px solid rgba(99,102,241,0.3)', borderRadius: '4px', fontSize: '0.75rem', cursor: imgFiltering ? 'not-allowed' : 'pointer' }}
>
  {imgFiltering ? '처리중...' : '이미지필터링'}
</button>
```

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/lib/samba/api.ts frontend/src/app/samba/collector/page.tsx
git commit -m "이미지 필터링 프론트엔드 — API 함수 + 목록/그룹 버튼 추가"
```

---

### Task 5: 통합 테스트 — 실제 API 호출 확인

**Files:** 없음 (수동 테스트)

- [ ] **Step 1: 백엔드 서버 재시작**

```bash
cd backend && .venv/Scripts/python.exe run.py
```

- [ ] **Step 2: API 직접 호출 테스트**

```bash
# 단일 상품 테스트 (실제 수집된 상품 ID 사용)
curl -X POST http://localhost:28080/api/v1/samba/proxy/image-filter/filter \
  -H "Content-Type: application/json" \
  -d '{"product_ids": ["<실제_상품_ID>"]}'
```

확인 사항:
- 응답에 `success: true`
- `results`에 각 상품별 `action` ("filtered" / "transformed" / "skipped")
- `removed` > 0이면 모델컷/연출컷이 실제로 제거됨

- [ ] **Step 3: 프론트엔드 확인**

1. `pnpm dev`로 프론트 실행
2. 수집 상품 목록에서 체크박스 선택 → "이미지 필터링" 버튼 클릭
3. 토스트 알림 확인
4. 상품 상세에서 이미지가 필터링됐는지 확인

- [ ] **Step 4: 최종 커밋 (필요 시)**

```bash
git add -A
git commit -m "이미지 필터링 통합 테스트 완료 — 버그 수정"
```
