"""Application lifecycle hooks for SambaWave backend."""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

UTC = timezone.utc

from fastapi import FastAPI

from backend.core.config import settings
from backend.shutdown_state import clear_shutting_down, mark_shutting_down


SUPPORTED_PYTHON_VERSION = (3, 12, 3)


@dataclass
class WorkerRuntime:
    worker: object
    worker_task: asyncio.Task
    watchdog_task: asyncio.Task


async def _cancel_task(task: asyncio.Task | None, timeout: float = 5) -> None:
    if not task or task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except (asyncio.CancelledError, TimeoutError):
        pass


async def _event_loop_lag_monitor() -> None:
    """이벤트루프 블로킹 감시기 (진단용, 2026-06-26 추가).

    프로덕션은 단일 워커(gunicorn -w 1) 이벤트루프에서 API 요청과
    백그라운드 루프(오토튠/리컨실러/폴러/청소)를 함께 돌린다. 백그라운드
    루프가 동기 CPU·블로킹 호출로 루프를 점유하면 proxy-status 같은
    무부하 요청까지 멈춰 '백엔드 서버 연결 실패'가 뜬다.

    0.5초마다 실제 경과를 재서 기대보다 LOOP_LAG_THRESHOLD(기본 1.0초)
    이상 밀리면, 그 순간 실행 중이던 task 들의 스택을 로그에 박아 범인
    루프를 특정한다. 기존 코드를 건드리지 않는 순수 추가 진단 코드.

    LOOP_LAG_DEBUG=1 이면 asyncio 디버그 모드를 켜 'Executing <Handle>
    took X seconds' 로 정확한 범인 콜백까지 로깅한다(오버헤드 있어 opt-in).
    """
    import time as _time  # ruff local import 규칙 — 함수 내부 사용

    lag_logger = logging.getLogger("backend.loop-lag")
    interval = 0.5
    try:
        threshold = float(os.environ.get("LOOP_LAG_THRESHOLD", "1.0"))
    except ValueError:
        threshold = 1.0

    if os.environ.get("LOOP_LAG_DEBUG", "").lower() in ("1", "true", "yes"):
        try:
            loop = asyncio.get_running_loop()
            loop.set_debug(True)
            loop.slow_callback_duration = threshold
            lag_logger.warning(
                "[loop-lag] asyncio 디버그 모드 ON — slow_callback_duration=%.1fs "
                "(정확한 범인 콜백 로깅, 오버헤드 있음)",
                threshold,
            )
        except Exception as e:
            lag_logger.warning(f"[loop-lag] 디버그 모드 설정 실패(무시): {e}")

    lag_logger.info(
        "[loop-lag] 이벤트루프 블로킹 감시 시작 (interval=%.1fs, threshold=%.1fs)",
        interval,
        threshold,
    )

    while True:
        start = _time.monotonic()
        await asyncio.sleep(interval)
        lag = _time.monotonic() - start - interval
        if lag < threshold:
            continue
        try:
            tasks = [t for t in asyncio.all_tasks() if not t.done()]
            lines = []
            for t in tasks:
                stack = t.get_stack(limit=4)
                if not stack:
                    continue
                top = stack[-1]
                fname = top.f_code.co_filename.replace("\\", "/").split("/")[-1]
                lines.append(
                    f"  {t.get_name()} @ {fname}:{top.f_lineno} {top.f_code.co_name}"
                )
            lag_logger.warning(
                "[loop-lag] 이벤트루프 %.2f초 블로킹 — 활성 task=%d\n%s",
                lag,
                len(tasks),
                "\n".join(lines[:40]) or "  (스택 없음)",
            )
        except Exception as e:
            lag_logger.warning(f"[loop-lag] task 스택 덤프 실패(무시): {e}")


async def _connect_cache() -> None:
    from backend.domain.samba.cache import cache

    await cache.connect()


async def _disconnect_cache() -> None:
    from backend.domain.samba.cache import cache

    await cache.disconnect()


def _startup_logger() -> logging.Logger:
    logger = logging.getLogger("backend.startup")
    commit = os.environ.get("COMMIT_SHA", "unknown")
    logger.info("[startup] commit=%s", commit)
    return logger


