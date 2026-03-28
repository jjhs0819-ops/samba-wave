"""소싱처 계정 DTO."""

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
