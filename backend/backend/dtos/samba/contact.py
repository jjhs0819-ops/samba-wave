"""SambaWave Contact DTOs."""

from typing import Optional

from pydantic import BaseModel


class ContactCreate(BaseModel):
    order_id: Optional[str] = None
    type: str  # sms, kakao, email
    recipient: Optional[str] = None
    template: Optional[str] = None
    custom_message: Optional[str] = None
    message: Optional[str] = None
