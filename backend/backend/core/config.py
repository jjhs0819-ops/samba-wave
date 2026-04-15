from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ===========================================
    # Environment Configuration
    # ===========================================
    environment: Literal["development", "staging", "production"] = "development"
    """Deployment environment: development, staging, production."""

    # ===========================================
    # Database Configuration
    # ===========================================
    write_db_user: str
    write_db_password: str
    write_db_host: str
    write_db_port: int
    write_db_name: str
    read_db_user: str
    read_db_password: str
    read_db_host: str
    read_db_port: int
    read_db_name: str

    # Database SSL configuration
    db_ssl_required: bool | None = None

    @computed_field
    @property
    def use_db_ssl(self) -> bool:
        """Compute actual SSL requirement based on explicit setting or environment."""
        if self.db_ssl_required is not None:
            return self.db_ssl_required
        return self.environment != "development"

    # ===========================================
    # JWT Configuration
    # ===========================================
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"

    # Token expiration settings
    access_token_expire_minutes: int = 43200  # 30일
    refresh_token_expire_days: int = 30

    # ===========================================
    # Authentication Configuration
    # ===========================================
    mock_auth_enabled: bool = False
    """Enable mock authentication for development."""

    # ===========================================
    # CORS Configuration
    # ===========================================

    # ===========================================
    # API Gateway Key (외부 앱 차단용)
    # ===========================================
    api_gateway_key: str = ""
    """API 게이트웨이 키 — 프론트엔드·확장앱만 허용, 외부 앱 차단."""

    # ===========================================
    # AI / Anthropic Configuration
    # ===========================================
    anthropic_api_key: str = ""
    """Claude API 키 (카테고리 AI 매핑 등)."""

    # ===========================================
    # Redis 설정
    # ===========================================
    redis_url: str | None = None  # 환경변수: REDIS_URL

    # ===========================================
    # 네이버 API 설정 (스마트스토어 소싱용)
    # ===========================================
    naver_client_id: str = ""
    """네이버 검색 API Client ID."""
    naver_client_secret: str = ""
    """네이버 검색 API Client Secret."""

    # ===========================================
    # HTTP 타임아웃 설정 (초)
    # ===========================================
    http_timeout_short: int = 10  # 빠른 API (검색, 조회)
    http_timeout_default: int = 30  # 기본 API (등록, 수정)
    http_timeout_upload: int = 60  # 이미지 업로드 등 느린 작업

    # 프록시 URL (오토튠용, 콤마 구분 — 로테이션)
    proxy_urls: str = ""
    # 프록시 URL (수집용)
    collect_proxy_url: str = ""

    # ===========================================
    # LOTTEON 소싱 기능 플래그
    # ===========================================
    lotteon_full_paging_enabled: bool = False
    """롯데ON 카테고리필터 수집 시 qapi 전수 페이징(최대 2,100건) 허용 여부.
    기본 off — 기존 동작(요청수×2 또는 최소 100) 유지.
    on으로 전환 시 worker.py _max=9999, 브랜드별 per_max=600 캡 적용."""

    # 추가 허용 origin (콤마 구분, Railway 환경변수로 주입)
    cors_extra_origins: str = ""

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        """Get allowed CORS origins based on environment."""
        origins = [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3002",
            "http://localhost:3003",
            "http://127.0.0.1:3000",
        ]
        if self.cors_extra_origins:
            extras = [
                o.strip() for o in self.cors_extra_origins.split(",") if o.strip()
            ]
            origins.extend(extras)
        return origins

    @computed_field
    @property
    def cors_origin_regex(self) -> str | None:
        """모든 환경에서 localhost + 프로젝트 vercel.app 허용."""
        return r"https?://(localhost(:\d+)?|127\.0\.0\.1(:\d+)?|samba-wave[a-z0-9-]*\.vercel\.app)"

    # ===========================================
    # Computed Properties
    # ===========================================
    @computed_field
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.environment == "development"

    @computed_field
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.environment == "production"

    @computed_field
    @property
    def debug_enabled(self) -> bool:
        """Enable debug mode in non-production environments."""
        return self.environment != "production"


_settings = BackendSettings()

# ── 개발 환경에서 운영 DB 접속 차단 ──
_PRODUCTION_DB_HOSTS = [
    "34.47.96.236",
    "/cloudsql/fresh-sanctuary",  # 팀장님 운영 DB
    "/cloudsql/samba-wave-molle",  # 준길 운영 DB
]
if _settings.is_development:
    for _h in _PRODUCTION_DB_HOSTS:
        if _h in _settings.write_db_host or _h in _settings.read_db_host:
            raise RuntimeError(
                f"[보안 차단] 개발 환경(APP_ENV=development)에서 운영 DB 호스트({_h}) 접속이 감지되었습니다. "
                "운영 DB는 Cloud Run 배포를 통해서만 접근해야 합니다."
            )

settings = _settings
