"""SambaWave Collector DTOs."""

from typing import Any, List, Optional

from pydantic import BaseModel


class SearchFilterCreate(BaseModel):
    source_site: str
    name: str
    keyword: Optional[str] = None
    category_filter: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    exclude_sold_out: bool = True
    is_active: bool = True


class SearchFilterUpdate(BaseModel):
    name: Optional[str] = None
    keyword: Optional[str] = None
    category_filter: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    exclude_sold_out: Optional[bool] = None
    is_active: Optional[bool] = None


class CollectedProductCreate(BaseModel):
    source_site: str
    name: str
    search_filter_id: Optional[str] = None
    site_product_id: Optional[str] = None
    name_en: Optional[str] = None
    name_ja: Optional[str] = None
    brand: Optional[str] = None
    original_price: float = 0
    sale_price: float = 0
    cost: Optional[float] = None
    images: Optional[List[str]] = None
    options: Optional[List[Any]] = None
    detail_html: Optional[str] = None
    category: Optional[str] = None
    category1: Optional[str] = None
    category2: Optional[str] = None
    category3: Optional[str] = None
    category4: Optional[str] = None
    status: str = "collected"
    kream_data: Optional[Any] = None
    manufacturer: Optional[str] = None
    origin: Optional[str] = None


class CollectedProductUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    name_ja: Optional[str] = None
    brand: Optional[str] = None
    original_price: Optional[float] = None
    sale_price: Optional[float] = None
    cost: Optional[float] = None
    images: Optional[List[str]] = None
    options: Optional[List[Any]] = None
    detail_html: Optional[str] = None
    category: Optional[str] = None
    category1: Optional[str] = None
    category2: Optional[str] = None
    category3: Optional[str] = None
    category4: Optional[str] = None
    status: Optional[str] = None
    applied_policy_id: Optional[str] = None
    market_prices: Optional[Any] = None
    market_enabled: Optional[Any] = None
    registered_accounts: Optional[List[str]] = None
    market_product_nos: Optional[Any] = None
    is_sold_out: Optional[bool] = None
    kream_data: Optional[Any] = None
