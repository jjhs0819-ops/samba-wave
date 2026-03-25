"""SambaWave Wholesale domain models - 도매몰 수집 상품 데이터."""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Integer, String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_ws_id() -> str:
    return f"ws_{ULID()}"


class SambaWholesaleProduct(SQLModel, table=True):
    """도매몰 상품 테이블 - domeme/ownerclan 등에서 수집한 도매 상품 데이터."""

    __tablename__ = "samba_wholesale_product"

    id: str = Field(
        default_factory=generate_ws_id,
        primary_key=True,
        max_length=30,
    )

    # 테넌트 격리
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True, nullable=True))

    # 도매몰 구분: domeme, ownerclan
    source_mall: str = Field(
        sa_column=Column(String(50), nullable=False, index=True),
    )

    # 도매몰 상품 ID
    product_id: str = Field(
        sa_column=Column(String(100), nullable=False, index=True),
    )

    # 상품 기본 정보
    name: str = Field(sa_column=Column(Text, nullable=False))

    # 도매가
    price: int = Field(
        sa_column=Column(Integer, nullable=False),
    )

    # 소비자가
    retail_price: int = Field(
        sa_column=Column(Integer, nullable=False),
    )

    # 카테고리
    category: Optional[str] = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )

    # 대표 이미지 URL
    image_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 상품 상세 페이지 URL
    detail_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 옵션 데이터 (색상/사이즈 등)
    options: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 재고 상태: in_stock / sold_out / preorder
    stock_status: str = Field(
        default="in_stock",
        sa_column=Column(String(20), nullable=False, server_default="in_stock"),
    )

    # 수집 시각
    collected_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )

    # 마지막 업데이트 시각
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
