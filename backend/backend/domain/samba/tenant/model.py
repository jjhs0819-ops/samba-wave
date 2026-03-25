"""테넌트(고객사) 모델 — 멀티테넌시 SaaS 기반."""

from datetime import datetime, timezone
from typing import Optional

import ulid
from sqlalchemy import Column, String, Boolean, JSON, DateTime, text
from sqlmodel import SQLModel, Field


UTC = timezone.utc


class SambaTenant(SQLModel, table=True):
    """테넌트(고객사) — 각 고객의 데이터 격리 단위."""
    __tablename__ = "samba_tenants"

    id: str = Field(
        default_factory=lambda: f"tn_{ulid.new().str}",
        sa_column=Column(String, primary_key=True),
    )
    name: str = Field(sa_column=Column(String, nullable=False))  # 사업자명
    owner_user_id: str = Field(default="", sa_column=Column(String, nullable=False))  # 최초 생성 User ID
    plan: str = Field(default="free", sa_column=Column(String, nullable=False))  # free / basic / pro / enterprise
    limits: Optional[dict] = Field(
        default_factory=lambda: {
            "max_products": 1000,
            "max_markets": 3,
            "max_sourcing": 2,
        },
        sa_column=Column(JSON, nullable=True),
    )
    is_active: bool = Field(default=True, sa_column=Column(Boolean, default=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), server_default=text("now()")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), server_default=text("now()")),
    )
