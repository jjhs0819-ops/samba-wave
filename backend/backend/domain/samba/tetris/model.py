"""SambaWave Tetris 정책 배치 domain model."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String
from sqlmodel import Column, DateTime, Field, SQLModel

from ulid import ULID


def generate_tetris_assignment_id() -> str:
    """테트리스 배치 ID 생성."""
    return f"ta_{ULID()}"


class SambaTetrisAssignment(SQLModel, table=True):
    """테트리스 정책 배치 테이블 — 소싱처·브랜드를 마켓 계정에 배치하는 설정."""

    __tablename__ = "samba_tetris_assignment"

    id: str = Field(
        default_factory=generate_tetris_assignment_id,
        primary_key=True,
        max_length=36,
    )
    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String, index=True, nullable=True),
    )
    # 소싱처 코드 (MUSINSA, SSG, LOTTEON, GSSHOP 등)
    source_site: str = Field(
        sa_column=Column(String, index=True, nullable=False),
    )
    # 브랜드명
    brand_name: str = Field(
        sa_column=Column(String, nullable=False),
    )
    # 마켓 계정 ID (samba_market_account.id 참조)
    market_account_id: str = Field(
        sa_column=Column(String, index=True, nullable=False),
    )
    # 적용할 정책 ID (samba_policy.id 참조, 없으면 기본정책)
    policy_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )
    # 배치 순서 (같은 계정 내 정렬 기준)
    position_order: int = Field(default=0)

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
