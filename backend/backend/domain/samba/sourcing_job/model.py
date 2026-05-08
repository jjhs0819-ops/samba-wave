"""소싱 잡 영속화 모델 — 인-메모리 SourcingQueue 의 DB 백킹.

Context:
    proxy.sourcing_queue.SourcingQueue 는 현재 프로세스 메모리에만 잡/Future 를 보관한다.
    배포·OOM·crash 시 in-flight 잡이 영구 대기되어 확장앱이 결과를 보내도 resolver 가
    사라져 데이터가 유실되는 단일 장애점이 있다.

    이 모델은 영속화 전환 1단계 — "테이블만 추가, 동작 미변경".
    실제 SourcingQueue 가 이 테이블을 쓰는 dual-write/read 전환은 후속 PR.

    상태 전이: pending → dispatched(확장앱이 받아감) → completed | failed | expired
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON
from sqlmodel import Field, SQLModel

UTC = timezone.utc


class SambaSourcingJob(SQLModel, table=True):
    """확장앱 기반 소싱 잡 영속화 — request_id 기준."""

    __tablename__ = "samba_sourcing_job"

    request_id: str = Field(
        sa_column=Column(String(64), primary_key=True),
    )
    site: str = Field(
        sa_column=Column(String(32), nullable=False, index=True),
    )
    job_type: str = Field(
        default="detail",
        sa_column=Column(String(32), nullable=False),
    )  # detail | search | category-scan
    status: str = Field(
        default="pending",
        sa_column=Column(String(20), nullable=False, index=True),
    )  # pending | dispatched | completed | failed | expired
    owner_device_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True, index=True),
    )
    payload: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    result: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    error: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    attempt: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, default=0, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    dispatched_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
