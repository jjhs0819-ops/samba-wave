"""스토어케어 — 가구매 스케줄 + 이력 모델."""

from datetime import datetime, timezone
from typing import Optional

import ulid
from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON, Text, text
from sqlmodel import SQLModel, Field

UTC = timezone.utc


class StoreCareSchedule(SQLModel, table=True):
    """가구매 자동 스케줄."""
    __tablename__ = "store_care_schedules"

    id: str = Field(
        default_factory=lambda: f"scs_{ulid.new().str}",
        sa_column=Column(String, primary_key=True),
    )
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True, nullable=True))
    market_type: str = Field(sa_column=Column(String(30), nullable=False))  # smartstore, coupang 등
    account_id: str = Field(sa_column=Column(String, nullable=False))  # SambaMarketAccount ID
    account_label: str = Field(default="", sa_column=Column(String, nullable=True))  # 표시명

    # 스케줄 설정
    interval_hours: int = Field(default=6, sa_column=Column(Integer, default=6))  # 실행 간격 (시간)
    daily_target: int = Field(default=3, sa_column=Column(Integer, default=3))  # 일일 목표 건수
    daily_done: int = Field(default=0, sa_column=Column(Integer, default=0))  # 오늘 완료 건수

    # 상품 선택 설정
    product_selection: str = Field(default="random", sa_column=Column(String(20), default="random"))  # random | specific | low_score
    product_ids: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))  # specific일 때 상품 ID 목록
    min_price: int = Field(default=10000, sa_column=Column(Integer, default=10000))
    max_price: int = Field(default=300000, sa_column=Column(Integer, default=300000))

    # 상태
    status: str = Field(default="scheduled", sa_column=Column(String(20), default="scheduled", index=True))  # scheduled | running | paused
    next_run_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_run_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    is_active: bool = Field(default=True, sa_column=Column(Boolean, default=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), server_default=text("now()")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), server_default=text("now()")),
    )


class StoreCarePurchase(SQLModel, table=True):
    """가구매 이력."""
    __tablename__ = "store_care_purchases"

    id: str = Field(
        default_factory=lambda: f"scp_{ulid.new().str}",
        sa_column=Column(String, primary_key=True),
    )
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True, nullable=True))
    schedule_id: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))  # 스케줄 ID (수동이면 None)
    market_type: str = Field(sa_column=Column(String(30), nullable=False))
    account_id: str = Field(sa_column=Column(String, nullable=False))

    # 상품 정보
    product_id: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    product_name: str = Field(default="", sa_column=Column(Text, nullable=True))
    product_no: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))  # 마켓 상품번호

    # 구매 정보
    amount: int = Field(default=0, sa_column=Column(Integer, default=0))  # 구매 금액
    order_no: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))  # 마켓 주문번호
    buyer_account: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))  # 구매자 계정

    # 결과
    status: str = Field(default="pending", sa_column=Column(String(20), default="pending", index=True))  # pending | completed | failed | cancelled
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), server_default=text("now()")),
    )
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True),
    )
