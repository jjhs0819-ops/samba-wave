# Redis 캐시 + 작업 큐 설계

> Redis 캐시 레이어 (폴백: 인메모리) + DB 기반 작업 큐 (SambaJob)

## 목표

1. **캐시**: 자주 조회하는 데이터를 Redis/메모리에 캐싱하여 DB 부하 감소
2. **작업 큐**: 전송/수집/갱신을 백그라운드 잡으로 비동기 실행, 프론트에서 진행률 확인

## 설계 결정

| 항목 | 선택 | 이유 |
|------|------|------|
| Redis 환경 | 로컬 Docker 먼저, 프로덕션은 나중에 | 코드에 Redis 연동 + 폴백으로 배포 없이 개발 |
| 작업 큐 | DB 테이블 기반 자체 구현 | 외부 의존성 0, 기존 전송 코드 재사용 |

---

## 1. Redis 캐시 레이어

### CacheService

```python
# backend/domain/samba/cache/service.py

class CacheService:
    """Redis 우선, 연결 실패 시 인메모리 dict 폴백."""

    def __init__(self, redis_url: str | None = None):
        self._redis = None  # aioredis 클라이언트
        self._memory: dict[str, tuple[Any, float]] = {}  # {key: (value, expires_at)}
        self._redis_url = redis_url

    async def connect(self):
        """Redis 연결 시도. 실패해도 예외 없음 — 메모리 폴백."""
        if self._redis_url:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(self._redis_url)
                await self._redis.ping()
            except Exception:
                self._redis = None

    async def get(self, key: str) -> Any | None:
        """캐시 조회. Redis → 메모리 → None."""
        # Redis 시도
        if self._redis:
            try:
                data = await self._redis.get(key)
                if data:
                    return json.loads(data)
            except Exception:
                pass
        # 메모리 폴백
        if key in self._memory:
            value, expires_at = self._memory[key]
            if time.time() < expires_at:
                return value
            del self._memory[key]
        return None

    async def set(self, key: str, value: Any, ttl: int = 30):
        """캐시 저장. ttl 단위: 초."""
        # Redis 시도
        if self._redis:
            try:
                await self._redis.set(key, json.dumps(value, default=str), ex=ttl)
                return
            except Exception:
                pass
        # 메모리 폴백
        self._memory[key] = (value, time.time() + ttl)

    async def delete(self, key: str):
        """캐시 삭제."""
        if self._redis:
            try:
                await self._redis.delete(key)
            except Exception:
                pass
        self._memory.pop(key, None)

    async def clear_pattern(self, pattern: str):
        """패턴 매칭 키 삭제. 예: 'products:*'"""
        if self._redis:
            try:
                keys = await self._redis.keys(pattern)
                if keys:
                    await self._redis.delete(*keys)
            except Exception:
                pass
        # 메모리: 패턴 매칭
        prefix = pattern.replace("*", "")
        to_delete = [k for k in self._memory if k.startswith(prefix)]
        for k in to_delete:
            del self._memory[k]
```

### 싱글턴 인스턴스

```python
# backend/domain/samba/cache/__init__.py

from backend.core.config import settings

cache = CacheService(redis_url=getattr(settings, "redis_url", None))
```

### 캐싱 대상

| 키 패턴 | TTL | 데이터 | 무효화 시점 |
|---------|-----|--------|------------|
| `products:counts` | 30초 | {total, registered, policy_applied, sold_out} | 상품 CRUD 시 |
| `products:category-tree` | 5분 | [{source_site, category, count}] | 상품 수집 시 |
| `accounts:active` | 1분 | SambaMarketAccount[] | 계정 수정 시 |
| `tags:search:{keyword}` | 10분 | 태그 검색 결과 | - (자연 만료) |
| `products:sites` | 5분 | [source_site 목록] | 상품 수집 시 |

### 적용 패턴 (라우터에서)

```python
@router.get("/products/counts")
async def product_counts(session):
    from backend.domain.samba.cache import cache
    cached = await cache.get("products:counts")
    if cached:
        return cached
    # DB 조회
    result = {...}
    await cache.set("products:counts", result, ttl=30)
    return result
```

### 설정

```python
# backend/core/config.py에 추가
redis_url: str | None = None  # 환경변수: REDIS_URL
# 예: redis://localhost:6379/0
# None이면 인메모리 폴백
```

---

## 2. 작업 큐 (SambaJob)

### 모델

