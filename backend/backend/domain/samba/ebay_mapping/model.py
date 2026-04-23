"""eBay 매핑 도메인 모델 — 한글 → 영문 변환용."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, UniqueConstraint
from sqlmodel import Column, DateTime, Field, Index, SQLModel, Text
from ulid import ULID


def generate_ebay_mapping_id() -> str:
    return f"em_{ULID()}"


class SambaEbayMapping(SQLModel, table=True):
    """eBay 한/영 매핑 테이블.

    category: 'color' | 'material' | 'origin' | 'sex' | 'type'
    kr_value: 한글 원본 값 (예: '검정')
    en_value: 영문 변환 값 (예: 'Black')
    source: 'default' (시드) | 'ai' (Claude 자동 추가) | 'manual' (사용자 수동)
    """

    __tablename__ = "samba_ebay_mapping"
    __table_args__ = (
        UniqueConstraint("category", "kr_value", name="uq_sem_category_kr"),
        Index("ix_sem_category", "category"),
    )

    id: str = Field(
        default_factory=generate_ebay_mapping_id,
        primary_key=True,
        max_length=30,
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    category: str = Field(sa_column=Column(Text, nullable=False))
    kr_value: str = Field(sa_column=Column(Text, nullable=False))
    en_value: str = Field(sa_column=Column(Text, nullable=False))
    source: str = Field(
        default="default",
        sa_column=Column(Text, nullable=False, server_default="default"),
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
