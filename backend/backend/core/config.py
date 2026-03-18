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
    access_token_expire_minutes: int = 720  # 12 hours
    refresh_token_expire_days: int = 30

    # ===========================================
    # Authentication Configuration
    # ===========================================
    mock_auth_enabled: bool = False
    """Enable mock authentication for development."""

    # ===========================================
    # S3 Configuration
    # ===========================================
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-northeast-2"
    s3_bucket_name: str = ""

    # ===========================================
    # CORS Configuration
    # ===========================================

    # ===========================================
    # Scheduler Configuration
    # ===========================================
    scheduler_secret: str = ""
    """스케줄러 tick 엔드포인트 인증 키."""

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
            "https://samba-wave-1zm6k4gb4-sbk0674-2598s-projects.vercel.app",
        ]
        if self.cors_extra_origins:
            extras = [o.strip() for o in self.cors_extra_origins.split(",") if o.strip()]
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


settings = BackendSettings()
