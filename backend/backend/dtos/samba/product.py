"""SambaWave Product DTOs."""

from typing import Any, List, Optional

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    name_ja: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    source_url: Optional[str] = None
    source_site: Optional[str] = None
    site_product_id: Optional[str] = None
    source_price: float = 0
    cost: float = 0
    margin_rate: float = 30
    sale_price: Optional[float] = None
    images: Optional[List[str]] = None
    options: Optional[List[Any]] = None
    category1: Optional[str] = None
    category2: Optional[str] = None
    category3: Optional[str] = None
    category4: Optional[str] = None
    status: str = "active"


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    name_ja: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    source_price: Optional[float] = None
    cost: Optional[float] = None
    margin_rate: Optional[float] = None
    sale_price: Optional[float] = None
    images: Optional[List[str]] = None
    options: Optional[List[Any]] = None
    status: Optional[str] = None
    applied_policy_id: Optional[str] = None
    market_prices: Optional[Any] = None
    market_enabled: Optional[Any] = None
