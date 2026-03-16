"""SambaWave Channel DTOs."""

from typing import Optional

from pydantic import BaseModel


class ChannelCreate(BaseModel):
    name: str
    type: str  # open-market, mall, resale, overseas
    platform: str
    fee_rate: Optional[float] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    platform: Optional[str] = None
    fee_rate: Optional[float] = None
    status: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
