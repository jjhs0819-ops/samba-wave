# SSG 배치 수집 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SSG 수집 시 50개 단위로 분할하여 배치 간 60초 대기를 주어 SSG 차단을 회피하고, 동시에 재수집 시 Job Worker에서 발생하는 "미지원 소싱처" 버그를 수정한다.

**Architecture:** `worker.py`의 `_run_collect`에 SSG 전용 분기를 추가하고, 새 `_collect_ssg` 메서드를 구현한다. 검색으로 후보 상품을 모두 확보한 뒤 50개 배치 단위로 상세 수집하며, 배치 완료 후 60초 대기한다. 기존 `_build_product_data` 헬퍼를 재사용하여 중복 코드를 최소화한다.

**Tech Stack:** Python asyncio, SSGSourcingClient, SQLAlchemy async, `collector_common._build_product_data`

---

## 파일 변경 범위

| 파일 | 변경 유형 | 내용 |
|------|---------|------|
| `backend/backend/domain/samba/job/worker.py` | 수정 | SSG 라우팅 추가 + `_collect_ssg` 메서드 신규 추가 |

---

### Task 1: SSG 라우팅 분기 추가

**Files:**
- Modify: `backend/backend/domain/samba/job/worker.py:747-753`

- [ ] **Step 1: SSG를 EXTENSION_SITES에서 제거하고 전용 분기 추가**

`worker.py`의 `_run_collect` 메서드에서 아래 부분을 수정한다.

현재 코드 (line 736-753):
```python
        # 확장앱 기반 소싱처 (소싱큐)
        EXTENSION_SITES = {
            "ABCmart",
            "GrandStage",
            "OKmall",
            "LOTTEON",
            "GSShop",
            "ElandMall",
            "SSF",
            "SSG",
        }

        if site in DIRECT_API_SITES:
            await self._collect_direct_api(job, sf, session, repo)
            return

        if site in EXTENSION_SITES:
            await self._collect_direct_api(job, sf, session, repo)
            return
```

변경 후:
```python
        # 확장앱 기반 소싱처 (소싱큐)
        EXTENSION_SITES = {
            "ABCmart",
            "GrandStage",
            "OKmall",
            "LOTTEON",
            "GSShop",
            "ElandMall",
            "SSF",
        }

        if site in DIRECT_API_SITES:
            await self._collect_direct_api(job, sf, session, repo)
            return

        if site == "SSG":
            await self._collect_ssg(job, sf, session, repo)
            return

        if site in EXTENSION_SITES:
            await self._collect_direct_api(job, sf, session, repo)
            return
```

- [ ] **Step 2: 변경 확인**

```bash
cd backend
grep -n "SSG\|EXTENSION_SITES" backend/domain/samba/job/worker.py | head -20
```

Expected: SSG가 EXTENSION_SITES에서 제거되고 전용 분기가 생긴 것 확인.

---

### Task 2: `_collect_ssg` 메서드 구현

**Files:**
- Modify: `backend/backend/domain/samba/job/worker.py` (클래스 내부, `_collect_direct_api` 메서드 바로 앞에 추가)

- [ ] **Step 1: `_collect_ssg` 메서드 추가**

`_collect_direct_api` 메서드 정의(`async def _collect_direct_api`) 바로 **앞**에 다음 메서드를 삽입한다.

