"""SambaWave 백엔드 서버 진입점."""
# DB 크리덴셜 로테이션 2026-04-11

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.core.config import settings
from backend.api.v1.routers.auth import router as auth_router
from backend.api.v1.routers.user import router as user_router
from backend.api.v1.routers.samba.product import router as samba_product_router
from backend.api.v1.routers.samba.order import router as samba_order_router
from backend.api.v1.routers.samba.channel import router as samba_channel_router
from backend.api.v1.routers.samba.policy import router as samba_policy_router
from backend.api.v1.routers.samba.collector import router as samba_collector_router
from backend.api.v1.routers.samba.collector_collection import (
    router as samba_collector_collection_router,
)
from backend.api.v1.routers.samba.collector_refresh import (
    router as samba_collector_refresh_router,
)
from backend.api.v1.routers.samba.collector_autotune import (
    router as samba_collector_autotune_router,
)
from backend.api.v1.routers.samba.category import router as samba_category_router
from backend.api.v1.routers.samba.account import router as samba_account_router
from backend.api.v1.routers.samba.shipment import router as samba_shipment_router
from backend.api.v1.routers.samba.forbidden import router as samba_forbidden_router
from backend.api.v1.routers.samba.contact import router as samba_contact_router
from backend.api.v1.routers.samba.returns import router as samba_returns_router
from backend.api.v1.routers.samba.analytics import router as samba_analytics_router
from backend.api.v1.routers.samba.proxy import router as samba_proxy_router
from backend.api.v1.routers.samba.proxy import (
    sourcing_queue_router as samba_sourcing_queue_router,
)
from backend.api.v1.routers.samba.warroom import router as samba_warroom_router
from backend.api.v1.routers.samba.user import router as samba_user_router
from backend.api.v1.routers.samba.ai_sourcing import router as samba_ai_sourcing_router
from backend.api.v1.routers.samba.tenant import router as samba_tenant_router
from backend.api.v1.routers.samba.job import router as samba_job_router
from backend.api.v1.routers.samba.cs_inquiry import router as samba_cs_inquiry_router
from backend.api.v1.routers.samba.store_care import router as samba_store_care_router
from backend.api.v1.routers.samba.wholesale import router as samba_wholesale_router
from backend.api.v1.routers.samba.sns_posting import router as samba_sns_posting_router
from backend.api.v1.routers.samba.sourcing_account import (
    router as samba_sourcing_account_router,
)

