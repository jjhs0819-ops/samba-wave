"""레이트 리미터 + JWT entropy 검증 smoke 테스트."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("JWT_SECRET_KEY", "a" * 48)
    os.environ.setdefault("API_GATEWAY_KEY", "")
    os.environ.setdefault("WRITE_DB_USER", "test")
    os.environ.setdefault("WRITE_DB_PASSWORD", "test")
    os.environ.setdefault("WRITE_DB_HOST", "localhost")
    os.environ.setdefault("WRITE_DB_PORT", "5433")
    os.environ.setdefault("WRITE_DB_NAME", "test")
    os.environ.setdefault("READ_DB_USER", "test")
    os.environ.setdefault("READ_DB_PASSWORD", "test")
    os.environ.setdefault("READ_DB_HOST", "localhost")
    os.environ.setdefault("READ_DB_PORT", "5433")
    os.environ.setdefault("READ_DB_NAME", "test")
    from backend.app_factory import create_application

    return create_application()


def test_jwt_entropy_validation_too_short(monkeypatch):
    """32바이트 미만 JWT secret 은 startup 시 RuntimeError."""
    from backend.lifecycle import _validate_startup_settings
    from backend.core.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", "short")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _validate_startup_settings()


def test_jwt_entropy_validation_passes(monkeypatch):
    """32바이트 이상 JWT secret 은 통과."""
    from backend.lifecycle import _validate_startup_settings
    from backend.core.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", "x" * 32)
    monkeypatch.setattr(settings, "mock_auth_enabled", False)
    _validate_startup_settings()  # no raise


def test_critical_endpoints_have_rate_limit(app):
    """로그인/set-cookie 엔드포인트에 limiter 데코레이터가 적용되어 있는지 정적 검증.

    슬로우API 의 데코레이터는 함수의 `_rate_limits` 또는 wrapper 속성을 부여한다.
    여기서는 라우트의 endpoint 함수에 limiter 가 등록되었는지 확인.
    """
    from backend.core.rate_limit import limiter

    expected_paths = {
        "/api/v1/auth/email/login",
        "/api/v1/auth/email/sign-up",
        "/api/v1/auth/refresh",
        "/api/v1/samba/users/login",
        "/api/v1/samba/proxy/musinsa/set-cookie",
        "/api/v1/samba/proxy/lotteon/set-cookie",
        "/api/v1/samba/proxy/kream/set-cookie",
        "/api/v1/samba/proxy/kream/login",
    }

    # slowapi 는 limiter._route_limits 에 라우트별 제한을 저장.
    # 키는 함수의 qualname ("module.path.func") 형식.
    registered_qualnames = set(limiter._route_limits.keys())

    found = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path not in expected_paths:
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        # endpoint 가 slowapi 데코레이터로 래핑됐으면 __wrapped__ 의 qualname 으로 등록되어 있음
        wrapped = getattr(endpoint, "__wrapped__", endpoint)
        qualname = f"{wrapped.__module__}.{wrapped.__name__}"
        if qualname in registered_qualnames:
            found.add(path)

    missing = expected_paths - found
    assert not missing, f"rate limit 누락 엔드포인트: {missing}"


def test_client_key_uses_forwarded_for():
    """프록시 (Caddy) 뒤에서 X-Forwarded-For 의 첫 번째 IP 를 클라이언트 키로 사용."""
    from unittest.mock import Mock
    from backend.core.rate_limit import _client_key

    req = Mock()
    req.headers = {"x-forwarded-for": "203.0.113.42, 10.0.0.1, 10.0.0.2"}
    req.client = Mock(host="10.0.0.99")
    assert _client_key(req) == "203.0.113.42"

    # 헤더 없을 때 fallback
    req.headers = {}
    assert _client_key(req) == "10.0.0.99"

    # 클라이언트도 없을 때
    req.client = None
    assert _client_key(req) == "unknown"


def test_retry_after_header_computed():
    """429 응답에 Retry-After 헤더가 expiry 초로 정확히 설정되는지."""
    from unittest.mock import Mock
    from backend.core.rate_limit import rate_limit_exceeded_handler
    import limits

    rate_item = limits.parse("10/minute")  # expiry = 60s
    limit_obj = Mock()
    limit_obj.limit = rate_item
    exc = Mock()
    exc.limit = limit_obj
    exc.detail = "10 per 1 minute"

    response = rate_limit_exceeded_handler(Mock(), exc)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