async def _apply_startup_schema_fixes(logger: logging.Logger) -> None:
    """Bootstrap schema fixes — 각 SQL은 lock_timeout=5s / statement_timeout=30s 보호.

    2026-04-28 근본 수정: blue/green 배포 중 idle connection이 잡고 있는
    ACCESS EXCLUSIVE LOCK 또는 samba_order 등 큰 테이블 풀스캔으로 startup이
    3분 5초 hang하던 문제 → SET LOCAL timeout으로 fail-fast 처리.
    실패해도 다음 startup에서 재시도 (모든 SQL idempotent).
    """
    import time

    from sqlalchemy import text

    from backend.db.orm import get_write_session

    statements: list[tuple[str, str]] = [
        (
            "alter_order_paid_at",
            "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
        ),
        (
            "alter_search_filter_source_brand",
            "ALTER TABLE samba_search_filter "
            "ADD COLUMN IF NOT EXISTS source_brand_name TEXT",
        ),
        (
            "alter_return_customer_amount",
            "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_amount TEXT",
        ),
        (
            "alter_return_company_amount",
            "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS company_amount TEXT",
        ),
        (
            "alter_return_link_manual",
            "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS return_link_manual TEXT",
        ),
        (
            "alter_return_customer_phone_manual",
            "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS customer_phone_manual TEXT",
        ),
        (
            "alter_return_sourcing_order_no",
            "ALTER TABLE samba_return ADD COLUMN IF NOT EXISTS sourcing_order_no TEXT",
        ),
        # (제거됨) drop_market_account_sort_order — 컬럼 이미 드롭 완료(프로덕션 ABSENT 확인,
        # 2026-06-03 #331). no-op DROP도 매 startup ACCESS EXCLUSIVE 락을 잡아 고부하 시
        # 계정 테이블 읽기 큐를 최대 lock_timeout(5s)만큼 막으므로 statements에서 제거.
        # 반품 회수송장 컬럼 (롯데ON 회수조회 자동수집)
        (
            "alter_order_return_collect_courier",
            "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS "
            "return_collect_courier TEXT",
        ),
        (
            "alter_order_return_collect_tracking",
            "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS "
            "return_collect_tracking TEXT",
        ),
        (
            "alter_order_return_collect_at",
            "ALTER TABLE samba_order ADD COLUMN IF NOT EXISTS "
            "return_collect_at TIMESTAMP WITH TIME ZONE",
        ),
        (
            "alter_tsj_is_return",
            "ALTER TABLE samba_tracking_sync_job ADD COLUMN IF NOT EXISTS "
            "is_return BOOLEAN NOT NULL DEFAULT false",
        ),
        # CS 자동화(Tier 0) 컬럼 — 소규모 테이블이라 데드락 위험 없음
        (
            "alter_cs_intent",
            "ALTER TABLE samba_cs_inquiry ADD COLUMN IF NOT EXISTS intent TEXT",
        ),
        (
            "alter_cs_draft_reply",
            "ALTER TABLE samba_cs_inquiry ADD COLUMN IF NOT EXISTS draft_reply TEXT",
        ),
        (
            "alter_cs_draft_status",
            "ALTER TABLE samba_cs_inquiry ADD COLUMN IF NOT EXISTS draft_status TEXT "
            "NOT NULL DEFAULT 'none'",
        ),
        (
            "alter_cs_draft_confidence",
            "ALTER TABLE samba_cs_inquiry ADD COLUMN IF NOT EXISTS draft_confidence "
            "DOUBLE PRECISION",
        ),
        (
            "alter_cs_draft_source",
            "ALTER TABLE samba_cs_inquiry ADD COLUMN IF NOT EXISTS draft_source TEXT",
        ),
        (
            "alter_cs_drafted_at",
            "ALTER TABLE samba_cs_inquiry ADD COLUMN IF NOT EXISTS drafted_at "
            "TIMESTAMP WITH TIME ZONE",
        ),
        (
            "idx_cs_intent",
            "CREATE INDEX IF NOT EXISTS ix_samba_cs_inquiry_intent "
            "ON samba_cs_inquiry (intent)",
        ),
        (
            "idx_cs_draft_status",
            "CREATE INDEX IF NOT EXISTS ix_samba_cs_inquiry_draft_status "
            "ON samba_cs_inquiry (draft_status)",
        ),
        (
            "create_login_history",
            """
            CREATE TABLE IF NOT EXISTS samba_login_history (
                id VARCHAR(30) PRIMARY KEY,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                ip_address TEXT,
                region TEXT,
                user_agent TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
        ),
        (
            "idx_login_history_user_id",
            "CREATE INDEX IF NOT EXISTS ix_samba_login_history_user_id "
            "ON samba_login_history (user_id)",
        ),
        (
            "update_abcmart_shipping_fee",
            "UPDATE samba_collected_product "
            "SET sourcing_shipping_fee = 0 "
            "WHERE source_site = 'ABCmart' AND sourcing_shipping_fee > 0",
        ),
        (
            "delete_derived_orders",
            "DELETE FROM samba_order "
            "WHERE product_name LIKE '[사본-%' "
            "OR product_name LIKE '%★교환주문%'",
        ),
        # 롯데ON paid_at 오염 정리 — 이전 datetime.now() 폴백 버그로 paid_at이
        # sync 시각으로 통일 박힌 row를 NULL로 되돌려 백필 로직(order.py:3092-3129)이
        # 재채움할 수 있게 한다. idempotent (정상 데이터는 paid_at <= created_at).
        (
            "reset_lotteon_paid_at",
            "UPDATE samba_order SET paid_at = NULL "
            "WHERE source = 'lotteon' AND paid_at > created_at",
        ),
    ]

    total_start = time.time()
    ok = 0
    skipped = 0

    for label, sql in statements:
        stmt_start = time.time()
        try:
            # 각 SQL을 별도 트랜잭션으로 분리 — 한 SQL이 fail해도 다른 SQL 진행
            async with get_write_session() as session:
                # SET LOCAL은 현재 트랜잭션에만 적용됨 — 트랜잭션 자동 시작 후 적용
                await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                await session.execute(text("SET LOCAL statement_timeout = '30s'"))
                result = await session.execute(text(sql))
                await session.commit()
            elapsed = time.time() - stmt_start
            rowcount = getattr(result, "rowcount", -1)
            if rowcount is not None and rowcount >= 0:
                logger.info(
                    "[startup] [%s] OK (%.2fs) rows=%d", label, elapsed, rowcount
                )
            else:
                logger.info("[startup] [%s] OK (%.2fs)", label, elapsed)
            ok += 1
        except Exception as exc:
            elapsed = time.time() - stmt_start
            logger.warning(
                "[startup] [%s] SKIP (%.2fs) — %s: %s",
                label,
                elapsed,
                type(exc).__name__,
                exc,
            )
            skipped += 1

    logger.info(
        "[startup] schema bootstrap complete — ok=%d skip=%d total=%.2fs",
        ok,
        skipped,
        time.time() - total_start,
    )


async def _recover_running_jobs(logger: logging.Logger) -> None:
    max_transmit_attempts = 3

    from sqlalchemy import text

    from backend.db.orm import get_write_session

    for attempt_index in range(3):
        try:
            async with get_write_session() as session:
                resumed = await asyncio.wait_for(
                    session.execute(
                        text(
                            "UPDATE samba_jobs "
                            "SET status = 'pending', started_at = NULL, "
                            "attempt = COALESCE(attempt, 0) + 1 "
                            "WHERE status = 'running' AND job_type = 'transmit' "
                            f"AND COALESCE(attempt, 0) < {max_transmit_attempts}"
                        )
                    ),
                    timeout=8,
                )
                failed = await asyncio.wait_for(
                    session.execute(
                        text(
                            "UPDATE samba_jobs "
                            "SET status = 'failed', "
                            "error = 'OOM repeated restart (attempt >= 3) - manual check required', "
                            "completed_at = now() "
                            "WHERE status = 'running' AND job_type = 'transmit' "
                            f"AND COALESCE(attempt, 0) >= {max_transmit_attempts}"
                        )
                    ),
                    timeout=8,
                )
                reset = await asyncio.wait_for(
                    session.execute(
                        text(
                            "UPDATE samba_jobs "
                            "SET status = 'pending', started_at = NULL "
                            "WHERE status = 'running' AND job_type != 'transmit'"
                        )
                    ),
                    timeout=8,
                )
                # transmitting 상태로 10분 이상 멈춘 shipment → failed 처리
                # (전송 성공 후 프로세스 종료로 registered_accounts 미업데이트 상태 방지)
                shipment_stuck = await asyncio.wait_for(
                    session.execute(
                        text(
                            "UPDATE samba_shipment "
                            "SET status = 'failed', "
                            "    transmit_error = COALESCE(transmit_error, '{}')::jsonb "
                            '    || \'{"_stuck_recovery": "transmitting > 10min at restart"}\'::jsonb '
                            "WHERE status = 'transmitting' "
                            "AND updated_at < now() - interval '10 minutes'"
                        )
                    ),
                    timeout=8,
                )
                await session.commit()

            if resumed.rowcount:
                logger.info("[startup] resumed transmit jobs=%s", resumed.rowcount)
            if failed.rowcount:
                logger.info("[startup] failed stale transmit jobs=%s", failed.rowcount)
            if reset.rowcount:
                logger.info(
                    "[startup] reset stale non-transmit jobs=%s", reset.rowcount
                )
            if shipment_stuck.rowcount:
                logger.warning(
                    "[startup] transmitting stuck shipments → failed: %s건",
                    shipment_stuck.rowcount,
                )
            return
        except Exception as exc:
            logger.warning(
                "[startup] job recovery failed (%s/3): %s", attempt_index + 1, exc
            )
            if attempt_index < 2:
                await asyncio.sleep(2)


async def _recover_sourcing_jobs(logger: logging.Logger) -> None:
    """재시작 시 pending/dispatched 소싱 잡을 메모리 큐에 복원.

    dispatched 상태에서 5분 이상 응답 없는 잡은 expired 처리.
    최대 1,000건 cap — 그 이상이면 초과분은 무시(TTL로 자연 소멸).
    """
    import asyncio as _asyncio
    from datetime import datetime, timezone

    from sqlalchemy import update as sa_update
    from sqlmodel import select

    from backend.db.orm import get_write_session
    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
    from backend.domain.samba.sourcing_job.model import SambaSourcingJob

    _UTC = timezone.utc
    _STALE_SEC = 5 * 60
    _MAX_RECOVER = 1000

    try:
        async with get_write_session() as session:
            now = datetime.now(_UTC)
            stmt = (
                select(SambaSourcingJob)
                .where(
                    SambaSourcingJob.status.in_(["pending", "dispatched"]),
                    SambaSourcingJob.expires_at > now,
                )
                .limit(_MAX_RECOVER)
            )
            result = await asyncio.wait_for(session.execute(stmt), timeout=10)
            rows = result.scalars().all()

            stale_ids: list[str] = []
            recovered = 0
            for row in rows:
                if row.status == "dispatched" and row.dispatched_at:
                    elapsed = (
                        now - row.dispatched_at.replace(tzinfo=_UTC)
                    ).total_seconds()
                    if elapsed > _STALE_SEC:
                        stale_ids.append(row.request_id)
                        continue

                # DB pending 상태 유지 — get_next_job이 DB에서 직접 읽어감
                # resolve_job 호출 시 Future가 있으면 resolve 가능하도록 등록
                loop = _asyncio.get_event_loop()
                future = loop.create_future()
                SourcingQueue.resolvers[row.request_id] = future
                recovered += 1

            if stale_ids:
                await session.execute(
                    sa_update(SambaSourcingJob)
                    .where(SambaSourcingJob.request_id.in_(stale_ids))
                    .values(status="expired")
                )
                await session.commit()

            logger.info(
                "[startup] sourcing job 복원: recovered=%d, expired=%d",
                recovered,
                len(stale_ids),
            )
    except Exception as exc:
        logger.warning("[startup] sourcing job 복원 실패 (무시): %s", exc)


async def _start_worker_runtime() -> WorkerRuntime:
    from backend.domain.samba.job.worker import JobWorker

    watchdog_logger = logging.getLogger("backend.watchdog")
    worker = JobWorker()
    worker_task = asyncio.create_task(worker.start())

    async def worker_watchdog() -> None:
        nonlocal worker, worker_task
        while True:
            try:
                await asyncio.sleep(10)
                if not worker_task.done():
                    continue
                exc = worker_task.exception() if not worker_task.cancelled() else None
                watchdog_logger.error("[watchdog] worker stopped unexpectedly: %s", exc)
                await asyncio.sleep(3)
                worker = JobWorker()
                worker_task = asyncio.create_task(worker.start())
                watchdog_logger.info("[watchdog] worker restarted")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                watchdog_logger.error("[watchdog] watchdog error: %s", exc)
                await asyncio.sleep(10)

    watchdog_task = asyncio.create_task(worker_watchdog())
    return WorkerRuntime(
        worker=worker, worker_task=worker_task, watchdog_task=watchdog_task
    )


async def _start_autotune_if_enabled() -> None:
    from backend.api.v1.routers.samba.collector_autotune import (
        auto_start_if_enabled,
        restore_pc_allowed_sites_from_db,
        restore_pc_last_seen_from_db,
    )

    # PC 분담 매핑(_pc_allowed_sites)을 DB에서 복원 — 재시작 직후 두 PC가 동일 사이트를
    # 동시에 띄우는 중복 사이클 문제 방지. 복원 실패해도 폴링 헤더로 채워지므로 무시 가능.
    await restore_pc_allowed_sites_from_db()
    # 데몬 heartbeat 타임스탬프 복원 — API 재시작 후 다음 heartbeat 도달 전까지
    # '데몬끊김'으로 보이던 문제 해결 (persist_pc_last_seen_to_db 와 쌍).
    await restore_pc_last_seen_from_db()
    await auto_start_if_enabled()


_order_poller_task: asyncio.Task | None = None
_lottehome_qa_poller_task: asyncio.Task | None = None
_tetris_sync_task: asyncio.Task | None = None
_sourcing_job_cleanup_task: asyncio.Task | None = None
_tetris_sync_last_run: float = 0.0
_order_auto_sync_task: asyncio.Task | None = None
_order_auto_sync_last_run: float = 0.0
_reward_auto_task: asyncio.Task | None = None
_reward_auto_last_run: float = 0.0
_pc_sync_task: asyncio.Task | None = None
_pc_cleanup_task: asyncio.Task | None = None
_daemon_poll_watch_task: asyncio.Task | None = None


# 프록시 서버사이드로 직접 fetch 하는 오토튠 사이트 — 확장앱 폴링(브라우저 탭) 없이도
# 백엔드가 갱신 가능. 따라서 확장앱 auto-spawn 의 5분 폴링 가드를 면제한다(웨일 탭이
# 백그라운드 throttle / PC 절전으로 폴링 끊겨도 무신사 오토튠이 죽지 않게). 쿠키 만료
# 시 잘못된 비로그인가는 musinsa.py 비로그인 검출 → price_uncertain → 오토튠 cost 갱신/
# 전송 보류(2단 방어)로 차단되므로 가격 오염 위험 없음. [2026-06-30]
_SERVER_SIDE_AUTOTUNE_SITES = {"MUSINSA"}

# 좀비 코디 watchdog [2026-06-30] — 코디 task 는 살아있는데(`_is_pc_running`=True)
# stale-conn 무한재시도/hung await 로 사이클이 안 도는 좀비. pc-sync 의 spawn 가드가
# "이미 running" 으로 보고 안 갈아끼워 무신사가 영구 비활성화되던 잔여 구멍을 메운다.
# 진척 신호(site heartbeat 또는 spawn 시각)가 _ZOMBIE_COORD_TIMEOUT 초 넘게 정지면 강제 교체.
# [2026-06-30] 600초로 상향: 무신사 풀사이클이 전역 동시성 캡 영향으로 bulk+후처리 합쳐
# ~245초까지 느려지고 후처리 구간엔 site heartbeat 가 멈출 수 있어, 240초면 정상-느린
# 사이클을 좀비로 오판해 죽이고 flapping 유발. 600초(10분)면 정상 사이클엔 여유, 진짜
# hung(10분+ 완전 무진척)만 회수.
_ZOMBIE_COORD_TIMEOUT = 600.0
_pc_coord_spawned_at: dict[str, float] = {}


async def _pc_sync_loop() -> None:
    """매 10초 PC 분담 매핑 DB → in-memory 동기화 (worker 간 sync).

    Gunicorn 다중 worker 환경에서 UI POST 가 1개 worker among 갱신해 다른 worker 의
    잡 발행 시 stale 매핑 사용 → 잡 발행 skip 사고 차단. lifecycle background task.

    추가: 분담 박혀있는 데몬 dev autotune cycle 자동 spawn (2026-05-27).
    데몬은 UI 시작 안 거치므로 _pc_sync_loop 가 매 tick 마다 spawn 보장.
    """
    import asyncio as _asyncio

    import time as _time

    from backend.api.v1.routers.samba.collector_autotune import (  # noqa: F811
        _autotune_enabled_flag,
        _autotune_loop,
        _get_pc_event,
        _is_pc_running,
        _pc_allowed_sites,
        _pc_cycle_count,
        _pc_last_seen,
        _pc_main_task,
        _pc_restart_count,
        _pc_site_cycle_counts,
        _pc_site_empty_hits,
        _pc_site_heartbeats,
        _pc_site_last_ticks,
        _pc_site_tasks,
        persist_pc_last_seen_to_db,
        sync_pc_allowed_sites_from_db,
    )

    _lg = logging.getLogger("backend.pc-sync")
    _persist_counter = 0
    while True:
        try:
            await sync_pc_allowed_sites_from_db()
            _persist_counter += 1
            if _persist_counter >= 6:  # 10s × 6 = 60s 마다 heartbeat 타임스탬프 영속화
                _persist_counter = 0
                await persist_pc_last_seen_to_db()
            # 분담 박힌 데몬 dev autotune cycle 자동 spawn.
            # 사용자 PC 의 pc_allowed_sites 는 DAEMON_ONLY(SSG/ABC/LOTTEON) 사이트 strip
            # 되므로 데몬 cycle 없으면 4개 사이트 처리 자체가 안 됨.
            for _ddev, _dsites in list(_pc_allowed_sites.items()):
                if not _ddev.startswith("samba-daemon-"):
                    continue
                if not _dsites:
                    continue
                if _is_pc_running(_ddev):
                    continue
                _pc_cycle_count[_ddev] = 0
                _pc_restart_count[_ddev] = 0
                _ev = _get_pc_event(_ddev)
                _ev.set()
                _pc_main_task[_ddev] = _asyncio.create_task(
                    _autotune_loop(_ddev),
                    name=f"autotune-main-{_ddev[:8]}",
                )
                _lg.info(f"[pc-sync] 데몬 자동 spawn: {_ddev} sites={sorted(_dsites)}")
            # 확장앱 dev 자동 spawn — 글로벌 오토튠 ON + 분담 있음 + 최근 폴링(5분 내).
            # 체크박스 체크 + 오토튠 실행 중이면 배포/재시작 후 자동 재개 (데몬과 동일 UX).
            # 5분 폴링 가드: 꺼진 PC는 재시작 금지 (탭 중복 열림 방지).
            if _autotune_enabled_flag:
                _now_ts = _time.time()
                for _edev, _esites in list(_pc_allowed_sites.items()):
                    if _edev.startswith("samba-daemon-"):
                        continue
                    if not _esites:
                        continue
                    if _is_pc_running(_edev):
                        # 좀비 코디 watchdog — running 인데 _ZOMBIE_COORD_TIMEOUT 초+ 무진척
                        # (site heartbeat / spawn 시각 정지)이면 hung 좀비로 보고 강제 교체.
                        # 정상이면 그대로 둠(continue). 이 분기 없으면 hung 코디가 영구 비활성.
                        _zmain = _pc_main_task.get(_edev)
                        _zhbs = _pc_site_heartbeats.get(_edev) or {}
                        _zprog = max(
                            [_pc_coord_spawned_at.get(_edev, 0.0)]
                            + list(_zhbs.values())
                        )
                        if (
                            _zmain is not None
                            and not _zmain.done()
                            and _zprog
                            and (_now_ts - _zprog) > _ZOMBIE_COORD_TIMEOUT
                        ):
                            _lg.warning(
                                f"[pc-sync] 좀비 코디 강제 교체: {_edev} "
                                f"(무진척 {int(_now_ts - _zprog)}초, sites={sorted(_esites)})"
                            )
                            _zmain.cancel()
                            _pc_main_task.pop(_edev, None)
                            # hung site loop 취소 — 남아있으면 새 코디가 "이미 실행중"으로 보고 재spawn 스킵 (이슈 #576)
                            _stale_sites = _pc_site_tasks.get(_edev) or {}
                            for _stale_t in list(_stale_sites.values()):
                                if not _stale_t.done():
                                    _stale_t.cancel()
                            _pc_site_tasks[_edev] = {}
                            _pc_site_cycle_counts[_edev] = {}
                            _pc_site_last_ticks[_edev] = {}
                            _pc_site_empty_hits[_edev] = {}
                            _pc_site_heartbeats[_edev] = {}
                            # event 는 set 유지 — 아래 spawn 으로 폴스루해 새 코디 교체.
                        else:
                            continue
                    # 프록시 서버사이드 사이트(무신사)만 분담된 확장앱은 5분 폴링 가드 면제 —
                    # 백엔드가 폴링 없이 직접 갱신하므로 PC 절전/탭 throttle 에도 죽지 않게.
                    _all_server_side = all(
                        _s in _SERVER_SIDE_AUTOTUNE_SITES for _s in _esites
                    )
                    if not _all_server_side:
                        _last_poll = _pc_last_seen.get(_edev, 0)
                        if not _last_poll or (_now_ts - _last_poll) > 300:
                            continue
                    _pc_cycle_count[_edev] = 0
                    _pc_restart_count[_edev] = 0
                    _pc_coord_spawned_at[_edev] = _now_ts
                    _ev2 = _get_pc_event(_edev)
                    _ev2.set()
                    _pc_main_task[_edev] = _asyncio.create_task(
                        _autotune_loop(_edev),
                        name=f"autotune-main-{_edev[:8]}",
                    )
                    _lg.info(
                        f"[pc-sync] 확장앱 자동 spawn: {_edev} sites={sorted(_esites)}"
                    )
        except Exception as exc:
            _lg.warning(f"[lifecycle][pc-sync] 동기화 실패(무시): {exc}")
        await asyncio.sleep(10)


async def _pc_cleanup_loop() -> None:
    """매 60초 PC 분담 매핑 자동 cleanup — dead device + 빈 분담 제거.

    1) samba_extension_key 에서 active device_id 목록 조회 (revoked/expired 제외)
    2) autotune_pc_allowed_sites 에서 active_set 외 device 또는 빈 분담 dev 제거
    3) 변경 발생 시 DB UPDATE → 다음 sync_loop 가 in-memory 정리

    사용자가 데몬 삭제/PC 교체 시 옛 흔적 자동 정리 — 수동 SQL 부담 제거.
    """
    import json

    from backend.api.v1.routers.samba.proxy._helpers import _get_setting, _set_setting
    from backend.db.orm import get_read_session, get_write_session

    _lg = logging.getLogger("backend.pc-cleanup")
    while True:
        try:
            # 1) active device 목록
            async with get_read_session() as session:
                from sqlalchemy import text

                rows = await session.execute(
                    text(
                        "SELECT DISTINCT device_id FROM samba_extension_key "
                        "WHERE device_id IS NOT NULL AND revoked_at IS NULL "
                        "AND (expires_at IS NULL OR expires_at > now())"
                    )
                )
                active_set = {r[0] for r in rows.all() if r[0]}

                # 2) DB 분담 매핑 조회
                current = await _get_setting(session, "autotune_pc_allowed_sites")
            if not isinstance(current, dict):
                await asyncio.sleep(60)
                continue

            # 3) cleanup — active device 만 유지 (빈 분담 허용)
            # active key 면 사용자 체크박스 비어있는 상태도 정상 → 보존.
            # 옛/revoked device 만 제거.
            # samba-daemon-* 는 install-token 없는 자가빌드 케이스에서 extension_key 미등록
            # 상태로도 정상 동작 가능 — cleanup 보존 (2026-05-27 사용자 PC 사고).
            cleaned = {
                k: v
                for k, v in current.items()
                if (k in active_set or k.startswith("samba-daemon-"))
                and isinstance(v, list)
            }

            if cleaned != current:
                removed = sorted(set(current.keys()) - set(cleaned.keys()))
                async with get_write_session() as wsess:
                    await _set_setting(wsess, "autotune_pc_allowed_sites", cleaned)
                    await wsess.commit()
                _lg.info(
                    "[pc-cleanup] dead device 매핑 %d개 제거: %s",
                    len(removed),
                    removed[:5],
                )
        except Exception as exc:
            _lg.warning(f"[lifecycle][pc-cleanup] 실패(무시): {exc}")
            # unused 방지
            _ = json  # noqa: F841
        await asyncio.sleep(60)


async def _daemon_poll_watch_loop() -> None:
    """매 5분 — 데몬 폴링 끊김 감지 + 워룸 경고 이벤트 발행.

    samba-daemon- prefix dev 중 분담 있는데 10분(600s) 이상 폴링 없으면 알림.
    폴링 재개 시 알림 상태 해제.
    """
    import time

    from backend.api.v1.routers.samba.collector_autotune import (
        _pc_allowed_sites,
        _pc_last_seen,
    )

    _lg = logging.getLogger("backend.daemon-watch")
    _alerted: set[str] = set()

    while True:
        await asyncio.sleep(300)
        try:
            now = time.time()
            for dev, sites in list(_pc_allowed_sites.items()):
                if not dev.startswith("samba-daemon-"):
                    continue
                if not sites:
                    continue
                last = _pc_last_seen.get(dev, 0)
                elapsed = int(now - last) if last else None
                if (last == 0 or now - last > 600) and dev not in _alerted:
                    _alerted.add(dev)
                    _lg.warning(
                        "[daemon-watch] 폴링 끊김: dev=%s sites=%s last_seen_ago=%s",
                        dev,
                        sorted(sites),
                        elapsed,
                    )
                    try:
                        from backend.domain.samba.warroom.service import (
                            SambaMonitorService,
                        )
                        from backend.db.orm import get_write_session

                        async with get_write_session() as ws:
                            await SambaMonitorService(ws).emit(
                                "daemon_poll_stopped",
                                "warning",
                                summary=(
                                    f"데몬 폴링 끊김 — {dev[:12]}"
                                    f" ({', '.join(sorted(sites))}). 데몬 재가동 필요."
                                ),
                                detail={
                                    "device_id": dev,
                                    "sites": sorted(sites),
                                    "last_seen_ago": elapsed,
                                },
                            )
                            await ws.commit()
                    except Exception as _e:
                        _lg.warning(
                            "[daemon-watch] 워룸 이벤트 발행 실패(무시): %s", _e
                        )
                elif last and now - last <= 600 and dev in _alerted:
                    _alerted.discard(dev)
        except Exception as exc:
            _lg.warning("[daemon-watch] 감지 실패(무시): %s", exc)


async def _tetris_sync_loop() -> None:
    """테트리스 자동 sync 인터벌 루프 — 1분마다 설정 확인 후 조건 충족 시 전송 잡 생성."""
    global _tetris_sync_last_run
    import time

    _log = logging.getLogger("backend.lifecycle")
    while True:
        await asyncio.sleep(60)
        try:
            from backend.db.orm import get_read_session, get_write_session

            async with get_read_session() as rs:
                from backend.api.v1.routers.samba.proxy._helpers import _get_setting

                val = await _get_setting(rs, "tetris_sync_interval_hours")
                interval_hours = int(val) if val else 0

            if interval_hours <= 0:
                continue

            now = time.time()
            if now - _tetris_sync_last_run < interval_hours * 3600:
                continue

            _log.info(f"[테트리스 auto sync] 인터벌 {interval_hours}h 도달 — 시작")

            from sqlalchemy import text as _sa_text

            async with get_read_session() as rs2:
                rows = await rs2.execute(
                    _sa_text("SELECT DISTINCT tenant_id FROM samba_tetris_assignment")
                )
                tenant_ids: list[str | None] = [row[0] for row in rows.all()]

            # 레거시 블록(registered_accounts 기반) 처리는 tenant_id=None 레코드가 실제 존재할 때만
            # 강제 삽입 금지 — 멀티테넌트 환경에서 sync_all(None) 호출 시 transmit 잡이 tenant_id=None 으로
            # 생성되어 worker.list_by_tenant(None)→WHERE tenant_id IS NULL 배치 0건 → "스킵 (전송 대상 계정 없음)" (#252)

            from backend.domain.samba.tetris.repository import SambaTetrisRepository
            from backend.domain.samba.tetris.service import SambaTetrisService

            for tid in tenant_ids:
                try:
                    async with get_write_session() as ws:
                        svc = SambaTetrisService(SambaTetrisRepository(ws), ws)
                        result = await svc.sync_all(tid)
                    _log.info(f"[테트리스 auto sync] tenant={tid} {result}")
                except Exception as e:
                    _log.error(f"[테트리스 auto sync] tenant={tid} 오류: {e}")

            _tetris_sync_last_run = now

        except Exception as e:
            logging.getLogger("backend.lifecycle").error(
                f"[테트리스 sync 루프] 오류: {e}"
            )


async def _warmup_filter_tree_counts_cache(logger: logging.Logger) -> None:
    """서버 시작 시 소싱처별 필터 카운트를 백그라운드에서 미리 계산해 캐시에 저장.

    소싱처 클릭 시 즉시 응답 가능하도록 워밍업.
    실패해도 무시 — 사용자 클릭 시 정상 동작함.
    """
    try:
        from sqlalchemy import func, case, and_, literal, text as _text
        from sqlmodel import select

        _AI_TAGGED_JSONB = _text("'[\"__ai_tagged__\"]'::jsonb")
        _AI_IMAGE_JSONB = _text("'[\"__ai_image__\"]'::jsonb")

        from backend.db.orm import get_read_session
        from backend.domain.samba.cache import cache
        from backend.domain.samba.collector.model import (
            SambaCollectedProduct,
            SambaSearchFilter,
        )

        async with get_read_session() as session:
            # 소싱처 목록 조회
            site_rows = await session.execute(
                select(SambaSearchFilter.source_site)
                .where(
                    SambaSearchFilter.is_folder == False,  # noqa: E712
                    SambaSearchFilter.source_site.isnot(None),
                )
                .distinct()
            )
            source_sites = [r[0] for r in site_rows.all() if r[0]]

        for source_site in source_sites:
            cache_key = f"filters:tree:counts:{source_site}"
            try:
                async with get_read_session() as session:
                    leaf_rows = await session.execute(
                        select(SambaSearchFilter.id).where(
                            SambaSearchFilter.is_folder == False,  # noqa: E712
                            SambaSearchFilter.source_site == source_site,
                        )
                    )
                    leaf_ids = [r[0] for r in leaf_rows.all()]
                    if not leaf_ids:
                        continue

                    _CP = SambaCollectedProduct
                    from backend.api.v1.routers.samba.collector_common import (  # noqa: F811
                        has_registered_accounts as _has_reg,
                    )

                    count_stmt = (
                        select(
                            _CP.search_filter_id,
                            func.count().label("cnt"),
                            func.count(case((_has_reg(_CP), literal(1)))).label(
                                "market_registered"
                            ),
                            func.count(
                                case(
                                    (
                                        _CP.tags.op("@>")(_AI_TAGGED_JSONB),
                                        literal(1),
                                    )
                                )
                            ).label("ai_tagged"),
                            func.count(
                                case(
                                    (
                                        _CP.tags.op("@>")(_AI_IMAGE_JSONB),
                                        literal(1),
                                    )
                                )
                            ).label("ai_image"),
                            func.count(
                                case(
                                    (
                                        and_(
                                            _CP.tags.isnot(None),
                                            func.jsonb_typeof(_CP.tags) == "array",
                                            func.jsonb_array_length(_CP.tags) > 0,
                                        ),
                                        literal(1),
                                    )
                                )
                            ).label("tag_applied"),
                            func.count(
                                case((_CP.applied_policy_id.isnot(None), literal(1)))
                            ).label("policy_applied"),
                        )
                        .where(_CP.search_filter_id.in_(leaf_ids))
                        .group_by(_CP.search_filter_id)
                    )
                    count_result = await session.execute(count_stmt)
                    counts: dict[str, dict] = {}
                    for row in count_result.all():
                        counts[row[0]] = {
                            "collected_count": row[1],
                            "market_registered_count": row[2],
                            "ai_tagged_count": row[3],
                            "ai_image_count": row[4],
                            "tag_applied_count": row[5],
                            "policy_applied_count": row[6],
                        }
                    await cache.set(cache_key, counts, ttl=300)
                    logger.info(
                        "[startup] 필터 카운트 워밍업 완료: %s (%d leaf)",
                        source_site,
                        len(leaf_ids),
                    )
            except Exception as exc:
                logger.warning(
                    "[startup] 필터 카운트 워밍업 실패: %s — %s", source_site, exc
                )
    except Exception as exc:
        logger.warning("[startup] 필터 카운트 워밍업 전체 실패: %s", exc)


async def _warmup_tetris_board_cache(logger: logging.Logger) -> None:
    """서버 시작 시 테트리스 보드 캐시 백그라운드 워밍업.

    get_board() 쿼리는 60초 이상 소요되므로 첫 사용자 요청 전에 미리 실행해둔다.
    캐시 키가 tenant_id별로 분리되므로 None 외에 실제 tenant_id 전부를 워밍업한다.
    실패해도 무시 — 사용자가 재시도하면 정상 동작함.
    """
    try:
        from sqlalchemy import text as _sa_text

        from backend.db.orm import get_read_session
        from backend.domain.samba.tetris.repository import SambaTetrisRepository
        from backend.domain.samba.tetris.service import SambaTetrisService

        tenant_ids: list[Optional[str]] = [None]
        try:
            async with get_read_session() as rs:
                rows = await rs.execute(
                    _sa_text(
                        "SELECT DISTINCT tenant_id FROM samba_market_account "
                        "WHERE tenant_id IS NOT NULL"
                    )
                )
                for (tid,) in rows.all():
                    if tid:
                        tenant_ids.append(str(tid))
        except Exception as exc:
            logger.warning("[startup] 테트리스 워밍업 tenant 목록 조회 실패: %s", exc)

        for tid in tenant_ids:
            try:
                async with get_read_session() as session:
                    svc = SambaTetrisService(SambaTetrisRepository(session), session)
                    await svc.get_board(tenant_id=tid)
                logger.info("[startup] 테트리스 보드 캐시 워밍업 완료 tenant=%s", tid)
            except Exception as exc:
                logger.warning(
                    "[startup] 테트리스 보드 캐시 워밍업 실패 tenant=%s — %s", tid, exc
                )
    except Exception as exc:
        logger.warning("[startup] 테트리스 보드 캐시 워밍업 전체 실패: %s", exc)


async def _start_tetris_sync_scheduler() -> None:
    global _tetris_sync_task, _pc_sync_task, _pc_cleanup_task, _daemon_poll_watch_task

    _tetris_sync_task = asyncio.create_task(_tetris_sync_loop())
    _pc_sync_task = asyncio.create_task(_pc_sync_loop())
    _pc_cleanup_task = asyncio.create_task(_pc_cleanup_loop())
    _daemon_poll_watch_task = asyncio.create_task(_daemon_poll_watch_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 테트리스 sync + PC 분담 sync + cleanup + 데몬 폴링 감시 스케줄러 시작"
    )


async def _order_auto_sync_loop() -> None:
    """주문 자동수집 인터벌 루프 — 1분마다 설정 확인 후 조건 충족 시:
    1) order_sync 잡 생성 (전체 활성 계정, 최근 7일)
    2) 잡 완료 대기
    3) tracking_sync_bulk 호출 (미발송 송장 수집·전송)
    """
    global _order_auto_sync_last_run
    import time

    _log = logging.getLogger("backend.lifecycle")
    while True:
        await asyncio.sleep(60)
        try:
            from backend.db.orm import get_read_session, get_write_session

            async with get_read_session() as rs:
                from backend.api.v1.routers.samba.proxy._helpers import _get_setting

                val = await _get_setting(rs, "order_auto_sync_interval_minutes")
                try:
                    interval_min = int(val) if val is not None else 0
                except (TypeError, ValueError):
                    interval_min = 0

            if interval_min <= 0:
                continue

            now = time.time()
            if now - _order_auto_sync_last_run < interval_min * 60:
                continue

            _log.info(f"[주문 auto sync] 인터벌 {interval_min}분 도달 — 시작")

            # 1) 활성 마켓 계정 전체 ID 조회 후 order_sync 잡 생성
            from sqlalchemy import text as _sa_text
            from backend.domain.samba.job.model import JobStatus, SambaJob

            async with get_write_session() as ws:
                rows = await ws.execute(
                    _sa_text(
                        "SELECT id FROM samba_market_account WHERE is_active = TRUE"
                    )
                )
                account_ids = [row[0] for row in rows.all()]

                if not account_ids:
                    _log.info("[주문 auto sync] 활성 계정 없음 — 스킵")
                    _order_auto_sync_last_run = now
                    continue

                # 같은 tenant 동시 order_sync 1개 제한이 있으므로 중복 시 그대로 진행
                from sqlmodel import select, col

                active = (
                    (
                        await ws.execute(
                            select(SambaJob)
                            .where(
                                SambaJob.job_type == "order_sync",
                                col(SambaJob.status).in_(
                                    [JobStatus.PENDING, JobStatus.RUNNING]
                                ),
                                SambaJob.tenant_id.is_(None),
                            )
                            .order_by(SambaJob.created_at.desc())
                            .limit(1)
                        )
                    )
                    .scalars()
                    .first()
                )
                if active:
                    job_id = active.id
                    _log.info(f"[주문 auto sync] 기존 잡 재연결 {job_id}")
                else:
                    new_job = SambaJob(
                        job_type="order_sync",
                        status=JobStatus.PENDING,
                        payload={"days": 7, "account_ids": account_ids},
                    )
                    ws.add(new_job)
                    await ws.flush()
                    await ws.commit()
                    job_id = new_job.id
                    _log.info(f"[주문 auto sync] order_sync 잡 생성 {job_id}")

            # 1-b) CS 문의 동기화도 주문 자동수집에 연동 — 별도 30분 폴러가 아닌
            #      주문 자동수집 인터벌마다 cs_sync 잡을 함께 큐잉(중복 실행 방지 내장).
            #      [테넌트 격리] tenant_id=None 단일 잡은 ContextVar가 비어 전 테넌트
            #      마켓계정을 무차별 순회한다(데이터 누수 사고 원인). 활성 테넌트별로
            #      잡을 나눠 생성해야 각 잡이 자기 테넌트 계정만 동기화한다.
            try:
                from sqlmodel import select as _sel

                from backend.domain.samba.order.poller import _create_cs_sync_job
                from backend.domain.samba.tenant.model import SambaTenant

                async with get_write_session() as cs_ws:
                    _trows = await cs_ws.execute(
                        _sel(SambaTenant.id).where(
                            SambaTenant.is_active == True  # noqa: E712
                        )
                    )
                    _tids = [r[0] for r in _trows.all()]
                    if _tids:
                        for _tid in _tids:
                            await _create_cs_sync_job(cs_ws, tenant_id=_tid)
                    else:
                        # 싱글테넌트 모드: 활성 테넌트 없음 → tenant_id=None 잡으로 전체 계정 처리
                        await _create_cs_sync_job(cs_ws, tenant_id=None)
            except Exception as _cs_e:
                _log.warning(f"[주문 auto sync] cs_sync 잡 생성 실패: {_cs_e}")

            # 2) 잡 완료 대기 (최대 30분)
            deadline = time.time() + 30 * 60
            while time.time() < deadline:
                await asyncio.sleep(5)
                async with get_read_session() as rs2:
                    job = (
                        await rs2.execute(
                            _sa_text("SELECT status FROM samba_jobs WHERE id = :jid"),
                            {"jid": job_id},
                        )
                    ).first()
                    status = job[0] if job else None
                if status in ("completed", "failed", "cancelled"):
                    _log.info(f"[주문 auto sync] order_sync 잡 종료: {status}")
                    break

            # 2-b) 역마진(가격X)/재고없음(재고X) 자동 판정 + 상품갱신 + 메모 기록.
            #      자동주문수집 본 경로(이 루프)에서 sync 끝난 직후 실행.
            try:
                from backend.domain.samba.order.auto_issue_check import (
                    auto_check_order_issues,
                )

                _ai_summary = await auto_check_order_issues()
                _log.info(f"[주문 auto sync] 주문이슈 자동체크: {_ai_summary}")
            except Exception as _ai_e:
                _log.warning(f"[주문 auto sync] 주문이슈 자동체크 실패: {_ai_e}")

            # 3) 송장수집 큐 적재 + 결과를 order_sync 잡 result에 머지
            tracking_summary: dict = {}
            try:
                from backend.domain.samba.tracking_sync.service import (
                    enqueue_pending_orders,
                )

                ts_result = await enqueue_pending_orders(
                    tenant_id=None, limit=500, days=7, force=True
                )
                _log.info(f"[주문 auto sync] 송장수집 큐 적재 완료: {ts_result}")

                # 반품 회수송장 수집 (롯데ON) — 회수송장 미보유 반품주문 적재
                try:
                    from backend.domain.samba.tracking_sync.service import (
                        enqueue_return_pending,
                    )

                    rt_result = await enqueue_return_pending(limit=200)
                    _log.info(f"[주문 auto sync] 회수송장 큐 적재: {rt_result}")
                except Exception as rte:
                    _log.error(f"[주문 auto sync] 회수송장 큐 적재 오류: {rte}")
                tracking_summary = {
                    "success": bool(ts_result.get("success")),
                    "queued": int(ts_result.get("queued") or 0),
                    "skipped": int(ts_result.get("skipped") or 0),
                    "errors": (ts_result.get("errors") or [])[:5],
                    "job_ids_count": len(ts_result.get("job_ids") or []),
                    "ran_at": datetime.now(UTC).isoformat(),
                }
            except Exception as e:
                _log.error(f"[주문 auto sync] 송장수집 큐 적재 오류: {e}")
                tracking_summary = {
                    "success": False,
                    "queued": 0,
                    "skipped": 0,
                    "errors": [str(e)[:300]],
                    "job_ids_count": 0,
                    "ran_at": datetime.now(UTC).isoformat(),
                }

            # order_sync 잡의 result.tracking_sync 에 송장수집 요약 머지
            try:
                from sqlalchemy import text as _sa_text2

                async with get_write_session() as ms:
                    # result 컬럼은 JSON 타입 — jsonb로 캐스팅 후 머지하고 다시 json으로 캐스팅해 저장
                    # (COALESCE에서 json/jsonb 혼합 불가, json || jsonb 연산자도 없음)
                    await ms.execute(
                        _sa_text2(
                            "UPDATE samba_jobs "
                            "SET result = (COALESCE(result::jsonb, '{}'::jsonb) || "
                            "jsonb_build_object('tracking_sync', CAST(:ts AS jsonb)))::json "
                            "WHERE id = :jid"
                        ),
                        {"ts": json.dumps(tracking_summary), "jid": job_id},
                    )
                    await ms.commit()
            except Exception as me:
                _log.warning(f"[주문 auto sync] tracking_sync 결과 머지 실패: {me}")

            _order_auto_sync_last_run = now

        except Exception as e:
            logging.getLogger("backend.lifecycle").error(
                f"[주문 auto sync 루프] 오류: {e}"
            )


async def _start_order_auto_sync_scheduler() -> None:
    global _order_auto_sync_task

    _order_auto_sync_task = asyncio.create_task(_order_auto_sync_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 주문 auto sync 스케줄러 시작"
    )


async def _reward_auto_loop() -> None:
    """적립금 자동 적립 인터벌 루프 — 1분마다 설정 확인 후 인터벌 도달 시
    활성 소싱처 계정(MUSINSA/ABCmart) 전체에 reward 잡 적재.

    각 액션은 라우터의 `_enqueue_reward_for_account` 내부에서 24h 가드를 다시 체크하므로
    여기서는 인터벌 도달 여부만 판단한다.
    """
    global _reward_auto_last_run
    import time

    _log = logging.getLogger("backend.lifecycle")
    while True:
        await asyncio.sleep(60)
        try:
            from backend.api.v1.routers.samba.proxy._helpers import (
                _get_setting,
                _set_setting,
            )
            from backend.db.orm import get_read_session, get_write_session

            async with get_read_session() as rs:
                val = await _get_setting(rs, "reward_auto_run_interval_hours")
                try:
                    interval_h = int(val) if val is not None else 0
                except (TypeError, ValueError):
                    interval_h = 0

            if interval_h <= 0:
                continue

            now = time.time()
            if now - _reward_auto_last_run < interval_h * 3600:
                continue

            _log.info(f"[적립금 auto] 인터벌 {interval_h}시간 도달 — 시작")

            from backend.api.v1.routers.samba.sourcing_account import (
                _enqueue_reward_for_account,
            )
            from backend.domain.samba.sourcing_account.model import (
                SambaSourcingAccount,
            )
            from sqlmodel import select as _select

            async with get_read_session() as rs2:
                stmt = _select(SambaSourcingAccount).where(
                    SambaSourcingAccount.site_name.in_(  # type: ignore[attr-defined]
                        [
                            "MUSINSA",
                            "ABCmart",
                            "SSG",
                            "GSShop",
                            "LOTTEON",
                            "NAVERSTORE",
                            "KREAM",
                        ]
                    ),
                    SambaSourcingAccount.is_active == True,  # noqa: E712
                )
                rows = (await rs2.execute(stmt)).scalars().all()

            count = 0
            for a in rows:
                try:
                    enq = await _enqueue_reward_for_account(a)
                    count += sum(1 for e in enq if "request_id" in e)
                except Exception as ee:
                    _log.warning(f"[적립금 auto] 계정 처리 실패 {a.id}: {ee}")

            _log.info(f"[적립금 auto] 적재 완료: 잡 {count}건 ({len(rows)}개 계정)")

            # 마지막 실행 시각 저장 (페이지 표시용)
            from datetime import datetime as _dt, timezone as _tz

            try:
                async with get_write_session() as ws:
                    await _set_setting(
                        ws,
                        "reward_auto_run_last_at",
                        _dt.now(_tz.utc).isoformat(),
                    )
            except Exception as ee:
                _log.warning(f"[적립금 auto] last_at 저장 실패: {ee}")

            _reward_auto_last_run = now

        except Exception as e:
            _log.error(f"[적립금 auto 루프] 오류: {e}")


async def _start_reward_auto_scheduler() -> None:
    global _reward_auto_task
    _reward_auto_task = asyncio.create_task(_reward_auto_loop())
    logging.getLogger("backend.lifecycle").info("[lifecycle] 적립금 auto 스케줄러 시작")


async def _start_order_poller() -> None:
    global _order_poller_task
    from backend.domain.samba.order.poller import start_order_poller

    _order_poller_task = asyncio.create_task(start_order_poller())
    logging.getLogger("backend.lifecycle").info("[lifecycle] 주문 폴러 시작")


async def _start_lottehome_qa_poller() -> None:
    global _lottehome_qa_poller_task
    from backend.domain.samba.order.lottehome_qa_poller import start_lottehome_qa_poller

    _lottehome_qa_poller_task = asyncio.create_task(start_lottehome_qa_poller())
    logging.getLogger("backend.lifecycle").info("[lifecycle] 롯데홈 QA 폴러 시작")


async def _sourcing_job_cleanup_loop() -> None:
    """1분 주기 소싱 잡 만료 청소 + 7일 이전 레코드 삭제."""
    from sqlalchemy import text

    from backend.db.orm import get_write_session
    from backend.shutdown_state import is_shutting_down

    _log = logging.getLogger("backend.lifecycle")
    while not is_shutting_down():
        await asyncio.sleep(60)
        if is_shutting_down():
            break
        # (2026-05-27) 단일 트랜잭션 분해: UPDATE + DELETE 한 번에 잡으면 hot 테이블
        # samba_sourcing_job 락 17s 보유 → write pool 핫스팟. 각 쿼리별 세션 분리해
        # 트랜잭션 짧게.
        _expired_n = 0
        _deleted_n = 0
        try:
            async with get_write_session() as session:
                expired = await session.execute(
                    text(
                        "UPDATE samba_sourcing_job SET status = 'expired' "
                        "WHERE expires_at < now() AND status IN ('pending', 'dispatched')"
                    )
                )
                await session.commit()
                _expired_n = expired.rowcount or 0
        except Exception as exc:
            _log.warning("[sourcing-cleanup] expired UPDATE 실패 (무시): %s", exc)
        try:
            async with get_write_session() as session:
                deleted = await session.execute(
                    text(
                        "DELETE FROM samba_sourcing_job "
                        "WHERE status IN ('completed', 'failed', 'expired') "
                        "AND created_at < now() - interval '7 days'"
                    )
                )
                await session.commit()
                _deleted_n = deleted.rowcount or 0
        except Exception as exc:
            _log.warning("[sourcing-cleanup] 7일 DELETE 실패 (무시): %s", exc)
        # transmit / autotune_transmit 잡 청소:
        # 테트리스·오토튠이 매 sync 마다 대량 생성 → 종료 잡 수만 건 누적 → bloat + 목록 렉.
        # 활성(pending/running)은 절대 건드리지 않음.
        #  ① transmit 종료 잡: 7일↑ 삭제
        #  ② tetris_sync 출처 transmit: 3일↑ 삭제 (churn 다발)
        #  ③ autotune_transmit 종료 잡: 1일↑ 삭제 (#459 — 고볼륨 transient sync)
        _tx_old_deleted = 0
        _tetris_job_deleted = 0
        _autotune_tx_deleted = 0
        try:
            async with get_write_session() as session:
                txdel = await session.execute(
                    text(
                        "DELETE FROM samba_jobs "
                        "WHERE job_type = 'transmit' "
                        "AND status IN ('completed', 'failed', 'cancelled') "
                        "AND created_at < now() - interval '7 days'"
                    )
                )
                await session.commit()
                _tx_old_deleted = txdel.rowcount or 0
        except Exception as exc:
            _log.warning("[sourcing-cleanup] transmit 7일 DELETE 실패 (무시): %s", exc)
        try:
            async with get_write_session() as session:
                tdel = await session.execute(
                    text(
                        "DELETE FROM samba_jobs "
                        "WHERE job_type = 'transmit' "
                        "AND status IN ('completed', 'failed', 'cancelled') "
                        "AND payload->>'origin' = 'tetris_sync' "
                        "AND created_at < now() - interval '3 days'"
                    )
                )
                await session.commit()
                _tetris_job_deleted = tdel.rowcount or 0
        except Exception as exc:
            _log.warning(
                "[sourcing-cleanup] 테트리스 transmit 잡 DELETE 실패 (무시): %s", exc
            )
        try:
            async with get_write_session() as session:
                atdel = await session.execute(
                    text(
                        "DELETE FROM samba_jobs "
                        "WHERE job_type = 'autotune_transmit' "
                        "AND status IN ('completed', 'failed', 'cancelled') "
                        "AND created_at < now() - interval '1 day'"
                    )
                )
                await session.commit()
                _autotune_tx_deleted = atdel.rowcount or 0
        except Exception as exc:
            _log.warning(
                "[sourcing-cleanup] autotune_transmit 1일 DELETE 실패 (무시): %s", exc
            )
        if (
            _expired_n
            or _deleted_n
            or _tx_old_deleted
            or _tetris_job_deleted
            or _autotune_tx_deleted
        ):
            _log.info(
                "[sourcing-cleanup] expired=%d deleted=%d transmit_7d=%d tetris_3d=%d autotune_1d=%d",
                _expired_n,
                _deleted_n,
                _tx_old_deleted,
                _tetris_job_deleted,
                _autotune_tx_deleted,
            )


async def _start_sourcing_job_cleanup() -> None:
    global _sourcing_job_cleanup_task
    _sourcing_job_cleanup_task = asyncio.create_task(_sourcing_job_cleanup_loop())
    logging.getLogger("backend.lifecycle").info("[lifecycle] 소싱 잡 청소 워커 시작")


_lotteon_ghost_reconciler_task: asyncio.Task | None = None
_elevenst_ghost_reconciler_task: asyncio.Task | None = None


async def _start_elevenst_ghost_reconciler() -> None:
    """11번가 prdNo 누락 매핑 일일 자동 감지 잡 — 24시간 주기."""
    global _elevenst_ghost_reconciler_task
    from backend.domain.samba.proxy.elevenst_ghost_reconciler import (
        ghost_reconciler_loop,
    )

    _elevenst_ghost_reconciler_task = asyncio.create_task(ghost_reconciler_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 11번가 prdNo 누락 reconciler 시작"
    )


# 컨테이너 재시작 후 filters 캐시 cold → 첫 호출 100초 → 프론트 fetch 타임아웃 →
# 체크박스 빈 채로 뜨던 문제. startup 시 백그라운드로 미리 워밍업.
async def _warmup_filters_cache() -> None:
    """autotune_get_filters 캐시 백그라운드 워밍업 (2026-05-25, 사용자 요청).

    + warroom dashboard 캐시도 같이 워밍업 — 페이지 첫 진입 cold start 83초 블로킹 차단.
    """
    _log = logging.getLogger("backend.lifecycle")
    try:
        from backend.api.v1.routers.samba.collector_autotune import autotune_get_filters

        await autotune_get_filters()
        _log.info("[lifecycle] filters 캐시 워밍업 완료")
    except Exception as exc:
        _log.warning("[lifecycle] filters 캐시 워밍업 실패(무시): %s", exc)

    # warroom dashboard 캐시 — 사용자 첫 진입 시 빈 구조 대신 실제 데이터 즉시 노출
    try:
        from backend.domain.samba.warroom.service import SambaMonitorService
        from backend.db.orm import get_read_session

        async with get_read_session() as sess:
            svc = SambaMonitorService(sess)
            await svc._compute_dashboard_now()
        _log.info("[lifecycle] warroom dashboard 캐시 워밍업 완료")
    except Exception as exc:
        _log.warning("[lifecycle] warroom dashboard 캐시 워밍업 실패(무시): %s", exc)


_filters_warmup_task: asyncio.Task | None = None


async def _start_filters_warmup() -> None:
    """startup 직후 filters 캐시 채움 — 첫 사용자 fetch 타임아웃 방지."""
    global _filters_warmup_task
    _filters_warmup_task = asyncio.create_task(_warmup_filters_cache())


_tracking_dispatch_sweep_task: asyncio.Task | None = None


async def _start_tracking_dispatch_sweep() -> None:
    """비-playauto 정체 송장(SCRAPED/DISPATCH_FAILED) 자동 재전송 sweep — 5분 주기.

    auto_dispatch가 수집 시점 1회 놓쳐 정체된 잡을 주기적으로 재전송 → 수동 전송 제거.
    """
    global _tracking_dispatch_sweep_task
    from backend.domain.samba.tracking_sync.service import dispatch_pending_sweep_loop

    _tracking_dispatch_sweep_task = asyncio.create_task(
        dispatch_pending_sweep_loop(300)
    )
    logging.getLogger("backend.lifecycle").info("[lifecycle] 송장 dispatch sweep 시작")


async def _start_lotteon_ghost_reconciler() -> None:
    """롯데ON 유령상품 일일 자동 감지 잡 — 24시간 주기."""
    global _lotteon_ghost_reconciler_task
    from backend.domain.samba.proxy.lotteon.ghost_reconciler import (
        ghost_reconciler_loop,
    )

    _lotteon_ghost_reconciler_task = asyncio.create_task(ghost_reconciler_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 롯데ON 유령상품 reconciler 시작"
    )


_ssg_status_reconciler_task: asyncio.Task | None = None


async def _start_ssg_status_reconciler() -> None:
    """SSG 반려/영구판매중지 상품 잔존 일일 자동 감지 잡 — 24시간 주기 (issue #308)."""
    global _ssg_status_reconciler_task
    from backend.domain.samba.proxy.ssg_status_reconciler import (
        status_reconciler_loop,
    )

    _ssg_status_reconciler_task = asyncio.create_task(status_reconciler_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] SSG 반려/판매중지 잔존 reconciler 시작"
    )


