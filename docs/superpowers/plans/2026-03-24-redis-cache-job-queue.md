# Redis 캐시 + 작업 큐 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redis/메모리 캐시 레이어 + DB 기반 작업 큐로 API 응답 속도 개선 + 전송/수집 비동기화

**Architecture:** CacheService(Redis→메모리 폴백) + SambaJob 테이블 + 백그라운드 폴러 워커

**Tech Stack:** Python 3.12, FastAPI, aioredis, SQLModel, asyncio

**Spec:** `docs/superpowers/specs/2026-03-24-redis-cache-job-queue-design.md`

---

## Task 1: CacheService 생성

**Files:**
- Create: `backend/backend/domain/samba/cache/__init__.py`
- Create: `backend/backend/domain/samba/cache/service.py`
- Modify: `backend/backend/core/config.py` — `redis_url` 설정 추가

- [ ] **Step 1: 디렉토리 + CacheService 작성**

`cache/service.py`: get/set/delete/clear_pattern 메서드. Redis 연결 실패 시 인메모리 dict 폴백. TTL 지원.

- [ ] **Step 2: 싱글턴 인스턴스**

`cache/__init__.py`: `cache = CacheService(redis_url=settings.redis_url)`

- [ ] **Step 3: config.py에 redis_url 추가**

```python
redis_url: str | None = None  # 환경변수: REDIS_URL, None이면 인메모리
```

- [ ] **Step 4: main.py lifespan에 cache.connect() 추가**

- [ ] **Step 5: 커밋**

---

## Task 2: 주요 API에 캐시 적용

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/collector.py` — counts, category-tree, sites
- Modify: `backend/backend/domain/samba/proxy/smartstore.py` — 태그사전 검색

- [ ] **Step 1: /products/counts 캐싱 (TTL 30초)**

- [ ] **Step 2: /products/category-tree 캐싱 (TTL 5분)**

- [ ] **Step 3: /products/scroll의 sites 캐싱 (TTL 5분)**

- [ ] **Step 4: 태그사전 검색 캐싱 (TTL 10분)**

validate_tags에서 각 태그 검색 결과를 `tags:search:{keyword}` 키로 캐싱. 429 에러 대폭 감소.

- [ ] **Step 5: 캐시 무효화** — 상품 생성/삭제 시 `products:*` 패턴 삭제

- [ ] **Step 6: 커밋**

---

## Task 3: SambaJob 모델 + 마이그레이션

**Files:**
- Create: `backend/backend/domain/samba/job/__init__.py`
- Create: `backend/backend/domain/samba/job/model.py`
- Create: `backend/backend/domain/samba/job/repository.py`
- Create: `backend/backend/domain/samba/job/service.py`
- Create: alembic 마이그레이션

- [ ] **Step 1: SambaJob 모델**

id, tenant_id, job_type, status, payload(JSON), result(JSON), progress, total, current, error, timestamps

- [ ] **Step 2: Repository + Service**

CRUD + pick_next_pending + update_progress + complete + fail

- [ ] **Step 3: alembic 마이그레이션**

```bash
alembic revision --autogenerate -m "samba_jobs 테이블 생성"
alembic upgrade head
```

- [ ] **Step 4: 커밋**

---

## Task 4: Job API 라우터

**Files:**
- Create: `backend/backend/api/v1/routers/samba/job.py`
- Modify: `backend/backend/main.py` — 라우터 등록

- [ ] **Step 1: CRUD 엔드포인트**

```
POST /jobs         → 잡 생성 (즉시 응답)
GET  /jobs         → 잡 목록 (status 필터)
GET  /jobs/{id}    → 잡 상태 + 진행률
DELETE /jobs/{id}  → 잡 취소 (pending만)
```

- [ ] **Step 2: main.py에 라우터 등록**

- [ ] **Step 3: 커밋**

---

## Task 5: 백그라운드 워커

**Files:**
- Create: `backend/backend/domain/samba/job/worker.py`
- Modify: `backend/backend/main.py` — lifespan에 워커 시작

- [ ] **Step 1: JobWorker 클래스**

5초 간격 폴링. pending 잡 → running → 실행 → completed/failed. job_type별 분기.

- [ ] **Step 2: transmit 잡 실행기**

기존 `shipment_service.start_update()` 호출 래퍼. progress 업데이트.

- [ ] **Step 3: collect/refresh/ai_tag 잡 실행기 (스텁)**

나중에 구현. 지금은 "미구현" 반환.

- [ ] **Step 4: lifespan 연동**

```python
worker_task = asyncio.create_task(worker.start())
```

- [ ] **Step 5: 커밋**

---

## 구현 순서

```
Task 1: CacheService        ← 의존성 없음, 바로 시작
Task 2: API 캐시 적용       ← Task 1 완료 후
Task 3: SambaJob 모델       ← Task 1과 병렬 가능
Task 4: Job API 라우터      ← Task 3 완료 후
Task 5: 백그라운드 워커      ← Task 4 완료 후
```
