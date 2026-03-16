"""Authentication DTOs for request/response validation."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class EmailLoginRequestDto(BaseModel):
    """Request DTO for email/password login."""

    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., min_length=6, description="User password")


class EmailSignUpRequestDto(BaseModel):
    """Request DTO for email/password signup."""

    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., min_length=6, description="User password")
    username: str = Field(..., min_length=2, max_length=50, description="Username")


class LoginResponseDto(BaseModel):
    """Response DTO for successful login."""

    user_id: str = Field(..., description="User ID")
    app_auth_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    nickname: Optional[str] = Field(None, description="User nickname")


class RefreshTokenRequestDto(BaseModel):
    """Request DTO for token refresh."""

    refresh_token: str = Field(..., description="JWT refresh token")


class RefreshTokenResponseDto(BaseModel):
    """Response DTO for token refresh."""

    app_auth_token: str = Field(..., description="New JWT access token")
    refresh_token: str = Field(..., description="New JWT refresh token")
