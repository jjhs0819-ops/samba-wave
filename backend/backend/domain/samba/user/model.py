"""삼바웨이브 사용자 모델 - 로그인 계정 관리."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean
from sqlmodel import Column, DateTime, Field, SQLModel, Text

from ulid import ULID


def generate_samba_user_id() -> str:
  return f"su_{ULID()}"


class SambaUser(SQLModel, table=True):
  """삼바웨이브 사용자 테이블 - 이메일/비밀번호 인증 계정."""

  __tablename__ = "samba_user"

  id: str = Field(
    default_factory=generate_samba_user_id,
    primary_key=True,
    max_length=30,
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
