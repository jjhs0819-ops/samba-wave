"""SambaWave SNS 포스팅 domain models — 워드프레스 연동 및 자동 포스팅 관련 테이블."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import Boolean, Integer, String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def gen_wp_id() -> str:
    """워드프레스 사이트 ID 생성."""
    return f"wp_{ULID()}"


def gen_kg_id() -> str:
    """키워드 그룹 ID 생성."""
    return f"skg_{ULID()}"


def gen_post_id() -> str:
    """SNS 포스트 ID 생성."""
    return f"snp_{ULID()}"


def gen_ac_id() -> str:
    """자동 포스팅 설정 ID 생성."""
    return f"sac_{ULID()}"


class SambaWpSite(SQLModel, table=True):
    """워드프레스 사이트 연결 테이블 — 사이트 URL, 인증 정보 관리."""

    __tablename__ = "samba_wp_site"

    id: str = Field(
        default_factory=gen_wp_id,
        primary_key=True,
        max_length=30,
    )

    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 사이트 접속 정보
    site_url: str = Field(sa_column=Column(Text, nullable=False))
    username: str = Field(sa_column=Column(String(100), nullable=False))
    app_password: str = Field(sa_column=Column(Text, nullable=False))

    # 사이트 메타
    site_name: Optional[str] = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )

    # 상태: active / inactive
    status: str = Field(
        default="active",
        sa_column=Column(String(20), nullable=False, server_default="active"),
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class SambaSnKeywordGroup(SQLModel, table=True):
    """이슈 검색 키워드 그룹 테이블 — 카테고리별 키워드 목록 관리."""

    __tablename__ = "samba_sns_keyword_group"

    id: str = Field(
        default_factory=gen_kg_id,
        primary_key=True,
        max_length=30,
    )

    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 그룹 정보
    name: str = Field(sa_column=Column(String(100), nullable=False))
    # 카테고리 구분: politics, economy, entertainment 등
    category: str = Field(sa_column=Column(String(50), nullable=False))

    # 세부 키워드 리스트 (JSON 배열)
    keywords: List[Any] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class SambaSnsPost(SQLModel, table=True):
    """SNS 포스팅 이력 테이블 — 워드프레스 발행된 포스트 기록."""

    __tablename__ = "samba_sns_post"

    id: str = Field(
        default_factory=gen_post_id,
        primary_key=True,
        max_length=30,
    )

    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 연결된 워드프레스 사이트
    wp_site_id: Optional[str] = Field(
        default=None, sa_column=Column(String(30), nullable=True)
    )
    # 워드프레스에서 발급된 포스트 ID
    wp_post_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )

    # 포스트 본문
    title: str = Field(sa_column=Column(Text, nullable=False))
    content: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 분류 정보
    category: Optional[str] = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    keyword: Optional[str] = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    source_url: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 상태: draft / published / failed
    status: str = Field(
        default="draft",
        sa_column=Column(String(20), nullable=False, server_default="draft"),
    )

    # 언어: ko / ja / en 등
    language: str = Field(
        default="ko",
        sa_column=Column(String(5), nullable=False, server_default="ko"),
    )

    # 연관 상품 ID 목록 (JSON 배열)
    product_ids: Optional[List[Any]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    published_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class SambaSnsAutoConfig(SQLModel, table=True):
    """SNS 자동 포스팅 설정 테이블 — 사이트별 자동화 파라미터."""

    __tablename__ = "samba_sns_auto_config"

    id: str = Field(
        default_factory=gen_ac_id,
        primary_key=True,
        max_length=30,
    )

    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 대상 워드프레스 사이트
    wp_site_id: str = Field(sa_column=Column(String(30), nullable=False))

    # 자동 포스팅 주기 (분)
    interval_minutes: int = Field(
        default=20, sa_column=Column(Integer, nullable=False, server_default="20")
    )
    # 일일 최대 포스팅 수
    max_daily_posts: int = Field(
        default=150, sa_column=Column(Integer, nullable=False, server_default="150")
    )

    # 실행 상태
    is_running: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # 언어: ko / ja / en 등
    language: str = Field(
        default="ko",
        sa_column=Column(String(5), nullable=False, server_default="ko"),
    )

    # 상품 배너 포함 여부
    include_product_banner: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    # 커스텀 배너 HTML (None이면 기본 배너 사용)
    product_banner_html: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 오늘 발행 카운트 (자정마다 리셋)
    today_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    last_posted_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