_coupang_pid_reconciler_task: asyncio.Task | None = None


async def _start_coupang_pid_reconciler() -> None:
    """쿠팡 노출상품ID(productId) 백필 reconciler — 30분 주기.

    등록 직후 productId 가 null 인 임시저장 상태의 상품을 주기적으로 재조회하여
    노출ID/옵션ID 가 발급되면 DB 에 채워 vp/products URL 이 정상 동작하게 함.
    """
    global _coupang_pid_reconciler_task
    from backend.domain.samba.proxy.coupang_pid_reconciler import pid_reconciler_loop

    _coupang_pid_reconciler_task = asyncio.create_task(pid_reconciler_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 쿠팡 노출ID 백필 reconciler 시작"
    )


_smartstore_ghost_reconciler_task: asyncio.Task | None = None


async def _start_smartstore_ghost_reconciler() -> None:
    """스마트스토어 유령상품 일일 자동 감지·정리 잡 — 24시간 주기."""
    global _smartstore_ghost_reconciler_task
    from backend.domain.samba.proxy.smartstore_ghost_reconciler import (
        ghost_reconciler_loop,
    )

    _smartstore_ghost_reconciler_task = asyncio.create_task(ghost_reconciler_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 스마트스토어 유령상품 reconciler 시작"
    )


