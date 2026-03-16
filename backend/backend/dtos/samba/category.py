"""SambaWave Category DTOs."""

from typing import Any, Optional

from pydantic import BaseModel


class CategoryMappingCreate(BaseModel):
    source_site: str
    source_category: str
    target_mappings: Optional[Any] = None
    applied_policy_id: Optional[str] = None


class CategoryMappingUpdate(BaseModel):
    source_category: Optional[str] = None
    target_mappings: Optional[Any] = None
    applied_policy_id: Optional[str] = None


class CategoryTreeSave(BaseModel):
    cat1: Optional[list] = None
    cat2: Optional[Any] = None
    cat3: Optional[Any] = None
    cat4: Optional[Any] = None
