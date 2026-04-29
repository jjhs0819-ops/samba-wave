"""Application lifecycle hooks for SambaWave backend."""

import asyncio
import logging
import os
import re
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


async def _sync_playauto_registered_accounts(logger: logging.Logger) -> None:
    try:
        from sqlalchemy import String, cast
        from sqlmodel import select

        from backend.db.orm import get_write_session
        from backend.domain.samba.account.model import SambaMarketAccount
        from backend.domain.samba.collector.model import SambaCollectedProduct
        from backend.domain.samba.proxy.playauto import PlayAutoClient

        async with get_write_session() as session:
            statement = select(SambaMarketAccount).where(
                SambaMarketAccount.market_type == "playauto",
                SambaMarketAccount.is_active == True,  # noqa: E712
            )
            result = await session.exec(statement)
            account = result.first()
            if not account:
                return

            extras = account.additional_fields or {}
            api_key = extras.get("apiKey", "") or getattr(account, "api_key", "")
            if not api_key:
                return

            client = PlayAutoClient(api_key)
            try:
                playauto_products = await client.get_products(my_cate_name="SAMBA-WAVE")
            finally:
                await client.close()

            logger.info(
                "[startup] playauto SAMBA-WAVE products=%s", len(playauto_products)
            )

            site_ids: set[str] = set()
            mastercode_map: dict[str, str] = {}
            for product in playauto_products:
                product_name = str(product.get("ProdName", "") or "").strip()
                master_code = str(product.get("MasterCode", "") or "").strip()
                parts = product_name.split()
                if not parts:
                    continue
                token = parts[-1]
                if not re.match(r"^[A-Za-z0-9_-]+$", token):
                    continue
                site_ids.add(token)
                if master_code:
                    mastercode_map[token] = master_code

            if site_ids:
                updated = 0
                site_id_list = list(site_ids)
                for chunk_index in range(0, len(site_id_list), 1000):
                    chunk = site_id_list[chunk_index : chunk_index + 1000]
                    product_stmt = select(SambaCollectedProduct).where(
                        SambaCollectedProduct.site_product_id.in_(chunk),
                    )
                    product_result = await session.exec(product_stmt)
                    for collected in product_result.all():
                        changed = False
                        registered_accounts = list(collected.registered_accounts or [])
                        if account.id not in registered_accounts:
                            registered_accounts.append(account.id)
                            collected.registered_accounts = registered_accounts
                            changed = True
                        if collected.status != "registered":
                            collected.status = "registered"
                            changed = True
                        market_product_nos = dict(collected.market_product_nos or {})
                        if account.id not in market_product_nos:
                            master_code = mastercode_map.get(
                                collected.site_product_id, ""
                            )
                            if master_code:
                                market_product_nos[account.id] = master_code
                                collected.market_product_nos = market_product_nos
                                changed = True
                        if changed:
                            session.add(collected)
                            updated += 1

                if updated:
                    await session.commit()
                logger.info(
                    "[startup] playauto forward sync products=%s site_ids=%s updated=%s",
                    len(playauto_products),
                    len(site_ids),
                    updated,
                )

                reverse_stmt = select(SambaCollectedProduct).where(
                    cast(SambaCollectedProduct.registered_accounts, String).like(
                        f'%"{account.id}"%'
                    )
                )
                reverse_result = await session.exec(reverse_stmt)
                removed = 0
                for collected in reverse_result.all():
                    if (
                        not collected.site_product_id
                        or collected.site_product_id in site_ids
                    ):
                        continue
                    registered_accounts = [
                        value
                        for value in (collected.registered_accounts or [])
                        if value != account.id
                    ]
                    collected.registered_accounts = registered_accounts or None
                    market_product_nos = dict(collected.market_product_nos or {})
                    market_product_nos.pop(str(account.id), None)
                    collected.market_product_nos = market_product_nos or None
                    if not registered_accounts:
                        collected.status = "collected"
                    session.add(collected)
                    removed += 1

                if removed:
                    await session.commit()
                logger.info("[startup] playauto reverse sync removed=%s", removed)
    except Exception as exc:
        logger.warning("[startup] playauto sync failed: %s", exc)


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
    # PlayAuto 동기화는 외부 API + 대용량 DB 스캔으로 5~10분 소요 가능
    # yield 이전에 실행하면 health check가 그만큼 지연되므로 백그라운드 태스크로 분리
    asyncio.create_task(_sync_playauto_registered_accounts(startup_logger))

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
        worker_runtime = await _start_worker_runtime()
        await _start_autotune_if_enabled()
        await _start_order_poller()
        await _start_lottehome_qa_poller()
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
        await _shutdown_worker_runtime(worker_runtime)
        await _disconnect_cache()
        shutdown_logger.info("[shutdown] graceful shutdown complete")
