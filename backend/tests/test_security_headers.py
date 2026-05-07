"""SecurityHeadersMiddleware 단위 테스트 — HSTS / CSP / 표준 보안 헤더."""

from __future__ import annotations

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


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app)


# ── 표준 보안 헤더 ────────────────────────────────────────────

class TestBaseSecurityHeaders:
    """모든 응답에 5개 표준 보안 헤더가 부착되어야 한다."""

    def test_hsts_on_health(self, client):
        r = client.get("/api/v1/health")
        assert r.headers.get("Strict-Transport-Security") == (
            "max-age=31536000; includeSubDomains; preload"
        )

    def test_x_content_type_options(self, client):
        r = client.get("/api/v1/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        r = client.get("/api/v1/health")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, client):
        r = client.get("/api/v1/health")
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        r = client.get("/api/v1/health")
        assert r.headers.get("Permissions-Policy") == (
            "camera=(), microphone=(), geolocation=()"
        )

    def test_root_endpoint_also_has_headers(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Strict-Transport-Security" in r.headers
        assert r.headers.get("X-Frame-Options") == "DENY"


# ── CSP 분기 ──────────────────────────────────────────────────

class TestCSPBranches:
    """경로에 따라 CSP 헤더가 다르게 부착되거나 면제되어야 한다."""

    def test_api_endpoint_has_strict_csp(self, client):
        r = client.get("/api/v1/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "base-uri 'none'" in csp

    def test_root_endpoint_has_strict_csp(self, client):
        r = client.get("/")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'none'" in csp

    def test_docs_has_no_csp(self, client):
        # /docs 는 swagger UI inline script 사용 — CSP 면제
        r = client.get("/docs")
        # 운영에선 docs_url=None 이라 404 가능. 200 이든 404 든 CSP 헤더는 없어야 함
        assert "Content-Security-Policy" not in r.headers

    def test_redoc_has_no_csp(self, client):
        r = client.get("/redoc")
        assert "Content-Security-Policy" not in r.headers

    # /openapi.json 은 fastapi schema 생성 시 KreamLoginRequest ForwardRef 미해결로
    # 테스트 환경에서 raise — `_csp_for` 단위 함수 테스트로 면제를 별도 검증.

    def test_static_endpoint_has_static_csp_when_present(self, client):
        # /static/images 가 mount 되어 있다면 정적 CSP 적용
        r = client.get("/static/images/__nonexistent__.png")
        # 404 든 200 든 CSP 가 있다면 정적용이어야 함
        csp = r.headers.get("Content-Security-Policy")
        if csp is not None:
            assert "default-src 'self'" in csp
            assert "img-src 'self' data:" in csp


# ── 미들웨어 함수 단위 ────────────────────────────────────────

class TestCspForFunction:
    """경로별 CSP 선택 헬퍼 단위 검증."""

    def test_api_path_returns_strict_csp(self):
        from backend.middleware.security_headers import _csp_for, _CSP_API

        assert _csp_for("/api/v1/health") == _CSP_API
        assert _csp_for("/") == _CSP_API
        assert _csp_for("/api/v1/samba/orders") == _CSP_API

    def test_docs_paths_return_none(self):
        from backend.middleware.security_headers import _csp_for

        assert _csp_for("/docs") is None
        assert _csp_for("/docs/oauth2-redirect") is None
        assert _csp_for("/redoc") is None
        assert _csp_for("/openapi.json") is None

    def test_static_paths_return_static_csp(self):
        from backend.middleware.security_headers import _csp_for, _CSP_STATIC

        assert _csp_for("/static/images/foo.png") == _CSP_STATIC
        assert _csp_for("/static/model_presets/x.png") == _CSP_STATIC
