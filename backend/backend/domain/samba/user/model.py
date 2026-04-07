"""삼바웨이브 사용자 모델 - 로그인 계정 관리."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, String
from sqlmodel import Column, DateTime, Field, SQLModel, Text

from ulid import ULID


def generate_samba_user_id() -> str:
    return f"su_{ULID()}"


def generate_login_history_id() -> str:
    return f"lh_{ULID()}"


class SambaUser(SQLModel, table=True):
    """삼바웨이브 사용자 테이블 - 이메일/비밀번호 인증 계정."""

    __tablename__ = "samba_user"

    id: str = Field(
        default_factory=generate_samba_user_id,
        primary_key=True,
        max_length=30,
    )
    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    # 역할: owner, admin, member
    role: str = Field(
        default="member", sa_column=Column(String, default="member", nullable=True)
    )

    # 인증 정보
    email: str = Field(
        sa_column=Column(Text, nullable=False, unique=True, index=True),
    )
    password_hash: str = Field(
        sa_column=Column(Text, nullable=False),
    )

    # 기본 정보
    name: str = Field(sa_column=Column(Text, nullable=False))

    # 권한/상태
    is_admin: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    status: str = Field(
        default="active",
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 타임스탬프
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True),
        default=None,
    )


class SambaLoginHistory(SQLModel, table=True):
    """로그인 이력 테이블."""

    __tablename__ = "samba_login_history"

    id: str = Field(
        default_factory=generate_login_history_id,
        primary_key=True,
        max_length=30,
    )
    user_id: str = Field(sa_column=Column(Text, nullable=False, index=True))
    email: str = Field(sa_column=Column(Text, nullable=False))
    ip_address: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    region: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    user_agent: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
