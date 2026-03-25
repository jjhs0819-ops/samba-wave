"""SambaWave CS 문의 DTOs."""

from typing import List, Optional

from pydantic import BaseModel


class CSInquiryCreate(BaseModel):
    market: str
    market_order_id: Optional[str] = None
    account_name: Optional[str] = None
    inquiry_type: str = "general"
    questioner: Optional[str] = None
    product_name: Optional[str] = None
    product_image: Optional[str] = None
    product_link: Optional[str] = None
    market_link: Optional[str] = None
    original_link: Optional[str] = None
    content: str
    inquiry_date: Optional[str] = None


class CSInquiryReply(BaseModel):
    reply: str


class CSInquiryBatchDelete(BaseModel):
    ids: List[str]
