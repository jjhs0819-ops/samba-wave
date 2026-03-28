"""소싱처 계정 모델."""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text

from ulid import ULID


def generate_sourcing_account_id() -> str:
    return f"sa_{ULID()}"


SUPPORTED_SOURCING_SITES = [
    {"id": "MUSINSA", "name": "무신사", "group": "패션"},
    {"id": "KREAM", "name": "크림", "group": "리셀"},
    {"id": "Nike", "name": "나이키", "group": "스포츠"},
    {"id": "Adidas", "name": "아디다스", "group": "스포츠"},
    {"id": "ABCmart", "name": "ABC마트", "group": "신발"},
    {"id": "OliveYoung", "name": "올리브영", "group": "뷰티"},
    {"id": "FashionPlus", "name": "패션플러스", "group": "패션"},
    {"id": "GMARKET", "name": "G마켓", "group": "오픈마켓"},
    {"id": "LOTTEON", "name": "롯데ON", "group": "오픈마켓"},
    {"id": "GSShop", "name": "GS샵", "group": "오픈마켓"},
    {"id": "SSG", "name": "SSG", "group": "오픈마켓"},
    {"id": "DANAWA", "name": "다나와", "group": "가격비교"},
]


class SambaSourcingAccount(SQLModel, table=True):
    """소싱처 로그인 계정 테이블."""

    __tablename__ = "samba_sourcing_account"

    id: str = Field(
        default_factory=generate_sourcing_account_id,
        primary_key=True,
        max_length=30,
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    site_name: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )
    account_label: str = Field(sa_column=Column(Text, nullable=False))
    username: str = Field(sa_column=Column(Text, nullable=False))
    password: str = Field(sa_column=Column(Text, nullable=False))
    chrome_profile: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    memo: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    balance: Optional[float] = Field(default=None)
    balance_updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true", index=True)
    )
    additional_fields: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
