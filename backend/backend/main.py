import asyncio
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
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
from backend.api.v1.routers.samba.category import router as samba_category_router
from backend.api.v1.routers.samba.account import router as samba_account_router
from backend.api.v1.routers.samba.shipment import router as samba_shipment_router
from backend.api.v1.routers.samba.forbidden import router as samba_forbidden_router
from backend.api.v1.routers.samba.contact import router as samba_contact_router
from backend.api.v1.routers.samba.returns import router as samba_returns_router
from backend.api.v1.routers.samba.analytics import router as samba_analytics_router
from backend.api.v1.routers.samba.proxy import router as samba_proxy_router
from backend.api.v1.routers.samba.warroom import router as samba_warroom_router
from backend.api.v1.routers.samba.user import router as samba_user_router
from backend.api.v1.routers.samba.ai_sourcing import router as samba_ai_sourcing_router
from backend.api.v1.routers.samba.tenant import router as samba_tenant_router
from backend.api.v1.routers.samba.job import router as samba_job_router
from backend.api.v1.routers.samba.cs_inquiry import router as samba_cs_inquiry_router
from backend.api.v1.routers.samba.store_care import router as samba_store_care_router
from backend.api.v1.routers.samba.wholesale import router as samba_wholesale_router
from backend.api.v1.routers.samba.sns_posting import router as samba_sns_posting_router
from backend.middleware.error_handler import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown validation."""
    # 앱 시작 시 DB 마이그레이션 자동 적용 (별도 프로세스 또는 수동 실행 권장)
    # 로컬 개발: cd backend && alembic upgrade head

    # 캐시 서비스 연결 (Redis 또는 인메모리 폴백)
    from backend.domain.samba.cache import cache
    await cache.connect()

    # 백그라운드 잡 워커 시작
    from backend.domain.samba.job.worker import JobWorker
    worker = JobWorker()
    worker_task = asyncio.create_task(worker.start())

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
    # Shutdown — 잡 워커 정리
    worker.stop()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


def create_application() -> FastAPI:
    """Create and configure FastAPI application with API routes."""

    app = FastAPI(
        title="Backend API",
        version="1.0.0",
        description="Backend API",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json",
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

    # Register routers
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(user_router, prefix="/api/v1")

    # SambaWave routers (no auth required)
    app.include_router(samba_product_router, prefix="/api/v1/samba")
    app.include_router(samba_order_router, prefix="/api/v1/samba")
    app.include_router(samba_channel_router, prefix="/api/v1/samba")
    app.include_router(samba_policy_router, prefix="/api/v1/samba")
    app.include_router(samba_collector_router, prefix="/api/v1/samba")
    app.include_router(samba_category_router, prefix="/api/v1/samba")
    app.include_router(samba_account_router, prefix="/api/v1/samba")
    app.include_router(samba_shipment_router, prefix="/api/v1/samba")
    app.include_router(samba_forbidden_router, prefix="/api/v1/samba")
    app.include_router(samba_contact_router, prefix="/api/v1/samba")
    app.include_router(samba_returns_router, prefix="/api/v1/samba")
    app.include_router(samba_analytics_router, prefix="/api/v1/samba")
    app.include_router(samba_proxy_router, prefix="/api/v1/samba")
    app.include_router(samba_warroom_router, prefix="/api/v1/samba")
    app.include_router(samba_user_router, prefix="/api/v1/samba")
    app.include_router(samba_ai_sourcing_router, prefix="/api/v1/samba")
    app.include_router(samba_tenant_router, prefix="/api/v1/samba")
    app.include_router(samba_job_router, prefix="/api/v1/samba")
    app.include_router(samba_cs_inquiry_router, prefix="/api/v1/samba")
    app.include_router(samba_store_care_router, prefix="/api/v1/samba")
    app.include_router(samba_wholesale_router, prefix="/api/v1/samba")
    app.include_router(samba_sns_posting_router, prefix="/api/v1/samba")

    # 로컬 이미지 저장 디렉토리 서빙 (R2 미설정 시 사용)
    static_dir = Path(__file__).resolve().parent / "static" / "images"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/images", StaticFiles(directory=str(static_dir)), name="static-images")

    # 모델 프리셋 이미지 서빙
    preset_dir = Path(__file__).resolve().parent / "static" / "model_presets"
    preset_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/model_presets", StaticFiles(directory=str(preset_dir)), name="static-presets")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "name": "Backend API",
            "version": "1.0.0",
        }

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    return app


# Create the app instance
app = create_application()