_coupang_ghost_reconciler_task: asyncio.Task | None = None
_esmplus_ghost_reconciler_task: asyncio.Task | None = None
_soldout_cleanup_task: asyncio.Task | None = None


async def _soldout_cleanup_loop() -> None:
    """품절 잔존 상품 마켓삭제 재시도 루프 — 10분마다.

    sale_status='sold_out'인데 registered_accounts가 남아있는 상품을
    오토튠 사이클·배치 실행 여부와 무관하게 주기적으로 마켓 삭제.
    배포/재시작으로 오토튠 배치가 실행되지 못한 경우도 커버.
    """
    _log = logging.getLogger("backend.lifecycle")
    while True:
        await asyncio.sleep(600)  # 10분 대기 후 실행
        try:
            from sqlmodel import select
            from sqlalchemy import String, cast
            from sqlalchemy.dialects.postgresql import JSONB
            from backend.db.orm import get_write_session
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as _CP,
            )
            from backend.domain.samba.account.model import SambaMarketAccount
            from backend.domain.samba.shipment.dispatcher import delete_from_market

            # market_cond 조건과 동일
            async with get_write_session() as session:
                stmt = (
                    select(_CP)
                    .where(
                        _CP.sale_status == "sold_out",
                        _CP.lock_delete.is_not(True),
                        _CP.registered_accounts.isnot(None),
                        _CP.registered_accounts.op("!=")(cast("null", JSONB)),
                        _CP.registered_accounts.op("!=")(cast("[]", JSONB)),
                        _CP.market_product_nos.isnot(None),
                        cast(_CP.market_product_nos, String) != "null",
                        cast(_CP.market_product_nos, String) != "{}",
                    )
                    .limit(100)
                )
                result = await session.exec(stmt)
                products = result.all()

            if not products:
                continue

            _log.info("[soldout-cleanup] 품절 잔존 재시도: %d건", len(products))

            # 계정 캐시 로드
            all_acc_ids: set[str] = set()
            for p in products:
                if p.registered_accounts:
                    all_acc_ids.update(p.registered_accounts)

            acc_cache: dict[str, object] = {}
            if all_acc_ids:
                async with get_write_session() as session:
                    acc_stmt = select(SambaMarketAccount).where(
                        SambaMarketAccount.id.in_(list(all_acc_ids))
                    )
                    acc_result = await session.exec(acc_stmt)
                    for a in acc_result.all():
                        acc_cache[a.id] = a

            # 상품별 마켓 삭제 시도
            for sp in products:
                sp_reg = list(sp.registered_accounts or [])
                sp_mnos = dict(sp.market_product_nos or {})
                ok_ids: list[str] = []

                for acc_id in sp_reg:
                    acc = acc_cache.get(acc_id)
                    if not acc:
                        continue
                    m_type = acc.market_type
                    if m_type in ("smartstore",):
                        pno = sp_mnos.get(f"{acc_id}_origin", "") or sp_mnos.get(
                            acc_id, ""
                        )
                    elif m_type in ("gmarket", "auction"):
                        pno = sp_mnos.get(f"{acc_id}_master") or sp_mnos.get(acc_id, "")
                    else:
                        pno = sp_mnos.get(acc_id, "")
                    if isinstance(pno, dict):
                        pno = ""

                    pd = {
                        **{
                            k: v
                            for k, v in sp.__dict__.items()
                            if not k.startswith("_")
                        },
                        "market_product_no": {m_type: pno},
                    }
                    try:
                        async with get_write_session() as del_session:
                            dr = await delete_from_market(
                                del_session, m_type, pd, account=acc
                            )
                            await del_session.commit()
                        if dr.get("success") and not dr.get("soldout_fallback"):
                            ok_ids.append(acc_id)
                            _log.info(
                                "[soldout-cleanup] 삭제 완료: %s → %s(%s)",
                                (sp.name or sp.id)[:30],
                                acc.market_name,
                                acc.seller_id or "-",
                            )
                        else:
                            _log.warning(
                                "[soldout-cleanup] 삭제 실패: %s → %s: %s",
                                (sp.name or sp.id)[:30],
                                acc.market_name,
                                dr.get("message", "")[:100],
                            )
                    except Exception as del_e:
                        _log.error(
                            "[soldout-cleanup] 삭제 오류: %s → %s: %s",
                            (sp.name or sp.id)[:30],
                            m_type,
                            del_e,
                        )

                if ok_ids:
                    new_regs = [a for a in sp_reg if a not in ok_ids]
                    async with get_write_session() as upd_session:
                        upd_sp = await upd_session.get(_CP, sp.id)
                        if upd_sp:
                            upd_sp.registered_accounts = new_regs if new_regs else None
                            if not new_regs:
                                upd_sp.market_product_nos = None
                            upd_session.add(upd_sp)
                            await upd_session.commit()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.getLogger("backend.lifecycle").error(
                "[soldout-cleanup] 루프 오류: %s", e
            )


