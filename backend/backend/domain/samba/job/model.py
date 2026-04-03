"""작업 큐 모델 — 전송/수집/갱신 비동기 잡."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import ulid
from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, text
from sqlmodel import SQLModel, Field

UTC = timezone.utc


class JobStatus(str, Enum):
    """잡 상태 열거형 — DB 값과 1:1 매핑."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def generate_job_id() -> str:
    return f"job_{ulid.ULID()}"


class SambaJob(SQLModel, table=True):
    """비동기 작업 큐."""

    __tablename__ = "samba_jobs"

    id: str = Field(
        default_factory=generate_job_id,
        sa_column=Column(String, primary_key=True),
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    job_type: str = Field(
        sa_column=Column(String(30), nullable=False, index=True)
    )  # transmit | collect | refresh | ai_tag
    status: str = Field(
        default=JobStatus.PENDING,
        sa_column=Column(
            String(20),
            nullable=False,
            index=True,
            server_default=JobStatus.PENDING.value,
        ),
    )  # pending → running → completed | failed | cancelled
    payload: Optional[dict] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=True)
    )
    result: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    progress: int = Field(default=0, sa_column=Column(Integer, default=0))
    total: int = Field(default=0, sa_column=Column(Integer, default=0))
    current: int = Field(default=0, sa_column=Column(Integer, default=0))
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), server_default=text("now()")),
    )
    started_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
