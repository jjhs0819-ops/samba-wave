"""주문건 소싱처 최저가 스캔 결과 모델."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlmodel import Boolean, Column, DateTime, Field, JSON, SQLModel, String, Text

from ulid import ULID


def generate_price_scan_id() -> str:
    return f"pscan_{ULID()}"


class SambaOrderPriceScan(SQLModel, table=True):
    """주문건 소싱처 최저가 스캔 캐시 테이블.

    주문 1건당 1행(order_id unique). 재스캔 시 upsert 로 갱신한다.
    """

    __tablename__ = "samba_order_price_scan"

    id: str = Field(
        default_factory=generate_price_scan_id,
        primary_key=True,
        max_length=40,
    )

    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 연결 주문 (주문 1건당 스캔 1행)
    order_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True, unique=True),
    )

    # 상품명에서 추출한 모델코드(품번)
    model_code: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 스캔 시점의 소싱 원가 (order.cost)
    base_cost: Optional[float] = Field(default=None)

    # 전체 최저가 사이트/가격/링크
    best_site: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    best_price: Optional[float] = Field(default=None)
    best_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 사이트별 최저가 목록 [{site, price, name, url, product_id}]
    results: Optional[List[Any]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 오매칭 의심 (best_price < base_cost * 0.5)
    suspect: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, default=False)
    )

    # 스캔 실패 사유 (전 사이트 실패 등)
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 스캔 수행 시각 (캐시 24시간 판정 기준)
    scanned_at: Optional[datetime] = Field(
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