async def _start_soldout_cleanup() -> None:
    """품절 잔존 마켓삭제 재시도 루프 시작."""
    global _soldout_cleanup_task

    _soldout_cleanup_task = asyncio.create_task(_soldout_cleanup_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 품절 잔존 마켓삭제 재시도 루프 시작 (10분 주기)"
    )


async def _start_coupang_ghost_reconciler() -> None:
    """쿠팡 유령상품 일일 자동 감지·정리 잡 — 24시간 주기."""
    global _coupang_ghost_reconciler_task
    from backend.domain.samba.proxy.coupang_ghost_reconciler import (
        ghost_reconciler_loop,
    )

    _coupang_ghost_reconciler_task = asyncio.create_task(ghost_reconciler_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 쿠팡 유령상품 reconciler 시작"
    )


async def _start_esmplus_ghost_reconciler() -> None:
    """ESMPlus(지마켓/옥션) 유령상품 일일 자동 감지 잡 — 24시간 주기."""
    global _esmplus_ghost_reconciler_task
    from backend.domain.samba.proxy.esmplus_ghost_reconciler import (
        ghost_reconciler_loop,
    )

    _esmplus_ghost_reconciler_task = asyncio.create_task(ghost_reconciler_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] ESMPlus 유령상품 reconciler 시작"
    )


