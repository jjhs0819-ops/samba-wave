"""
User domain DTOs.

Request and response DTOs for User API endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from backend.domain.user.enums import (
    AuthTypeEnum,
    GenderEnum,
    UserStatusEnum,
)


# ============================================================
# Request DTOs
# ============================================================


class UserCreateRequest(BaseModel):
    """Request to create a new user."""

    phone: str = Field(
        ...,
        description="Phone number",
        min_length=10,
        max_length=15,
    )
    name: str = Field(
        ...,
        description="User's name",
        min_length=2,
        max_length=50,
    )
    gender: GenderEnum = Field(..., description="User gender")
    auth_type: AuthTypeEnum = Field(
        default=AuthTypeEnum.PHONE,
        description="Authentication type",
    )


class UserUpdateRequest(BaseModel):
    """Request to update user information."""

    name: Optional[str] = Field(None, min_length=2, max_length=50)
    status: Optional[UserStatusEnum] = None


class UserSearchRequest(BaseModel):
    """Search filters for users."""

    query: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = None
    gender: Optional[str] = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


# ============================================================
# Response DTOs
# ============================================================


class UserSummaryResponse(BaseModel):
    """Minimal user response for lists."""

    id: str
    name: str
    gender: Optional[GenderEnum] = None
    phone: str
    status: UserStatusEnum
    created_at: datetime


class UserResponse(BaseModel):
    """Full user response."""

    id: str
    firebase_id: Optional[str] = None
    phone: str
    name: str
    gender: Optional[GenderEnum] = None
    auth_type: AuthTypeEnum
    status: UserStatusEnum
    created_at: datetime
    updated_at: datetime

    # Related data (simplified - always None for now)
    profile: Optional[dict] = None
    lifestyle: Optional[dict] = None
    preference: Optional[dict] = None
    subscription: Optional[dict] = None

    # Counts
    photo_count: int = Field(default=0)
    document_count: int = Field(default=0)


class UserListResponse(BaseModel):
    """Paginated list of users."""

    users: list[UserSummaryResponse]
    total: int
    skip: int
    limit: int


# ============================================================
# Auth Info DTO
# ============================================================


class UserInfoDto(BaseModel):
    """User info for auth endpoints."""

    id: str
    nickname: str
    email: Optional[str] = None
    auth_type: str
    is_admin: bool = False
    is_premium: bool = False
