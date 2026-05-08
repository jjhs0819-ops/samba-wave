# 잡 큐 영속화 — 단계별 마이그레이션 plan

## Context

`backend/domain/samba/proxy/sourcing_queue.py` 의 `SourcingQueue.queue` / `resolvers` /
`_pc_force_stop_set` / `_autotune_running_event` 는 모두 단일 프로세스 메모리에 존재한다.
백엔드 재시작(배포·OOM·crash)이 발생하면:

- 미완료 `Future` 가 GC 되어 확장앱이 결과를 POST 해도 `resolve_job()` → `False` 반환
- 결과 적재 코드는 호출되지 않음 → 수집된 상품 데이터 영구 유실
- 확장앱 입장에서 로그상 "정상 응답 받음(success: ok=False)" 이라 침묵 실패

이 plan 은 점진적·하위호환 전환을 통해 운영 중단·롤백 위험 최소화하는 것을 목표로 한다.

---

## 진행 현황 (2026-05-09)

- ✅ **단계 0** — 모델 + 마이그레이션 추가만 (이번 PR)
  - `backend/domain/samba/sourcing_job/model.py` SambaSourcingJob 정의
  - `alembic/versions/zzzzzzzz_add_samba_sourcing_job.py` 빈 테이블 + 인덱스만 생성
  - 기존 SourcingQueue 동작 미변경, 새 테이블은 비어있음 → 운영 영향 0
- ⏳ **단계 1** — Dual-write (메모리+DB 동시 기록)
- ⏳ **단계 2** — 재시작 시 DB 복원 (pending/dispatched 잡 자동 재큐잉)
- ⏳ **단계 3** — Read 단일화 (DB 만 사용, 메모리는 캐시)
- ⏳ **단계 4** — 만료/통계 백그라운드 워커

---

## 테이블 스키마 (확정)

```sql
CREATE TABLE samba_sourcing_job (
    request_id      VARCHAR(64) PRIMARY KEY,
    site            VARCHAR(32) NOT NULL,
    job_type        VARCHAR(32) NOT NULL DEFAULT 'detail',
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    owner_device_id VARCHAR(64),
    payload         JSON,
    result          JSON,
    error           TEXT,
    attempt         INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    dispatched_at   TIMESTAMP WITH TIME ZONE,
    completed_at    TIMESTAMP WITH TIME ZONE,
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL
);
```

상태 전이: `pending → dispatched(확장앱이 받아감) → completed | failed | expired`

---

## 단계 1 — Dual-write

**변경 범위:** `proxy/sourcing_queue.py`

- `SourcingQueue.add_*_job()` 호출 시 메모리 큐 enqueue 후 **즉시** DB INSERT
- `get_next_job()` 시 DB UPDATE status='dispatched', dispatched_at=now()
- `resolve_job()` 시 DB UPDATE status='completed', result=..., completed_at=now()
- DB write 실패는 경고 로그만 남기고 메모리 흐름 우선 유지 (역호환 우선)

**검증:**
- 로컬 PG 에서 잡 발행→처리 1건 끝까지 흘려 DB 레코드 정합성 확인
- pg_stat_statements 로 추가 쿼리 부하 측정 (목표: 잡당 +3 쿼리, <2ms)
- 배포 직후 모니터링 — 잡 처리 성공률 변화 없는지 5분 주기 확인

---

## 단계 2 — 재시작 시 복원

**변경 범위:** `lifecycle.py` startup 훅

- 백엔드 시작 시 `SELECT * FROM samba_sourcing_job WHERE status IN ('pending', 'dispatched') AND expires_at > now()` 로딩
- 메모리 큐에 재 enqueue (Future 새로 생성 → `resolvers` 등록)
- `dispatched` 상태로 5분 이상 응답 없는 잡은 `status='expired'` 로 마감

**위험:**
- startup 쿼리 시간 길어지면 health check timeout
- 인덱스 `ix_samba_sourcing_job_active_expiry` 활용해 < 100ms 보장
- 복원 잡 수가 많으면 메모리 폭증 — 1000 건 cap

---

## 단계 3 — Read 단일화

**변경 범위:** worker / poller 가 DB 만 조회

- `SourcingQueue.queue` 리스트 제거. DB SELECT FOR UPDATE SKIP LOCKED 로 dequeue
- 멀티 워커 동시성 안전 (Postgres 행 락)
- 메모리는 핫 캐시로만 사용

---

## 단계 4 — 백그라운드 워커

**변경 범위:** 새 lifecycle task

- 1분 주기로 만료 잡 청소 (`expires_at < now() AND status IN ('pending', 'dispatched')`)
- 7일 이전 completed 잡 archive 또는 delete (운영 정책 결정)
- 통계: 일별 잡 처리량/실패율 노출

---

## 롤백 계획

- 단계 1~3 모두 환경변수 `SOURCING_JOB_DB_PERSIST=false` 로 즉시 비활성 가능하도록 feature flag 도입
- DB 테이블은 그대로 두고 코드 경로만 메모리 fallback
- 단계 0 (이번 PR) 은 코드 변경이 없어 롤백 불필요

---

## 진행 권장 시점

- 단계 1: 사용자 작업 시간 中 (롤백 가능)
- 단계 2: 평일 오전 (재시작 후 모니터링 가능 시간대)
- 단계 3·4: 단계 1·2 가 1주 이상 안정 검증된 후

새벽·주말 진행 금지 (장애 대응 인력 부재).
