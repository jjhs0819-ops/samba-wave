"""SambaWave Policy (가격정책) domain model."""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_policy_id() -> str:
    return f"pol_{ULID()}"


class SambaPolicy(SQLModel, table=True):
    """가격정책 테이블."""

    __tablename__ = "samba_policy"

    id: str = Field(
        default_factory=generate_policy_id,
        primary_key=True,
        max_length=30,
    )

    name: str = Field(
        default="새 정책",
        sa_column=Column(Text, nullable=False),
    )
    site_name: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 가격 계산 설정 (JSON)
    # {
    #   shippingCost, marginRate, marginAmount, useRangeMargin,
    #   rangeMargins: [{min, max, rate, amount}],
    #   extraCharge, minMarginAmount, discountRate, discountAmount, ...
    # }
    pricing: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 마켓별 정책 오버라이드 (JSON)
    market_policies: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