```python
    async def _collect_ssg(self, job, sf, session, repo):
        """SSG 소싱처 배치 수집.

        50개 단위로 분할하여 배치 간 60초 대기 — SSG 차단 회피.
        requested_count 기준으로 remaining 계산하여 정확한 수량 수집.
        """
        import asyncio
        from urllib.parse import parse_qs, urlparse

        from sqlmodel import func as _func
        from sqlmodel import select

        from backend.api.v1.routers.samba.collector_common import _build_product_data
        from backend.api.v1.routers.samba.collector_common import (
            _get_services,
        )
        from backend.domain.samba.collector.model import (
            SambaCollectedProduct as CPModel,
        )
        from backend.domain.samba.job.model import SambaJob as _SJ
        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        SSG_BATCH_SIZE = 50   # 배치당 수집 개수
        SSG_BATCH_DELAY = 60  # 배치 간 대기 (초)
        SSG_PAGE_SIZE = 40    # SSG API 한 페이지 크기

        filter_id = sf.id
        keyword_url = sf.keyword or ""
        requested_count = sf.requested_count or 100

        # URL에서 키워드·옵션 파싱
        try:
            parsed = urlparse(keyword_url)
            qs = parse_qs(parsed.query)
            keyword = qs.get("query", [keyword_url])[0]
            use_max_discount = qs.get("maxDiscount", [""])[0] == "1"
        except Exception:
            keyword = keyword_url
            use_max_discount = False

        if not keyword:
            await repo.fail_job(job.id, "SSG 키워드 없음")
            return

        # 기존 수집 수 확인
        count_stmt = select(_func.count()).where(CPModel.search_filter_id == filter_id)
        existing_count = (await session.execute(count_stmt)).scalar() or 0
        remaining = max(0, requested_count - existing_count)

        if remaining <= 0:
            await repo.complete_job(
                job.id,
                {"saved": 0, "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)"},
            )
            return

        await repo.update_progress(job.id, existing_count, requested_count)

        client = SSGSourcingClient()

        # ── 검색 단계: 후보 상품 목록 수집 ──
        all_items: list[dict] = []
        # remaining의 2배 분량 확보 (중복·품절 제거 후 충분한 후보 보장)
        max_search_pages = min(25, max(1, (remaining * 2 // SSG_PAGE_SIZE) + 2))
        for page in range(1, max_search_pages + 1):
            if len(all_items) >= remaining * 2:
                break
            try:
                items = await client.search_products(
                    keyword=keyword, page=page, size=SSG_PAGE_SIZE
                )
                if not items:
                    break
                all_items.extend(items)
                await asyncio.sleep(1.0)  # 검색 페이지 간 딜레이
            except Exception as e:
                logger.warning(f"[SSG] 검색 p{page} 실패: {e}")
                break

        if not all_items:
            await repo.fail_job(job.id, f"SSG '{keyword}' 검색 결과 없음")
            return

        # ── 중복 필터링 ──
        candidate_ids = [
            str(item.get("siteProductId", item.get("goodsNo", "")))
            for item in all_items
            if item.get("siteProductId") or item.get("goodsNo")
        ]
        existing_result = await session.execute(
            select(CPModel.site_product_id).where(
                CPModel.source_site == "SSG",
                CPModel.site_product_id.in_(candidate_ids),
            )
        )
        existing_ids = {row[0] for row in existing_result.all()}

        targets: list[str] = []
        for item in all_items:
            if len(targets) >= remaining:
                break
            site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
            if not site_pid:
                continue
            if site_pid in existing_ids:
                continue
            if item.get("isSoldOut", False):
                continue
            targets.append(site_pid)

        svc = _get_services(session)
        total_saved = 0
        total_batches = max(1, (len(targets) + SSG_BATCH_SIZE - 1) // SSG_BATCH_SIZE)

        # ── 배치 수집 루프 ──
        for i, item_id in enumerate(targets):
            # 취소 확인
            _job_chk = await session.get(_SJ, job.id)
            if _job_chk and _job_chk.status.value == "failed":
                logger.info(f"[SSG] 수집 취소됨: {job.id}")
                return

            # 배치 경계: SSG_BATCH_SIZE번째마다 대기
            if i > 0 and i % SSG_BATCH_SIZE == 0:
                current_batch = i // SSG_BATCH_SIZE
                logger.info(
                    f"[SSG] 배치 {current_batch}/{total_batches} 완료 "
                    f"({total_saved}개 저장), {SSG_BATCH_DELAY}초 대기 중..."
                )
                await repo.update_progress(
                    job.id, existing_count + total_saved, requested_count
                )
                await asyncio.sleep(SSG_BATCH_DELAY)

            try:
                detail = await client.get_product_detail(item_id)
                if not detail or not detail.get("name"):
                    await asyncio.sleep(1.0)
                    continue

                # 가격 계산
                if use_max_discount:
                    _raw_cost = detail.get("bestBenefitPrice")
                    new_cost = (
                        float(_raw_cost)
                        if (_raw_cost is not None and _raw_cost > 0)
                        else float(detail.get("salePrice") or 0)
                    )
                else:
                    new_cost = float(detail.get("salePrice") or 0)

                _sale_price = float(detail.get("salePrice") or 0)
                _original_price = float(detail.get("originalPrice") or 0) or _sale_price

                raw_cat = detail.get("category", "") or ""
                cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []

                detail_imgs = detail.get("detailImages") or []
                raw_detail_html = (
                    "\n".join(
                        f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                        for img in detail_imgs
                    )
                    if detail_imgs
                    else ""
                )

                product_data = _build_product_data(
                    detail,
                    item_id,
                    filter_id,
                    "SSG",
                    new_cost,
                    _sale_price,
                    _original_price,
                    raw_cat,
                    cat_parts,
                    raw_detail_html,
                )

                await svc.create_collected_product(product_data)
                total_saved += 1
                await repo.update_progress(
                    job.id, existing_count + total_saved, requested_count
                )

            except Exception as e:
                logger.warning(f"[SSG] 상세 수집 실패 {item_id}: {e}")

            await asyncio.sleep(1.0)  # 상품별 딜레이

        # ── 수집 완료 ──
        from datetime import datetime as _dt

        from sqlalchemy import update as _sa_upd

        from backend.domain.samba.collector.model import SambaSearchFilter as _SF

        actual_count = (
            await session.execute(
                select(_func.count()).where(CPModel.search_filter_id == filter_id)
            )
        ).scalar() or 0

        await session.execute(
            _sa_upd(_SF)
            .where(_SF.id == filter_id)
            .values(
                last_collected_at=_dt.now(UTC),
                requested_count=actual_count,
            )
        )
        await session.commit()

        await repo.complete_job(
            job.id,
            {
                "saved": total_saved,
                "message": f"SSG 수집 완료: {total_saved}개 저장 (총 {actual_count}개)",
            },
        )
```

- [ ] **Step 2: ruff 포맷 + 린트 실행**

```bash
cd backend
.venv/Scripts/python.exe -m ruff format backend/domain/samba/job/worker.py
.venv/Scripts/python.exe -m ruff check --fix backend/domain/samba/job/worker.py
```

Expected: 오류 없음

- [ ] **Step 3: 백엔드 서버 기동 확인**

터미널에서:
```bash
cd backend
uvicorn backend.main:app --reload --port 28080
```

Expected: 서버 정상 기동, import 오류 없음

- [ ] **Step 4: commit**

```bash
cd backend
git add backend/domain/samba/job/worker.py
git commit -m "SSG 배치 수집 — 50개 단위 분할·60초 대기 및 재수집 버그 수정"
```

---

## 테스트 방법

1. 상품수집 페이지에서 SSG 검색 URL로 그룹을 생성 (기존 100개 수집 완료 상태)
2. `요청` 수를 **200**으로 변경
3. `수집` 버튼 클릭
4. 수집 로그에서 확인:
   - `[SSG] 배치 1/3 완료 (50개 저장), 60초 대기 중...` 표시
   - 60초 후 다음 배치 진행
   - 최종 `[SSG] 수집 완료: 100개 저장` (기존 100 + 신규 100 = 총 200)
5. 수집/요청 숫자가 200으로 동기화 확인
