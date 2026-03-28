# 수집 백그라운드 Job 전환 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** SSE 스트림 기반 수집을 Job 큐 방식으로 전환하여 타임아웃 없이 대량 수집 지원

**Architecture:** 기존 SambaJob 모델/워커 활용. collect 스텁을 실제 수집 로직으로 교체. 프론트는 SSE EventSource 대신 폴링.

**Tech Stack:** FastAPI, SambaJob 모델, asyncio, React 폴링

---

### Task 1: 워커 collect 구현

**Files:**
- Modify: `backend/backend/domain/samba/job/worker.py`

- [ ] **Step 1:** `_run_collect()` 메서드 구현 — `collector_collection.py`의 `_stream_musinsa` 로직 이식

payload:
```json
{
  "filter_id": "sf_xxx",
  "source_site": "MUSINSA"
}
```

핵심 로직:
1. filter 조회 → keyword, requested_count 추출
2. 기존 수집 수 확인 → remaining 계산
3. 검색 → 필터링 → 상세수집 → 저장 (기존 로직 동일)
4. `repo.update_progress(job_id, current, total)` 호출로 진행률 갱신
5. 완료 시 정책 자동 적용

- [ ] **Step 2:** `_poll_once`에서 `collect` 타입 연결

```python
elif job.job_type == "collect":
    await self._run_collect(job, repo, session)
```

- [ ] **Step 3:** 커밋

---

### Task 2: 수집 API 변경

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/collector_collection.py`

- [ ] **Step 1:** `POST /collect-filter/{filter_id}` 엔드포인트 변경

기존: SSE StreamingResponse 반환
변경: Job 생성 → `{"job_id": "job_xxx"}` 즉시 응답

```python
@router.post("/collect-filter/{filter_id}")
async def collect_filter(filter_id: str, session = Depends(...)):
    # filter 존재 확인
    # Job 생성: job_type="collect", payload={"filter_id": filter_id, "source_site": ...}
    # return {"job_id": job.id}
```

- [ ] **Step 2:** 기존 SSE 스트림 코드 제거 (또는 별도 엔드포인트로 보존)

- [ ] **Step 3:** 커밋

---

### Task 3: 프론트 폴링 전환

**Files:**
- Modify: `frontend/src/app/samba/collector/page.tsx`

- [ ] **Step 1:** `handleCollectGroups` 변경

기존: fetch → SSE reader 루프
변경:
1. `POST /collect-filter/{id}` → `{job_id}` 수신
2. 3초 간격 폴링: `GET /jobs/{job_id}` → `{status, current, total, progress}`
3. `status === "completed"` 또는 `"failed"` 시 종료
4. 로그: `[그룹명] [current/total] 수집 중...`

- [ ] **Step 2:** 중단 처리 — `DELETE /jobs/{job_id}` (pending 상태 취소)

- [ ] **Step 3:** 커밋 + 푸시
