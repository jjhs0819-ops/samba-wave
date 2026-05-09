"""Application lifecycle hooks for SambaWave backend."""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass

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
            "drop_market_account_sort_order",
            "ALTER TABLE samba_market_account DROP COLUMN IF EXISTS sort_order",
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
                await session.commit()

            if resumed.rowcount:
                logger.info("[startup] resumed transmit jobs=%s", resumed.rowcount)
            if failed.rowcount:
                logger.info("[startup] failed stale transmit jobs=%s", failed.rowcount)
            if reset.rowcount:
                logger.info(
                    "[startup] reset stale non-transmit jobs=%s", reset.rowcount
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

    from backend.db.orm import get_write_sessionmaker
    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
    from backend.domain.samba.sourcing_job.model import SambaSourcingJob

    _UTC = timezone.utc
    _STALE_SEC = 5 * 60
    _MAX_RECOVER = 1000

    try:
        sessionmaker = get_write_sessionmaker()
        async with sessionmaker() as session:
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
    from backend.api.v1.routers.samba.collector_autotune import auto_start_if_enabled

    await auto_start_if_enabled()


_order_poller_task: asyncio.Task | None = None
_lottehome_qa_poller_task: asyncio.Task | None = None
_tetris_sync_task: asyncio.Task | None = None
_tetris_sync_last_run: float = 0.0


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

            # 배치가 없어도 레거시 블록(registered_accounts 기반)을 처리하기 위해
            # tenant_id=None 항상 포함 (멀티테넌트 환경에서도 None 레코드가 존재)
            if None not in tenant_ids:
                tenant_ids.insert(0, None)

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
    실패해도 무시 — 사용자가 재시도하면 정상 동작함.
    """
    try:
        from backend.db.orm import get_read_session
        from backend.domain.samba.tetris.repository import SambaTetrisRepository
        from backend.domain.samba.tetris.service import SambaTetrisService

        async with get_read_session() as session:
            svc = SambaTetrisService(SambaTetrisRepository(session), session)
            await svc.get_board(tenant_id=None)
            logger.info("[startup] 테트리스 보드 캐시 워밍업 완료")
    except Exception as exc:
        logger.warning("[startup] 테트리스 보드 캐시 워밍업 실패: %s", exc)


async def _start_tetris_sync_scheduler() -> None:
    global _tetris_sync_task

    _tetris_sync_task = asyncio.create_task(_tetris_sync_loop())
    logging.getLogger("backend.lifecycle").info(
        "[lifecycle] 테트리스 sync 스케줄러 시작"
    )


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
        _autotune_running_event,
        _site_tasks,
        _autotune_task,
    )
    from backend.domain.samba.collector.refresher import request_bulk_cancel_all

    _autotune_running_event.clear()
    request_bulk_cancel_all()
    site_tasks = list(_site_tasks.values())
    _site_tasks.clear()
    for task in site_tasks:
        task.cancel()
    if site_tasks:
        await asyncio.gather(*site_tasks, return_exceptions=True)
    await _cancel_task(_autotune_task)


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
    asyncio.create_task(_warmup_tetris_board_cache(startup_logger))
    asyncio.create_task(_warmup_filter_tree_counts_cache(startup_logger))

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

    if _disable_bg:
        startup_logger.warning(
            "[startup] DISABLE_BACKGROUND_WORKERS=1 — "
            "JobWorker/오토튠/주문폴러를 비활성화한다 (API 전용 모드)"
        )
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
        await _shutdown_worker_runtime(worker_runtime)
        await _disconnect_cache()
        shutdown_logger.info("[shutdown] graceful shutdown complete")
