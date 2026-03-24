"""SambaWave Category domain models - category mappings and trees."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_category_mapping_id() -> str:
    return f"cm_{ULID()}"


class SambaCategoryMapping(SQLModel, table=True):
    """카테고리 매핑 테이블 - 소싱처 카테고리를 마켓별 카테고리로 매핑."""

    __tablename__ = "samba_category_mapping"

    id: str = Field(
        default_factory=generate_category_mapping_id,
        primary_key=True,
        max_length=30,
    )
    # 테넌트 격리
    tenant_id: Optional[str] = Field(default=None, sa_column=Column(String, index=True, nullable=True))

    source_site: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )
    source_category: str = Field(sa_column=Column(Text, nullable=False))

    # 마켓별 매핑: { marketName: categoryPath }
    target_mappings: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    applied_policy_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class SambaCategoryTree(SQLModel, table=True):
    """카테고리 트리 테이블 - 사이트별 카테고리 계층 구조 캐시."""

    __tablename__ = "samba_category_tree"

    site_name: str = Field(primary_key=True)

    # 카테고리 계층 (JSON)
    # cat1: ["대분류1", "대분류2", ...]
    cat1: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    # cat2: 마켓별 용도 다름
    # - 11st: {경로문자열: 숫자코드} 매핑 딕셔너리 (예: {"패션 > 남성의류": "12345"})
    # - 기타: { "대분류1": ["중분류1", "중분류2"], ... }
    cat2: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    # cat3: { "중분류1": ["소분류1", "소분류2"], ... }
    cat3: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    # cat4: { "소분류1": ["세분류1", "세분류2"], ... }
    cat4: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Timestamp
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
