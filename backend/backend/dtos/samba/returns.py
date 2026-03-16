"""SambaWave Return DTOs."""

from typing import Optional

from pydantic import BaseModel


class ReturnCreate(BaseModel):
    order_id: str
    type: str  # return, exchange, cancel
    reason: Optional[str] = None
    description: Optional[str] = None
    quantity: int = 1
    requested_amount: Optional[float] = None


class ReturnRejectBody(BaseModel):
    reason: Optional[str] = None


class ReturnNoteBody(BaseModel):
    note: str
