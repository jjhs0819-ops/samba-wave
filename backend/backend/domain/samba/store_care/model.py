"""스토어케어 — 가구매 스케줄 + 이력 모델."""

from datetime import datetime, timezone
from typing import Optional

from ulid import ULID
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, Text, text
from sqlmodel import SQLModel, Field

UTC = timezone.utc


class StoreCareSchedule(SQLModel, table=True):
    """가구매 자동 스케줄."""

    __tablename__ = "store_care_schedules"

    id: str = Field(
        default_factory=lambda: f"scs_{ULID()}",
        sa_column=Column(String, primary_key=True),
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    market_type: str = Field(
        sa_column=Column(String(30), nullable=False)
    )  # smartstore, coupang 등
    account_id: str = Field(
        sa_column=Column(String, nullable=False)
    )  # SambaMarketAccount ID
    account_label: str = Field(
        default="", sa_column=Column(String, nullable=True)
    )  # 표시명

    # 스케줄 설정
    interval_hours: int = Field(
        default=6, sa_column=Column(Integer, default=6)
    )  # 실행 간격 (시간)
    daily_target: int = Field(
        default=3, sa_column=Column(Integer, default=3)
    )  # 일일 목표 건수
    daily_done: int = Field(
        default=0, sa_column=Column(Integer, default=0)
    )  # 오늘 완료 건수

    # 상품 선택 설정
    product_selection: str = Field(
        default="random", sa_column=Column(String(20), default="random")
    )  # random | specific | low_score
    product_ids: Optional[list] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )  # specific일 때 상품 ID 목록
    min_price: int = Field(default=10000, sa_column=Column(Integer, default=10000))
    max_price: int = Field(default=300000, sa_column=Column(Integer, default=300000))

    # 상태
    status: str = Field(
        default="scheduled",
        sa_column=Column(String(20), default="scheduled", index=True),
    )  # scheduled | running | paused
    next_run_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_run_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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


class StoreCarePurchase(SQLModel, table=True):
    """가구매 이력."""

    __tablename__ = "store_care_purchases"

    id: str = Field(
        default_factory=lambda: f"scp_{ULID()}",
        sa_column=Column(String, primary_key=True),
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    schedule_id: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )  # 스케줄 ID (수동이면 None)
    market_type: str = Field(sa_column=Column(String(30), nullable=False))
    account_id: str = Field(sa_column=Column(String, nullable=False))

    # 상품 정보
    product_id: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    product_name: str = Field(default="", sa_column=Column(Text, nullable=True))
    product_no: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )  # 마켓 상품번호

    # 구매 정보
    amount: int = Field(default=0, sa_column=Column(Integer, default=0))  # 구매 금액
    order_no: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )  # 마켓 주문번호
    buyer_account: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )  # 구매자 계정

    # 결과
    status: str = Field(
        default="pending", sa_column=Column(String(20), default="pending", index=True)
    )  # pending | completed | failed | cancelled
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), server_default=text("now()")),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class StoreCareMarketMetric(SQLModel, table=True):
    """마켓 판매자 점수·품절률 스냅샷 — 파트너/셀러 포털 스크래핑 결과.

    포털마다 노출 지표가 달라(SSG=평점/등급, 11번가=평점/패널티, GS샵=품절률)
    핵심 지표는 정규화 컬럼으로, 원시 전체는 metrics(JSON)로 보관한다.
    대시보드는 market_type별 최신 1건을 보여준다.
    """

    __tablename__ = "store_care_market_metrics"

    id: str = Field(
        default_factory=lambda: f"scm_{ULID()}",
        sa_column=Column(String, primary_key=True),
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    market_type: str = Field(
        sa_column=Column(String(30), nullable=False, index=True)
    )  # ssg | 11st | gsshop | ...
    account_id: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )  # SambaMarketAccount ID (선택)
    account_label: str = Field(default="", sa_column=Column(String, nullable=True))

    # ── 정규화 핵심 지표 (해당 없으면 NULL) ──
    soldout_rate: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )  # 품절률 % (예: GS샵 당월 9.7)
    soldout_rate_prev: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )  # 직전 기준 품절률 % (예: GS샵 전월 7.3) — 추세 판단용
    score: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )  # 대표 점수(서비스평점/주문이행 등) 0~100
    grade: Optional[str] = Field(
        default=None, sa_column=Column(String(30), nullable=True)
    )  # 판매등급/등급 라벨 (예: 웰컴)
    penalty: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )  # 패널티/경고 개수

    # ── 마켓별 상이한 원시 지표 전부 (에르메스 의사결정용 — 넓게 보관) ──
    metrics: Optional[dict] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )  # 파싱·라벨된 지표: {"주문이행":{"value":90.4,"level":"주의"}, "품절률_당월":9.7, ...}
    raw: Optional[dict] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )  # 포털에서 긁은 원시 값 전부 (DOM 변경 시 재파싱/디버깅/추후 지표 추출용)
    period_label: Optional[str] = Field(
        default=None, sa_column=Column(String(80), nullable=True)
    )  # 평가기간/기준 표시 (예: "2026.05.09~06.07", "당월")

    status: str = Field(
        default="ok", sa_column=Column(String(20), default="ok")
    )  # ok | failed
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    source_url: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )

    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True), index=True, server_default=text("now()")
        ),
    )
