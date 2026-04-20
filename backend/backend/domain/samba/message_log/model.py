"""SMS/카카오 발송 이력 도메인 모델."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, String
from sqlmodel import Column, DateTime, Field, SQLModel, Text

from ulid import ULID


def generate_message_log_id() -> str:
    return f"msg_{ULID()}"


class MessageLog(SQLModel, table=True):
    """SMS/카카오 발송 이력 테이블."""

    __tablename__ = "samba_message_log"

    id: str = Field(
        default_factory=generate_message_log_id,
        primary_key=True,
        max_length=30,
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )
    order_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, index=True, nullable=True)
    )
    customer_phone: Optional[str] = Field(
        default=None, sa_column=Column(Text, index=True, nullable=True)
    )
    message_type: str = Field(
        default="sms", sa_column=Column(Text, nullable=False, index=True)
    )
    template_raw: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    rendered_message: str = Field(sa_column=Column(Text, nullable=False))
    receiver: str = Field(sa_column=Column(Text, nullable=False))
    sent_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
        ),
    )
    success: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    result_message: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    msg_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
