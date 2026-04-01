"""SambaWave Shipment domain model - product update and market transmission."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_shipment_id() -> str:
    return f"shp_{ULID()}"


class SambaShipment(SQLModel, table=True):
    """전송 테이블 - 상품 업데이트 및 마켓 전송 작업."""

    __tablename__ = "samba_shipment"

    id: str = Field(
        default_factory=generate_shipment_id,
        primary_key=True,
        max_length=30,
    )
    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 대상 상품
    product_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 전송 대상 계정 목록
    target_account_ids: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 업데이트 항목: ['price', 'stock', 'image', 'description']
    update_items: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 상태: pending -> updating -> transmitting -> completed | partial | failed
    status: str = Field(
        default="pending",
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 업데이트 결과 (JSON)
    update_result: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 전송 결과: { accountId: 'success' | 'failed' }
    transmit_result: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    transmit_error: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 카테고리 매핑 (JSON)
    mapped_categories: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 롯데ON 전용 상세 (JSON)
    lotte_details: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 에러 메시지
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 완료 시각
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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
