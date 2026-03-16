"""SambaWave Return domain model."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_return_id() -> str:
    return f"ret_{ULID()}"


class SambaReturn(SQLModel, table=True):
    """반품/교환/취소 테이블."""

    __tablename__ = "samba_return"

    id: str = Field(
        default_factory=generate_return_id,
        primary_key=True,
        max_length=30,
    )

    # 연결 주문
    order_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 유형: return, exchange, cancel
    type: str = Field(sa_column=Column(Text, nullable=False))

    # 사유
    reason: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 상세 설명
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 수량
    quantity: int = Field(default=1)

    # 환불 요청 금액
    requested_amount: Optional[float] = Field(default=None)

    # 상태: requested, approved, rejected, completed, cancelled
    status: str = Field(
        default="requested",
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 승인/완료 일시
    approval_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completion_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # 메모 [{date, message}]
    notes: Optional[List[Any]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 타임라인 [{date, status, message}]
    timeline: Optional[List[Any]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
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