def _validate_startup_settings() -> None:
    if sys.version_info[:3] != SUPPORTED_PYTHON_VERSION:
        current = ".".join(str(part) for part in sys.version_info[:3])
        expected = ".".join(str(part) for part in SUPPORTED_PYTHON_VERSION)
        raise RuntimeError(
            "Unsupported Python runtime. "
            f"Expected {expected}, got {current}. "
            "Use backend/.venv or the production Docker image runtime."
        )

    if settings.mock_auth_enabled and settings.environment == "production":
        raise RuntimeError(
            "CRITICAL: Mock authentication cannot be enabled in production. "
            "Set MOCK_AUTH_ENABLED=false or ENVIRONMENT to non-production value."
        )

    if settings.mock_auth_enabled:
        logging.warning(
            "Mock authentication is ENABLED. This should only be used for development/testing."
        )

    # PlayAuto proxy 미설정 경고 — GCP/클라우드 환경에서 직접 연결 불가
    try:
        import os as _os

        from backend.domain.samba.collector.refresher import get_transmit_proxy_url

        _playauto_env = _os.environ.get("PLAYAUTO_PROXY_URL", "").strip()
        _transmit_proxy = (get_transmit_proxy_url() or "").strip()
        if not _playauto_env and not _transmit_proxy:
            logging.getLogger("backend.startup").warning(
                "[startup] PlayAuto 전송 프록시 미설정 — GCP/클라우드 환경에서 PlayAuto 호스트 직접 도달 불가. "
                "settings > 프록시/IP 설정에서 전송(transmit) 용도 국내 ISP 정적 IP 프록시를 등록하세요."
            )
    except Exception:
        pass

    secret_bytes = (settings.jwt_secret_key or "").encode("utf-8")
    if len(secret_bytes) < 32:
        raise RuntimeError(
            "CRITICAL: JWT_SECRET_KEY 가 32바이트 미만입니다. "
            "HS256 알고리즘은 최소 256비트(32바이트) 시크릿이 필요합니다. "
            f"현재 길이: {len(secret_bytes)}바이트. "
            "권고: `python -c 'import secrets; print(secrets.token_urlsafe(48))'` 로 재생성."
        )


