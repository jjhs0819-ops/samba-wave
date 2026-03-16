"""Authentication API endpoints."""

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.user.auth_service import AuthService, get_user_id
from backend.dtos.auth import (
    EmailLoginRequestDto,
    EmailSignUpRequestDto,
    LoginResponseDto,
    RefreshTokenRequestDto,
    RefreshTokenResponseDto,
)
from backend.dtos.user import UserInfoDto

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/email/sign-up", response_model=LoginResponseDto)
async def email_sign_up(
    request: EmailSignUpRequestDto,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> LoginResponseDto:
    """Sign up user with email and password."""
    auth_service = AuthService(session=session)
    return await auth_service.email_sign_up(request=request)


@router.post("/email/login", response_model=LoginResponseDto)
async def email_login(
    request: EmailLoginRequestDto,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> LoginResponseDto:
    """Login user with email and password."""
    auth_service = AuthService(session=session)
    return await auth_service.email_login(request=request)


@router.post("/refresh", response_model=RefreshTokenResponseDto)
async def refresh_token(
    request: RefreshTokenRequestDto,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> RefreshTokenResponseDto:
    """Refresh access token using refresh token."""
    auth_service = AuthService(session=session)
    return await auth_service.refresh_access_token(
        refresh_token=request.refresh_token
    )


@router.get("/me", response_model=UserInfoDto)
async def get_current_user(
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> UserInfoDto:
    """Get current user info."""
    from backend.core.config import settings

    # Mock mode
    if settings.mock_auth_enabled and user_id == "mock-user-001":
        return UserInfoDto(
            id="mock-user-001",
            nickname="Test User",
            email="test@example.com",
            auth_type="mock",
            is_admin=True,
            is_premium=False,
        )

    auth_service = AuthService(session=session)
    user_info = await auth_service.get_current_user_info(user_id)

    return UserInfoDto(
        id=user_info["id"],
        nickname=user_info["nickname"],
        email=user_info["email"],
        auth_type=user_info["auth_type"],
        is_admin=user_info["is_admin"],
        is_premium=user_info["is_premium"],
    )
