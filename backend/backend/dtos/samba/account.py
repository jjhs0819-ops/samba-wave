"""SambaWave Account DTOs."""

from typing import Any, Optional

from pydantic import BaseModel


class MarketAccountCreate(BaseModel):
    market_type: str
    market_name: Optional[str] = None
    account_label: Optional[str] = None
    seller_id: Optional[str] = None
    business_name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    additional_fields: Optional[Any] = None
    is_active: bool = True


class MarketAccountUpdate(BaseModel):
    market_name: Optional[str] = None
    account_label: Optional[str] = None
    seller_id: Optional[str] = None
    business_name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    additional_fields: Optional[Any] = None
    is_active: Optional[bool] = None
