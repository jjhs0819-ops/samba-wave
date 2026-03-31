"""SambaWave Order domain model."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String
from sqlmodel import Column, DateTime, Field, SQLModel, Text

from ulid import ULID


def generate_order_id() -> str:
    return f"ord_{ULID()}"


def generate_order_number() -> str:
    now = datetime.now(tz=timezone.utc)
    date_part = now.strftime("%y%m%d%H%M")
    import random
    rand_part = str(random.randint(0, 999)).zfill(3)
    return f"{date_part}{rand_part}"


class SambaOrder(SQLModel, table=True):
    """주문 테이블."""

    __tablename__ = "samba_order"

    id: str = Field(
        default_factory=generate_order_id,
        primary_key=True,
        max_length=30,
    )
    # 테넌트 격리
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True, nullable=True))

    order_number: str = Field(
        default_factory=generate_order_number,
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 연결 정보
    channel_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True, index=True))
    channel_name: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    product_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True, index=True))
    product_name: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    product_image: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    product_option: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    coupang_display_name: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    source_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    source_site: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 고객 정보
    customer_name: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    customer_phone: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    customer_address: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 수량/금액
    quantity: int = Field(default=1)
    sale_price: float = Field(default=0)
    cost: float = Field(default=0)
    shipping_fee: float = Field(default=0)
    fee_rate: float = Field(default=0)
    revenue: float = Field(default=0)
    profit: float = Field(default=0)
    profit_rate: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 상태
    status: str = Field(
        default="pending",
        sa_column=Column(Text, nullable=False, index=True),
    )
    payment_status: str = Field(
        default="completed",
        sa_column=Column(Text, nullable=False),
    )
    shipping_status: str = Field(
        default="preparing",
        sa_column=Column(Text, nullable=False),
    )
    return_status: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 배송 정보
    shipping_company: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    tracking_number: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 타마켓 주문번호
    ext_order_number: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 소싱처 구매주문번호
    sourcing_order_number: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 소싱처 주문계정 ID
    sourcing_account_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 출처
    source: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    shipment_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    shipped_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    delivered_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
