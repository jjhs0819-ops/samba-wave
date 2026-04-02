"""SambaWave Channel (판매처) domain model."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_channel_id() -> str:
    return f"ch_{ULID()}"


class SambaChannel(SQLModel, table=True):
    """판매처 테이블."""

    __tablename__ = "samba_channel"

    id: str = Field(
        default_factory=generate_channel_id,
        primary_key=True,
        max_length=30,
    )

    name: str = Field(sa_column=Column(Text, nullable=False))
    type: str = Field(
        sa_column=Column(Text, nullable=False),
    )  # open-market, mall, resale, overseas
    platform: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )  # coupang, 11st, ssg, etc.
    fee_rate: float = Field(default=0)

    # 연동 상품 목록 (JSON)
    products: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    status: str = Field(
        default="active",
        sa_column=Column(Text, nullable=False),
    )

    # API 키 (암호화 필요시 별도 처리)
    api_key: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    api_secret: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
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
