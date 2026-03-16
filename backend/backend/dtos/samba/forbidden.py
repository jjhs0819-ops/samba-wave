"""SambaWave Forbidden word DTOs."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ForbiddenWordCreate(BaseModel):
    word: str
    type: str = "forbidden"  # 'forbidden' | 'deletion'
    scope: str = "title"  # 'title' | 'description' | 'both'
    group_id: Optional[str] = None
    is_active: bool = True


class ForbiddenWordUpdate(BaseModel):
    word: Optional[str] = None
    type: Optional[str] = None
    scope: Optional[str] = None
    group_id: Optional[str] = None
    is_active: Optional[bool] = None


class ProductValidateRequest(BaseModel):
    """Request body for validating product(s) against forbidden/deletion words."""

    products: List[Dict[str, Any]]
