"""FastAPI app construction for SambaWave backend."""

from pathlib import Path

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.v1.routers.auth import router as auth_router
from backend.api.v1.routers.ebay import router as ebay_router
from backend.api.v1.routers.license import router as license_router
from backend.api.v1.routers.samba.account import router as samba_account_router
from backend.api.v1.routers.samba.license_admin import router as license_admin_router
from backend.api.v1.routers.samba.ai_sourcing import router as samba_ai_sourcing_router
from backend.api.v1.routers.samba.analytics import router as samba_analytics_router
from backend.api.v1.routers.samba.category import router as samba_category_router
from backend.api.v1.routers.samba.channel import router as samba_channel_router
from backend.api.v1.routers.samba.collector import router as samba_collector_router
from backend.api.v1.routers.samba.collector_autotune import (
    router as samba_collector_autotune_router,
)
from backend.api.v1.routers.samba.collector_collection import (
    router as samba_collector_collection_router,
)
from backend.api.v1.routers.samba.collector_refresh import (
    router as samba_collector_refresh_router,
)
from backend.api.v1.routers.samba.contact import router as samba_contact_router
from backend.api.v1.routers.samba.cs_inquiry import router as samba_cs_inquiry_router
from backend.api.v1.routers.samba.ebay_mapping import (
    router as samba_ebay_mapping_router,
)
from backend.api.v1.routers.samba.forbidden import router as samba_forbidden_router
from backend.api.v1.routers.samba.job import router as samba_job_router
from backend.api.v1.routers.samba.naverstore_sourcing import (
    router as samba_naverstore_sourcing_router,
)
from backend.api.v1.routers.samba.order import router as samba_order_router
from backend.api.v1.routers.samba.policy import router as samba_policy_router
from backend.api.v1.routers.samba.product import router as samba_product_router
from backend.api.v1.routers.samba.proxy import (
    bg_worker_router as samba_bg_worker_router,
    cafe24_oauth_router as samba_cafe24_oauth_router,
    router as samba_proxy_router,
    sourcing_queue_router as samba_sourcing_queue_router,
)
from backend.api.v1.routers.samba.returns import router as samba_returns_router
from backend.api.v1.routers.samba.shipment import router as samba_shipment_router
from backend.api.v1.routers.samba.sns_posting import router as samba_sns_posting_router
from backend.api.v1.routers.samba.sourcing_account import (
    extension_router as samba_sourcing_account_extension_router,
)
from backend.api.v1.routers.samba.sourcing_account import (
    router as samba_sourcing_account_router,
)
from backend.api.v1.routers.samba.store_care import router as samba_store_care_router
from backend.api.v1.routers.samba.tenant import router as samba_tenant_router
from backend.api.v1.routers.samba.user import router as samba_user_router
from backend.api.v1.routers.samba.warroom import router as samba_warroom_router
from backend.api.v1.routers.samba.wholesale import router as samba_wholesale_router
from backend.api.v1.routers.user import router as user_router
from backend.core.config import settings
from backend.domain.user.auth_service import get_user_id
from backend.lifecycle import lifespan
from backend.middleware.error_handler import register_exception_handlers


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

    register_exception_handlers(app)

    from backend.middleware.api_gateway import ApiGatewayMiddleware

    # CORS가 가장 바깥쪽에 있어야 Gateway 403 같은 오류 응답에도 CORS 헤더가 붙음
    # add_middleware는 나중에 추가할수록 바깥쪽(outermost)이므로 순서 주의
    app.add_middleware(ApiGatewayMiddleware, api_key=settings.api_gateway_key)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_origin_regex=settings.cors_origin_regex,
    )

    samba_auth = [Depends(get_user_id)]

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(license_router, prefix="/api/v1")
    app.include_router(
        license_admin_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(user_router, prefix="/api/v1", dependencies=samba_auth)
    app.include_router(samba_user_router, prefix="/api/v1/samba")
    app.include_router(
        samba_product_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_order_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_channel_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_policy_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_collector_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_collector_collection_router,
        prefix="/api/v1/samba",
        dependencies=samba_auth,
    )
    app.include_router(
        samba_collector_refresh_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_collector_autotune_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_category_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_account_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_shipment_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_forbidden_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_contact_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_returns_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_analytics_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_proxy_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(samba_sourcing_queue_router, prefix="/api/v1/samba")
    # 카페24 OAuth 콜백은 외부 서버 리다이렉트라 JWT 헤더 불가 → 별도 라우터로 JWT 예외
    app.include_router(samba_cafe24_oauth_router, prefix="/api/v1/samba")
    app.include_router(samba_bg_worker_router, prefix="/api/v1/samba")
    app.include_router(
        samba_warroom_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_ai_sourcing_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_tenant_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_job_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_cs_inquiry_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_store_care_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_wholesale_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_sns_posting_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    # extension_router를 먼저 등록 — `@router.get("/{account_id}")` 같은 catch-all보다
    # specific 라우트(GET /login-credential)가 우선 매칭되도록 함.
    # 등록 순서 바꾸지 않으면 GET /login-credential이 /{account_id}로 매칭되어 samba_auth JWT 401 발생.
    app.include_router(samba_sourcing_account_extension_router, prefix="/api/v1/samba")
    app.include_router(
        samba_sourcing_account_router, prefix="/api/v1/samba", dependencies=samba_auth
    )
    app.include_router(
        samba_naverstore_sourcing_router,
        prefix="/api/v1/samba",
        dependencies=samba_auth,
    )

    # eBay 라우터 (포크 전용)
    app.include_router(ebay_router, prefix="/api/v1", dependencies=samba_auth)
    app.include_router(
        samba_ebay_mapping_router, prefix="/api/v1/samba", dependencies=samba_auth
    )

    static_dir = Path(__file__).resolve().parent / "static" / "images"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/images", StaticFiles(directory=str(static_dir)), name="static-images"
    )

    preset_dir = Path(__file__).resolve().parent / "static" / "model_presets"
    preset_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/model_presets",
        StaticFiles(directory=str(preset_dir)),
        name="static-presets",
    )

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"name": "Backend API", "version": "1.0.0"}

    @app.get("/api/v1/health")
    async def health(response: Response) -> dict:
        import os

        from backend.domain.samba.job.worker import get_worker_status

        # Blue/Green 배포 graceful drain 신호:
        # deploy.sh 가 stop 직전 /tmp/draining 을 touch 하면 503 반환 →
        # Caddy active health check 가 즉시 fail 감지 → 다른 upstream 으로 트래픽 전환 →
        # 이후 실제 stop 시점에는 트래픽 0 상태 (무중단 보장)
        if os.path.exists("/tmp/draining"):
            response.status_code = 503
            return {"status": "draining"}

        commit = os.environ.get("COMMIT_SHA", "unknown")
        return {
            "status": "healthy",
            "commit": commit[:7] if commit and commit != "unknown" else "unknown",
            "deployed_at": os.environ.get("DEPLOYED_AT", ""),
            "worker": get_worker_status(),
        }

    return app
