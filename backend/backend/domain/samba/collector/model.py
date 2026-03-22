"""SambaWave Collector domain models - search filters and collected products."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_search_filter_id() -> str:
    return f"sf_{ULID()}"


def generate_collected_product_id() -> str:
    return f"cp_{ULID()}"


class SambaSearchFilter(SQLModel, table=True):
    """수집 필터 테이블 - 소싱처별 검색/수집 조건."""

    __tablename__ = "samba_search_filter"

    id: str = Field(
        default_factory=generate_search_filter_id,
        primary_key=True,
        max_length=30,
    )

    source_site: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )
    name: str = Field(sa_column=Column(Text, nullable=False))

    # 트리 구조
    parent_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )
    is_folder: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )

    keyword: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    category_filter: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 가격 범위
    min_price: Optional[float] = Field(default=None)
    max_price: Optional[float] = Field(default=None)

    # 필터 옵션
    exclude_sold_out: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )

    # 요청 상품수 (기본 100)
    requested_count: int = Field(
        default=100,
        sa_column=Column(Integer, nullable=False, server_default="100"),
    )

    # 적용 정책
    applied_policy_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 스마트스토어 브랜드/제조사 ID 매핑
    ss_brand_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    ss_brand_name: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    ss_manufacturer_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    ss_manufacturer_name: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 마지막 수집 시각
    last_collected_at: Optional[datetime] = Field(
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


class SambaCollectedProduct(SQLModel, table=True):
    """수집 상품 테이블 - 소싱처에서 수집한 원본 상품 데이터."""

    __tablename__ = "samba_collected_product"

    id: str = Field(
        default_factory=generate_collected_product_id,
        primary_key=True,
        max_length=30,
    )

    # 소싱 정보
    source_site: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )
    search_filter_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )
    site_product_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )

    # 기본 정보
    name: str = Field(sa_column=Column(Text, nullable=False))
    name_en: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    name_ja: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    brand: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 가격 정보
    original_price: float = Field(default=0)
    sale_price: float = Field(default=0)
    cost: Optional[float] = Field(default=None)

    # 이미지/옵션 (JSON)
    images: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    detail_images: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    video_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    options: Optional[List[Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 상세 설명
    detail_html: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 카테고리 계층
    category: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    category1: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    category2: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    category3: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    category4: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 상태: collected -> saved -> registered
    status: str = Field(
        default="collected",
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 정책/마켓 연동
    applied_policy_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    market_prices: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    market_enabled: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    registered_accounts: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    # 마켓별 등록된 상품번호: { "account_id": "product_no", ... }
    market_product_nos: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 품절/가격 변동 추적
    is_sold_out: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    price_before_change: Optional[float] = Field(default=None)
    price_changed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # 판매 상태: in_stock / sold_out / preorder
    sale_status: str = Field(
        default='in_stock',
        sa_column=Column(Text, nullable=False, server_default='in_stock'),
    )

    # 가격/재고 이력 (최신순 배열, 최대 200건)
    price_history: Optional[List[Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 잠금 플래그
    lock_delete: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    lock_stock: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )

    # 태그
    tags: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    # SEO 검색키워드 (상품명 조합용, 2-3개)
    seo_keywords: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 모니터링 우선순위: hot / warm / cold
    monitor_priority: str = Field(
        default='cold',
        sa_column=Column(Text, nullable=False, server_default='cold'),
    )
    # 마지막 갱신 시각
    last_refreshed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # 갱신 실패 횟수 (3회 초과 시 스케줄러 제외)
    refresh_error_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default='0')
    )

    # KREAM 특화 데이터
    kream_data: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 제조사/원산지/소재/색상
    manufacturer: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    origin: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    material: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    color: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    # 품번/성별/시즌
    style_code: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    sex: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    season: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    # 취급주의사항/품질보증기준
    care_instructions: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    quality_guarantee: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 배송 정보: 무료배송 / 당일발송
    free_shipping: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    same_day_delivery: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )

    # 마켓별 마지막 전송 스냅샷 (스킵 판단용)
    # { "계정ID": { "sale_price": 24469, "cost": 20000, "options": [...], "sent_at": "..." } }
    last_sent_data: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 그룹상품 관련
    group_key: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True, index=True))
    similar_no: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
    group_product_no: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
