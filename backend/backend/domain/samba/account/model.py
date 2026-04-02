"""SambaWave Account domain model - market seller accounts."""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_market_account_id() -> str:
    return f"ma_{ULID()}"


class SambaMarketAccount(SQLModel, table=True):
    """마켓 계정 테이블 - 판매처별 셀러 계정 정보."""

    __tablename__ = "samba_market_account"

    id: str = Field(
        default_factory=generate_market_account_id,
        primary_key=True,
        max_length=30,
    )
    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 마켓 구분
    market_type: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )  # auction, gmarket, 11st, coupang, kream, etc.
    market_name: str = Field(sa_column=Column(Text, nullable=False))
    account_label: str = Field(sa_column=Column(Text, nullable=False))

    # 셀러 정보
    seller_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )
    business_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # API 인증 (암호화 필요시 별도 처리)
    api_key: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    api_secret: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 추가 설정 (JSON)
    additional_fields: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true", index=True),
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
