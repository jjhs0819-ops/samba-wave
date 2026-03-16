"""SambaWave Policy DTOs."""

from typing import Any, Optional

from pydantic import BaseModel


class PolicyCreate(BaseModel):
    name: str = "새 정책"
    site_name: Optional[str] = None
    pricing: Optional[Any] = None
    market_policies: Optional[Any] = None


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    site_name: Optional[str] = None
    pricing: Optional[Any] = None
    market_policies: Optional[Any] = None


class PriceCalculateRequest(BaseModel):
    cost: float
    fee_rate: float = 0
