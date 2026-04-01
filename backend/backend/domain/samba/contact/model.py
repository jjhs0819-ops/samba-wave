"""SambaWave Contact Log domain model."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Column, DateTime, Field, SQLModel, Text

from ulid import ULID


def generate_contact_id() -> str:
    return f"con_{ULID()}"


class SambaContactLog(SQLModel, table=True):
    """연락 로그 테이블 - SMS/카카오/이메일 발송 기록."""

    __tablename__ = "samba_contact_log"

    id: str = Field(
        default_factory=generate_contact_id,
        primary_key=True,
        max_length=30,
    )

    # 연결 정보
    order_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )

    # 발송 유형: sms, kakao, email
    type: str = Field(sa_column=Column(Text, nullable=False))

    # 수신자
    recipient: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 템플릿 이름
    template: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 사용자 커스텀 메시지
    custom_message: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 최종 발송 메시지
    message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 상태: pending, sent, failed
    status: str = Field(
        default="pending",
        sa_column=Column(Text, nullable=False, index=True),
    )

    # 발송/읽음 시각
    sent_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    read_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Timestamp
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