async def _stop_autotune_and_refreshers() -> None:
    from backend.api.v1.routers.samba.collector_autotune import (
        _pc_running,
        _pc_site_tasks,
        _pc_main_task,
    )
    from backend.domain.samba.collector.refresher import request_bulk_cancel_all

    # 모든 PC 인스턴스 중지 신호
    for ev in list(_pc_running.values()):
        ev.clear()
    request_bulk_cancel_all()

    # 모든 PC의 소싱처 태스크 취소
    all_site_tasks: list = []
    for site_tasks in _pc_site_tasks.values():
        all_site_tasks.extend(site_tasks.values())
        site_tasks.clear()
    for task in all_site_tasks:
        task.cancel()
    if all_site_tasks:
        await asyncio.gather(*all_site_tasks, return_exceptions=True)

    # 모든 PC의 메인 코디네이터 태스크 취소
    for main_task in list(_pc_main_task.values()):
        await _cancel_task(main_task)
    _pc_main_task.clear()


async def _shutdown_worker_runtime(runtime: WorkerRuntime) -> None:
    shutdown_logger = logging.getLogger("backend.shutdown")

    await _cancel_task(runtime.watchdog_task)
    try:
        await runtime.worker.graceful_stop(timeout=30)
    except Exception as exc:
        shutdown_logger.error("[shutdown] graceful_stop failed: %s", exc)
        runtime.worker.stop()
    await _cancel_task(runtime.worker_task)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown validation."""
    clear_shutting_down()
    app.state.is_shutting_down = False

    await _connect_cache()
    startup_logger = _startup_logger()
    await _apply_startup_schema_fixes(startup_logger)

    # 자동 발주취소 트리거 등록 — SambaOrder.status 변경 감지 → cancel_order 잡 자동 발행
    try:
        from backend.domain.samba.order.model import _register_auto_cancel_trigger

        _register_auto_cancel_trigger()
        startup_logger.info("[startup] 자동 발주취소 트리거 등록 완료")
    except Exception as e:
        startup_logger.warning(f"[startup] 자동 발주취소 트리거 등록 실패: {e}")
    asyncio.create_task(_warmup_tetris_board_cache(startup_logger))
    asyncio.create_task(_warmup_filter_tree_counts_cache(startup_logger))

    # DB 풀 모니터 로거 — 30초 주기로 풀 사용률 INFO/WARN 로깅
    try:
        from backend.db.pool_monitor import pool_status_logger_loop

        app.state._pool_monitor_task = asyncio.create_task(pool_status_logger_loop())
    except Exception as e:
        startup_logger.warning(f"[startup] DB 풀 모니터 로거 시작 실패: {e}")

    # 이벤트루프 블로킹 감시기 — '백엔드 서버 연결 실패' 범인 루프 색출용 (진단)
    try:
        app.state._loop_lag_task = asyncio.create_task(_event_loop_lag_monitor())
    except Exception as e:
        startup_logger.warning(f"[startup] 이벤트루프 lag 감시기 시작 실패: {e}")

    # DB 프록시 캐시를 워커/오토튠 시작 전에 프라임한다.
    # async 컨텍스트에서는 _get_cached_proxies 가 백그라운드 태스크만 예약하므로,
    # 프라임 없이는 첫 호출 시 빈 목록이 반환되어 프록시 없이 직접 트래픽이 나감.
    try:
        from backend.domain.samba.collector.refresher import refresh_db_proxy_cache

        await refresh_db_proxy_cache()
    except Exception as e:
        startup_logger.warning(f"[startup] DB 프록시 캐시 프라임 실패: {e}")

    # VM 마이그레이션 병행 운영 지원 — API 전용 모드:
    # DISABLE_BACKGROUND_WORKERS=1 이면 JobWorker/오토튠/주문폴러를 시작하지 않는다.
    # 두 인스턴스가 동일 DB에 연결된 동안 백그라운드 작업 중복 실행을 방지한다.
    import os

    _disable_bg = os.environ.get("DISABLE_BACKGROUND_WORKERS", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # 프로세스 분리 (process-split-design): PROCESS_ROLE=worker 면 전송 전용 워커.
    # JobWorker(WORKER_ONLY_TYPES=transmit,order_sync)만 기동하고 오토튠 루프·데몬
    # 엔드포인트·리컨실러는 띄우지 않는다(이들은 API 프로세스 A 가 담당).
    # in-memory Future/오토튠 상태 결합 때문에 A 에만 둬야 함.
    _process_role = os.environ.get("PROCESS_ROLE", "api").strip().lower()

    if _disable_bg:
        startup_logger.warning(
            "[startup] DISABLE_BACKGROUND_WORKERS=1 — "
            "JobWorker/오토튠/주문폴러를 비활성화한다 (API 전용 모드)"
        )
        worker_runtime = WorkerRuntime(
            worker=None, worker_task=None, watchdog_task=None
        )
    elif _process_role == "worker":
        startup_logger.warning(
            "[startup] PROCESS_ROLE=worker — 전송 전용 워커 모드. "
            "JobWorker 만 기동(오토튠/리컨실러/주문폴러 비활성)"
        )
        # 전송 잡 boot 복구 후 JobWorker 만 기동. 수집/소싱 복구는 A 가 담당.
        await _recover_running_jobs(startup_logger)
        # 데몬 레지스트리 read-only 미러 — daemon-only source(SSG/ABC/LOTTEON) 전송 시
        # owner 해석(_resolve_job_owner → pick_daemon_owner)이 _pc_allowed_sites /
        # _pc_last_seen 을 참조하므로 워커도 복원 필요. write / autotune spawn 안 함.
        from backend.api.v1.routers.samba.collector_autotune import (  # noqa: F811
            restore_pc_allowed_sites_from_db,
            restore_pc_last_seen_from_db,
            sync_pc_allowed_sites_from_db,
        )

        await restore_pc_allowed_sites_from_db()
        await restore_pc_last_seen_from_db()

        async def _pc_sync_loop_worker() -> None:
            """워커 전용 데몬 레지스트리 15s 주기 sync (read-only, autotune spawn 없음)."""
            _wlg = logging.getLogger("backend.pc-sync-worker")
            while True:
                try:
                    await sync_pc_allowed_sites_from_db()
                    await restore_pc_last_seen_from_db()
                except Exception as _e:
                    _wlg.warning(f"[pc-sync-worker] sync 실패(무시): {_e}")
                await asyncio.sleep(15)

        asyncio.create_task(_pc_sync_loop_worker(), name="pc-sync-worker")
        worker_runtime = await _start_worker_runtime()
    elif _process_role == "reconciler":
        # 유지보수 루프 전용 프로세스(C) — A(api) 이벤트루프 과부하(단일 워커 굶김 →
        # HTTP 503) 분리용. 고스트 리컨실러/송장sweep/soldout 정리 등 주기적 DB+마켓
        # 유지보수 루프만 단일 인스턴스로 기동한다. JobWorker/오토튠/폴러는 A 담당.
        startup_logger.warning(
            "[startup] PROCESS_ROLE=reconciler — 유지보수 루프 전용 모드. "
            "(고스트 리컨실러/송장sweep/soldout 정리만 기동, JobWorker/오토튠 비활성)"
        )
        # 데몬 레지스트리 read-only 미러 — 송장sweep/soldout 정리가 daemon-only
        # source(SSG/ABC/LOTTEON) 전송 시 owner 해석(pick_daemon_owner)에 필요.
        # write/autotune spawn 은 하지 않는다(worker 모드와 동일 패턴).
        from backend.api.v1.routers.samba.collector_autotune import (  # noqa: F811
            restore_pc_allowed_sites_from_db,
            restore_pc_last_seen_from_db,
            sync_pc_allowed_sites_from_db,
        )

        await restore_pc_allowed_sites_from_db()
        await restore_pc_last_seen_from_db()

        async def _pc_sync_loop_reconciler() -> None:
            """reconciler 전용 데몬 레지스트리 15s 주기 sync (read-only)."""
            _rlg = logging.getLogger("backend.pc-sync-reconciler")
            while True:
                try:
                    await sync_pc_allowed_sites_from_db()
                    await restore_pc_last_seen_from_db()
                except Exception as _e:
                    _rlg.warning(f"[pc-sync-reconciler] sync 실패(무시): {_e}")
                await asyncio.sleep(15)

        asyncio.create_task(_pc_sync_loop_reconciler(), name="pc-sync-reconciler")

        await _start_sourcing_job_cleanup()
        await _start_lotteon_ghost_reconciler()
        await _start_elevenst_ghost_reconciler()
        await _start_coupang_pid_reconciler()
        await _start_ssg_status_reconciler()
        await _start_smartstore_ghost_reconciler()
        await _start_coupang_ghost_reconciler()
        await _start_esmplus_ghost_reconciler()
        await _start_tracking_dispatch_sweep()
        await _start_soldout_cleanup()
        worker_runtime = WorkerRuntime(
            worker=None, worker_task=None, watchdog_task=None
        )
    else:
        await _recover_running_jobs(startup_logger)
        await _recover_sourcing_jobs(startup_logger)
        worker_runtime = await _start_worker_runtime()
        await _start_autotune_if_enabled()
        await _start_order_poller()
        await _start_lottehome_qa_poller()
        await _start_tetris_sync_scheduler()
        await _start_order_auto_sync_scheduler()
        await _start_reward_auto_scheduler()
        await _start_filters_warmup()
        # 아래 유지보수 루프들은 PROCESS_ROLE=reconciler 프로세스(C)로 분리됨
        # (단일 워커 이벤트루프 과부하 → HTTP 503 방지). 여기서 기동하지 않는다.
        #   _start_sourcing_job_cleanup / _start_lotteon_ghost_reconciler /
        #   _start_elevenst_ghost_reconciler / _start_coupang_pid_reconciler /
        #   _start_ssg_status_reconciler / _start_smartstore_ghost_reconciler /
        #   _start_coupang_ghost_reconciler / _start_tracking_dispatch_sweep /
        #   _start_soldout_cleanup
    _validate_startup_settings()

    try:
        yield
    finally:
        shutdown_logger = logging.getLogger("backend.shutdown")
        shutdown_logger.info("[shutdown] graceful shutdown starting")
        app.state.is_shutting_down = True
        mark_shutting_down()
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
        from backend.domain.samba.proxy.kream import KreamClient

        SourcingQueue.cancel_all()
        KreamClient.cancel_all()
        await _stop_autotune_and_refreshers()
        await _cancel_task(_order_poller_task)
        await _cancel_task(_lottehome_qa_poller_task)
        await _cancel_task(_tetris_sync_task)
        await _cancel_task(_order_auto_sync_task)
        await _cancel_task(_reward_auto_task)
        await _cancel_task(_lotteon_ghost_reconciler_task)
        await _cancel_task(_elevenst_ghost_reconciler_task)
        await _cancel_task(_smartstore_ghost_reconciler_task)
        await _cancel_task(_coupang_ghost_reconciler_task)
        await _cancel_task(_tracking_dispatch_sweep_task)
        await _cancel_task(_soldout_cleanup_task)
        await _shutdown_worker_runtime(worker_runtime)
        await _cancel_task(getattr(app.state, "_pool_monitor_task", None))
        await _disconnect_cache()
        shutdown_logger.info("[shutdown] graceful shutdown complete")
