"""소싱처 계정 DTO."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class SourcingAccountCreate(BaseModel):
    site_name: str
    account_label: str
    username: str
    password: str
    chrome_profile: Optional[str] = None
    memo: Optional[str] = None
    additional_fields: Optional[Any] = None


class SourcingAccountUpdate(BaseModel):
    account_label: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    chrome_profile: Optional[str] = None
    memo: Optional[str] = None
    is_active: Optional[bool] = None
    additional_fields: Optional[Any] = None


class SourcingAccountOut(BaseModel):
    """소싱처 계정 응답 DTO — password 마스킹."""

    id: str
    tenant_id: Optional[str] = None
    site_name: str
    account_label: str
    username: str
    password: str  # 마스킹된 값
    chrome_profile: Optional[str] = None
    memo: Optional[str] = None
    balance: Optional[float] = None
    balance_updated_at: Optional[datetime] = None
    is_active: bool = True
    additional_fields: Optional[Any] = None
    created_at: datetime
    updated_at: datetime
