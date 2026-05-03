from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, JSON
from sqlmodel import Column, Field, SQLModel


class SourcingRecipe(SQLModel, table=True):
    __tablename__ = "sourcing_recipes"

    id: int | None = Field(default=None, primary_key=True)
    site_name: str = Field(max_length=50, unique=True, index=True)
    version: str = Field(max_length=20)
    steps: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(default=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