from backend.domain.user.auth_service import get_user_id
from backend.middleware.error_handler import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown validation."""
    # 앱 시작 시 DB 마이그레이션 자동 적용 (별도 프로세스 또는 수동 실행 권장)
    # 로컬 개발: cd backend && alembic upgrade head

    # 캐시 서비스 연결 (Redis 또는 인메모리 폴백)
    from backend.domain.samba.cache import cache

    await cache.connect()

    # 서버 시작 시 리비전/커밋 로그 — 어떤 코드가 돌고 있는지 즉시 확인
    import logging as _startup_logging
    import os as _os

    _startup_log = _startup_logging.getLogger("backend.startup")
    _revision = _os.environ.get("K_REVISION", "local")
    _commit = _os.environ.get("COMMIT_SHA", "unknown")
    _startup_log.info(f"[startup] 리비전={_revision}, 커밋={_commit}")

    # 누락 컬럼 자동 추가 (CI/CD가 DB를 건드리지 않으므로 앱에서 보완)
    _migrations = [
        ("samba_order", "paid_at", "TIMESTAMPTZ"),
        ("samba_search_filter", "source_brand_name", "TEXT"),
    ]
    try:
        from backend.db.orm import get_write_session
        from sqlalchemy import text

        async with get_write_session() as session:
            for _tbl, _col, _typ in _migrations:
                await session.execute(
                    text(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS {_col} {_typ}")
                )
            # sort_order 컬럼 제거 (모델에서 삭제됨)
            await session.execute(
                text(
                    "ALTER TABLE samba_market_account DROP COLUMN IF EXISTS sort_order"
                )
            )
            # samba_login_history 테이블 자동 생성
            await session.execute(
                text(
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
                    """
                )
            )
            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_samba_login_history_user_id ON samba_login_history (user_id)"
                )
            )
            # [일회성] ABCmart 배송비 초기화 — 무료배송인데 sourcing_shipping_fee=3000 잘못 저장된 건
            _fix = await session.execute(
                text(
                    "UPDATE samba_collected_product SET sourcing_shipping_fee = 0 WHERE source_site = 'ABCmart' AND sourcing_shipping_fee > 0"
                )
            )
            if _fix.rowcount > 0:
                _startup_log.info(
                    f"[startup] ABCmart sourcing_shipping_fee 초기화: {_fix.rowcount}건"
                )
            # 파생 주문 일괄 삭제 (사본-* + ★교환주문 — 원주문에 이미 정보 포함)
            _del = await session.execute(
                text(
                    "DELETE FROM samba_order WHERE product_name LIKE '[사본-%' OR product_name LIKE '%★교환주문%'"
                )
            )
            if _del.rowcount > 0:
                _startup_log.info(f"[startup] 파생 주문 {_del.rowcount}건 삭제")
            await session.commit()
            _startup_log.info(
                f"[startup] 스키마 마이그레이션 완료 ({len(_migrations)}건)"
            )
    except Exception as _mig_err:
        _startup_log.error(
            f"[startup] 스키마 마이그레이션 실패 — 서비스 동작에 영향을 줄 수 있습니다: {_mig_err}",
            exc_info=True,
        )

    # 서버 시작 시 좀비 running Job 처리
    # - transmit: attempt < 3이면 pending 복구 (배포 중단 → 자동 재개)
    #             attempt >= 3이면 failed (OOM 무한루프 방지)
    # - collect 등 나머지: pending 복구
    _MAX_TRANSMIT_ATTEMPTS = 3
    for _attempt in range(3):
        try:
            from backend.db.orm import get_write_session
            from sqlalchemy import text

            async with get_write_session() as session:
                # transmit Job: attempt 기반 분기
                # attempt < 3 → pending 복구 + attempt 증가 (current 보존 → 이어서 전송)
                r_resume = await asyncio.wait_for(
                    session.execute(
                        text(
                            "UPDATE samba_jobs "
                            "SET status = 'pending', started_at = NULL, "
                            "attempt = COALESCE(attempt, 0) + 1 "
                            "WHERE status = 'running' AND job_type = 'transmit' "
                            f"AND COALESCE(attempt, 0) < {_MAX_TRANSMIT_ATTEMPTS}"
                        )
                    ),
                    timeout=8,
                )
                if r_resume.rowcount > 0:
                    _startup_log.info(
                        f"[startup] 좀비 transmit Job {r_resume.rowcount}건 → pending 복구 (재개 예정)"
                    )

                # attempt >= 3 → failed (OOM 반복 의심)
                r_fail = await asyncio.wait_for(
                    session.execute(
                        text(
                            "UPDATE samba_jobs "
                            "SET status = 'failed', "
                            "error = 'OOM 반복 재시작 (attempt >= 3) — 수동 확인 필요', "
                            "completed_at = now() "
                            "WHERE status = 'running' AND job_type = 'transmit' "
                            f"AND COALESCE(attempt, 0) >= {_MAX_TRANSMIT_ATTEMPTS}"
                        )
                    ),
                    timeout=8,
                )
                if r_fail.rowcount > 0:
                    _startup_log.info(
                        f"[startup] 좀비 transmit Job {r_fail.rowcount}건 → failed (attempt >= {_MAX_TRANSMIT_ATTEMPTS})"
                    )

                # collect 등 나머지 → pending 복구 (기존 동작 유지)
                r_other = await asyncio.wait_for(
                    session.execute(
                        text(
                            "UPDATE samba_jobs SET status = 'pending', started_at = NULL "
                            "WHERE status = 'running' AND job_type != 'transmit'"
                        )
                    ),
                    timeout=8,
                )
                if r_other.rowcount > 0:
                    _startup_log.info(
                        f"[startup] 좀비 running Job {r_other.rowcount}건 → pending 복구"
                    )
                await session.commit()
            break
        except Exception as e:
            _startup_log.warning(f"[startup] Job 복구 실패 ({_attempt + 1}/3): {e}")
            if _attempt < 2:
                await asyncio.sleep(2)

    # 백그라운드 잡 워커 시작 + watchdog (죽으면 자동 재시작)
    from backend.domain.samba.job.worker import JobWorker
    import logging as _logging

    _wd_log = _logging.getLogger("backend.watchdog")
    worker = JobWorker()
    worker_task = asyncio.create_task(worker.start())

    async def _worker_watchdog():
        """워커 태스크 감시 — 죽으면 3초 후 자동 재시작."""
        nonlocal worker, worker_task
        while True:
            try:
                await asyncio.sleep(10)
                if worker_task.done():
                    exc = (
                        worker_task.exception() if not worker_task.cancelled() else None
                    )
                    _wd_log.error(
                        f"[watchdog] 잡워커 죽음 감지 (exc={exc}) — 3초 후 재시작"
                    )
                    await asyncio.sleep(3)
                    worker = JobWorker()
                    worker_task = asyncio.create_task(worker.start())
                    _wd_log.info("[watchdog] 잡워커 재시작 완료")
            except asyncio.CancelledError:
                break
            except Exception as e:
                _wd_log.error(f"[watchdog] 감시 에러: {e}")
                await asyncio.sleep(10)

    watchdog_task = asyncio.create_task(_worker_watchdog())

    # 오토튠 자동 시작 (DB에 ON 상태면 자동 실행)
    from backend.api.v1.routers.samba.collector_autotune import auto_start_if_enabled

    await auto_start_if_enabled()

    # Startup validation
    if settings.mock_auth_enabled and settings.environment == "production":
        raise RuntimeError(
            "CRITICAL: Mock authentication cannot be enabled in production. "
            "Set MOCK_AUTH_ENABLED=false or ENVIRONMENT to non-production value."
        )

    if settings.mock_auth_enabled:
        import logging

        logging.warning(
            "Mock authentication is ENABLED. "
            "This should only be used for development/testing."
        )

    yield
    # Graceful Shutdown — 진행 중인 전송을 안전하게 중단하고 pending으로 보존
    import logging

    _log = logging.getLogger("backend.shutdown")
    _log.info("[shutdown] SIGTERM 수신 — graceful shutdown 시작")

    # 1) 오토튠 즉시 정지
    from backend.api.v1.routers.samba.collector_autotune import (
        _autotune_running_event,
        _autotune_task,
    )
    from backend.domain.samba.collector.refresher import request_bulk_cancel_all

    _autotune_running_event.clear()
    request_bulk_cancel_all()
    if _autotune_task and not _autotune_task.done():
        _autotune_task.cancel()
    watchdog_task.cancel()

    # 2) 잡 워커 graceful 종료 — 전송 루프가 현재 건 완료 후 pending 보존
    #    최대 30초 대기 (Cloud Run graceful-timeout=300초 내)
    try:
        await worker.graceful_stop(timeout=30)
    except Exception as gs_err:
        _log.error(f"[shutdown] graceful_stop 실패: {gs_err}")
        # 폴백: 강제 종료
        worker.stop()

    worker_task.cancel()
    _log.info("[shutdown] graceful shutdown 완료")