```python
# backend/domain/samba/job/model.py

class SambaJob(SQLModel, table=True):
    __tablename__ = "samba_jobs"

    id: str  # job_{ULID}
    tenant_id: Optional[str]  # 테넌트 격리
    job_type: str  # "transmit" | "collect" | "refresh" | "ai_tag"
    status: str = "pending"  # pending → running → completed | failed
    payload: dict  # 잡 파라미터 (product_ids, account_ids 등)
    result: Optional[dict] = None  # 완료 결과
    progress: int = 0  # 0~100
    total: int = 0  # 전체 건수
    current: int = 0  # 처리 건수
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

### API 라우터

```python
# backend/api/v1/routers/samba/job.py

POST /jobs              → 잡 생성 (즉시 응답, job_id 반환)
GET  /jobs              → 잡 목록 (tenant별)
GET  /jobs/{id}         → 잡 상태 + 진행률
DELETE /jobs/{id}       → 잡 취소 (pending만)
```

### 잡 생성 예시

```python
# POST /jobs
{
    "job_type": "transmit",
    "payload": {
        "product_ids": ["cp_xxx", "cp_yyy"],
        "update_items": ["image", "description"],
        "target_account_ids": ["ma_aaa"]
    }
}
# → 200 {"id": "job_xxx", "status": "pending"}
```

### 백그라운드 워커 (폴러)

```python
# backend/domain/samba/job/worker.py

class JobWorker:
    """백그라운드 잡 실행기. FastAPI lifespan에서 시작."""

    POLL_INTERVAL = 5  # 초

    async def start(self):
        """무한 루프: pending 잡 조회 → 실행."""
        while True:
            job = await self._pick_next_job()
            if job:
                await self._execute(job)
            else:
                await asyncio.sleep(self.POLL_INTERVAL)

    async def _pick_next_job(self) -> SambaJob | None:
        """가장 오래된 pending 잡 1개를 running으로 변경 후 반환."""
        # SELECT ... WHERE status='pending' ORDER BY created_at LIMIT 1
        # UPDATE status='running', started_at=now()

    async def _execute(self, job: SambaJob):
        """잡 타입별 실행. 기존 서비스 메서드 호출."""
        try:
            if job.job_type == "transmit":
                await self._run_transmit(job)
            elif job.job_type == "collect":
                await self._run_collect(job)
            elif job.job_type == "refresh":
                await self._run_refresh(job)
            elif job.job_type == "ai_tag":
                await self._run_ai_tag(job)
        except Exception as e:
            await self._fail_job(job, str(e))

    async def _run_transmit(self, job: SambaJob):
        """기존 shipment_service.start_update() 래퍼."""
        payload = job.payload
        product_ids = payload["product_ids"]
        total = len(product_ids)
        # 상품별 순차 전송 + progress 업데이트
        for i, pid in enumerate(product_ids):
            await shipment_service.transmit_product(pid, ...)
            await self._update_progress(job, current=i+1, total=total)
        await self._complete_job(job)
```

### FastAPI lifespan 연동

```python
# backend/main.py

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시
    from backend.domain.samba.cache import cache
    await cache.connect()

    from backend.domain.samba.job.worker import JobWorker
    worker = JobWorker()
    worker_task = asyncio.create_task(worker.start())

    yield

    # 종료 시
    worker_task.cancel()
```

### 프론트 연동 (폴링)

```typescript
// 잡 생성
const { id } = await jobApi.create({ job_type: 'transmit', payload: {...} })

// 진행률 폴링 (2초 간격)
const poll = setInterval(async () => {
    const job = await jobApi.get(id)
    setProgress(job.progress)
    if (job.status === 'completed' || job.status === 'failed') {
        clearInterval(poll)
    }
}, 2000)
```

---

## 변경 영향 범위

| 파일 | 변경 |
|------|------|
| `cache/` (신규) | CacheService + 싱글턴 |
| `job/` (신규) | SambaJob 모델 + 서비스 + 워커 |
| `job.py` 라우터 (신규) | CRUD API |
| `config.py` | redis_url 설정 추가 |
| `main.py` | lifespan에 cache.connect + worker 시작 |
| `collector.py` | counts, category-tree에 캐시 적용 |
| `proxy.py` | 태그사전 검색에 캐시 적용 |
| alembic | samba_jobs 테이블 마이그레이션 |

## 전환 전략

1. Redis 없이 인메모리 캐시로 시작 (즉시 효과)
2. 잡 워커를 FastAPI lifespan에 내장 (별도 프로세스 불필요)
3. 프론트에서 기존 전송 API와 잡 API 병행 (점진적 전환)
4. 프로덕션에 Redis 추가 시 `REDIS_URL` 환경변수만 설정
