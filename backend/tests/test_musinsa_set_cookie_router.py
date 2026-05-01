"""무신사 /set-cookie 라우터가 확장앱 전용 라우터(JWT 면제)에 등록됐는지 검증.

배경: 2026-04-09부터 settings.musinsa_cookie(단수)가 갱신되지 않은 사고. 원인은
proxy 라우터 전체에 적용된 라우터 레벨 samba_auth(JWT) 의존성. 확장앱은 X-Api-Key만
보내 'Missing authentication token' 401로 거부. 팀장님 fix(2a4d8565)는 라우터 내부의
require_admin만 제거했고 라우터 레벨 JWT는 그대로라 사실상 미해결 상태였음.

이 테스트는 set-cookie 엔드포인트가 extension_router로 분리되어 JWT 없이 X-Api-Key만으로
호출 가능한지 라우팅 구조 자체를 검증한다.
"""

from __future__ import annotations


def test_set_cookie_route_lives_in_extension_router():
    """set-cookie 경로는 extension_router에만 등록되어야 한다."""
    from backend.api.v1.routers.samba.proxy.musinsa import extension_router, router

    extension_paths = {
        getattr(route, "path", "") for route in extension_router.routes
    }
    main_paths = {getattr(route, "path", "") for route in router.routes}

    assert "/musinsa/set-cookie" in extension_paths, (
        "set-cookie가 extension_router에 등록되어야 함 "
        f"(현재 extension_router 경로: {sorted(extension_paths)})"
    )
    assert "/musinsa/set-cookie" not in main_paths, (
        "set-cookie가 JWT 인증이 걸린 main router에 남아있으면 안 됨 "
        f"(현재 main router 경로 일부: {sorted(p for p in main_paths if 'cookie' in p)})"
    )


def test_extension_router_exported_from_proxy_package():
    """proxy 패키지가 extension_router를 export해야 app_factory에서 등록 가능."""
    from backend.api.v1.routers.samba.proxy import musinsa as musinsa_module
    from backend.api.v1.routers.samba.proxy import (
        musinsa_extension_router,
    )

    assert musinsa_extension_router is musinsa_module.extension_router


def test_extension_router_registered_without_jwt_in_app_factory():
    """app_factory.py가 musinsa extension_router를 dependencies 없이(JWT 면제) 등록해야 한다."""
    import inspect

    from backend.app_factory import create_application

    src = inspect.getsource(create_application)

    # musinsa_extension_router가 등록되어 있어야 하고,
    # 그 등록부에는 dependencies=samba_auth 가 없어야 한다 (JWT 면제).
    assert "musinsa_extension_router" in src, (
        "app_factory.create_application이 musinsa_extension_router를 등록해야 함"
    )

    register_idx = src.find("musinsa_extension_router")
    snippet = src[register_idx : register_idx + 200]
    assert "dependencies=samba_auth" not in snippet, (
        "musinsa_extension_router는 JWT 의존성 없이 등록되어야 함 (확장앱 X-Api-Key만 사용)"
    )
