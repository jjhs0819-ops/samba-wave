"""
User API endpoints for user management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.user.service import UserService
from backend.dtos.user import (
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserSearchRequest,
    UserUpdateRequest,
)
from backend.error import NotFoundError

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserListResponse)
async def list_users(
    query: str = Query(None, description="Search in name or phone"),
    status: str = Query(None, description="Filter by status"),
    gender: str = Query(None, description="Filter by gender"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> UserListResponse:
    """List users with pagination."""
    service = UserService(session)
    request = UserSearchRequest(
        query=query,
        status=status,
        gender=gender,
        skip=skip,
        limit=limit,
    )
    return await service.list_users(request)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> UserResponse:
    """Get user by ID."""
    service = UserService(session)
    try:
        return await service.get_user(user_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    request: UserCreateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> UserResponse:
    """Create a new user."""
    service = UserService(session)
    try:
        return await service.create_user(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> UserResponse:
    """Update user information."""
    service = UserService(session)
    try:
        return await service.update_user(user_id, request)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> None:
    """Soft delete a user."""
    service = UserService(session)
    result = await service.delete_user(user_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