def create_application() -> FastAPI:
    """Create and configure FastAPI application with API routes."""

    app = FastAPI(
        title="Backend API",
        version="1.0.0",
        description="Backend API",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        lifespan=lifespan,
    )

    # Register exception handlers
    register_exception_handlers(app)

    # Configure CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_origin_regex=settings.cors_origin_regex,
    )

    # API Gateway Key 미들웨어 — 외부 앱 차단 (CORS 뒤에 등록해야 preflight 통과)
    from backend.middleware.api_gateway import ApiGatewayMiddleware

    app.add_middleware(ApiGatewayMiddleware, api_key=settings.api_gateway_key)

    # JWT 인증 의존성 (모든 보호 라우터에 일괄 적용)
    _samba_auth = [Depends(get_user_id)]

    # 레거시 auth/user 라우터
    # auth_router: login/signup/refresh는 공개, /me만 인증 (자체 처리)
    app.include_router(auth_router, prefix="/api/v1")
    # user_router: 레거시 사용자 관리 — 인증 필수
    app.include_router(user_router, prefix="/api/v1", dependencies=_samba_auth)

    # SambaWave routers — 로그인/회원가입만 공개, 나머지 전부 인증 필수
    app.include_router(samba_user_router, prefix="/api/v1/samba")

    # 나머지 모든 samba 라우터 — 인증 필수
    app.include_router(
        samba_product_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_order_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_channel_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_policy_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_collector_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_collector_collection_router,
        prefix="/api/v1/samba",
        dependencies=_samba_auth,
    )
    app.include_router(
        samba_collector_refresh_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_collector_autotune_router,
        prefix="/api/v1/samba",
        dependencies=_samba_auth,
    )
    app.include_router(
        samba_category_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_account_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_shipment_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_forbidden_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_contact_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_returns_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_analytics_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_proxy_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    # 소싱큐 엔드포인트 — 확장앱 폴링용, 인증 불필요
    app.include_router(samba_sourcing_queue_router, prefix="/api/v1/samba")
    app.include_router(
        samba_warroom_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_ai_sourcing_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_tenant_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_job_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_cs_inquiry_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_store_care_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_wholesale_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_sns_posting_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )
    app.include_router(
        samba_sourcing_account_router, prefix="/api/v1/samba", dependencies=_samba_auth
    )

    # 로컬 이미지 저장 디렉토리 서빙 (R2 미설정 시 사용)
    static_dir = Path(__file__).resolve().parent / "static" / "images"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/images", StaticFiles(directory=str(static_dir)), name="static-images"
    )

    # 모델 프리셋 이미지 서빙
    preset_dir = Path(__file__).resolve().parent / "static" / "model_presets"
    preset_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/model_presets",
        StaticFiles(directory=str(preset_dir)),
        name="static-presets",
    )

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "name": "Backend API",
            "version": "1.0.0",
        }

    @app.get("/api/v1/health")
    async def health() -> dict:
        from backend.domain.samba.job.worker import get_worker_status

        return {"status": "healthy", "worker": get_worker_status()}

    return app


# Create the app instance
app = create_application()
