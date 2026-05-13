"""SambaWave Order domain model."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index, String, text
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
    __table_args__ = (
        Index("uq_order_tenant_number", "tenant_id", "order_number", unique=True),
        Index(
            "ix_samba_order_lotteon_line",
            "tenant_id",
            "channel_id",
            "od_no",
            "od_seq",
            unique=True,
            postgresql_where=text("source = 'lotteon'"),
        ),
        Index("ix_samba_order_tenant_paid_at", "tenant_id", "paid_at"),
    )

    id: str = Field(
        default_factory=generate_order_id,
        primary_key=True,
        max_length=30,
    )
    # 테넌트 격리
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    order_number: str = Field(
        default_factory=generate_order_number,
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 연결 정보
    channel_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )
    channel_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    product_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )
    product_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    product_image: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    product_option: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    coupang_display_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    source_url: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    source_site: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # 수집상품 직접 참조 (근본적 연결)
    collected_product_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )

    # 고객 정보
    customer_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # 주문자명 (수취인 customer_name과 다를 수 있음 — 선물하기 등)
    orderer_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    customer_phone: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    customer_address: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # 상세주소(동/호/층 등) — 마켓 API가 base/detail 분리 제공하는 경우 별도 저장
    # 분리 미제공 마켓(eBay, 플레이오토 EMP)은 NULL 유지하고 customer_address에 단일 문자열 저장
    customer_address_detail: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 수량/금액
    quantity: int = Field(default=1)
    sale_price: float = Field(default=0)
    # 고객결제금액 (할인 적용 후 실제 고객이 결제한 금액)
    # 롯데ON: slAmt - fvrAmtSum
    # 다른 마켓: 미설정 시 sale_price 폴백 사용 (UI 단)
    total_payment_amount: Optional[float] = Field(default=None)
    cost: float = Field(default=0)
    shipping_fee: float = Field(default=0)
    fee_rate: float = Field(default=0)
    revenue: float = Field(default=0)
    profit: float = Field(default=0)
    profit_rate: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

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
    return_status: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 배송 정보
    shipping_company: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    tracking_number: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    customer_note: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 타마켓 주문번호
    ext_order_number: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 소싱처 구매주문번호
    sourcing_order_number: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 소싱처 주문계정 ID
    sourcing_account_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 액션 태그 (no_price/no_stock/direct/kkadaegi/gift)
    action_tag: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 롯데ON 라인 키 (동일 주문 내 다른 옵션 식별)
    od_no: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    od_seq: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    proc_seq: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    sitm_no: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 11번가 라인 키 (판매불가처리/취소승인 등 클레임 API 필수 파라미터)
    ord_prd_seq: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 출처
    source: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    shipment_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 고객 결제시간 (대시보드/날짜 범위 조회의 핵심 필터 — 인덱스 필수)
    paid_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
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
    shipped_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    delivered_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


# 송장수집·진행현황 모달에서 "취소/반품/교환"으로 분류해 제외하는 status 영문 enum 집합.
# 페이지 필터 "취소/반품/교환 제외"가 사용하는 기준과 동일.
EXCLUDED_ORDER_STATUSES: tuple[str, ...] = (
    "cancel_requested",
    "cancelling",
    "cancelled",
    "return_requested",
    "returning",
    "returned",
    "return_completed",
    "exchange_requested",
    "exchanging",
    "exchanged",
    "exchange_pending",
    "exchange_done",
    "ship_failed",
    "undeliverable",
)

# 배송이 이미 진행/종료된 단계 — shipping_status(마켓 원본 한글)에 이 키워드 포함 시 제외.
SHIPPED_SHIPPING_STATUS_KEYWORDS: tuple[str, ...] = ("배송중", "배송완료")
