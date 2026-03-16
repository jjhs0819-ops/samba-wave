"""
User domain service with business logic for user management.
"""

from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.user.enums import UserStatusEnum
from backend.domain.user.model import User
from backend.domain.user.repository import (
    UserAccessAuditRepository,
    UserDataLoader,
    UserRepository,
    UserWithRelations,
)
from backend.dtos.user import (
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserSearchRequest,
    UserSummaryResponse,
    UserUpdateRequest,
)
from backend.error import NotFoundError
from backend.utils.logger import logger


class UserService:
    """Service for user management operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._user_repo = UserRepository(session)
        self._audit_repo = UserAccessAuditRepository(session)
        self._data_loader = UserDataLoader(session)

    # ============================================================
    # User CRUD Operations
    # ============================================================

    async def create_user(self, request: UserCreateRequest) -> UserResponse:
        """Create a new user with optional profile data."""
        # Normalize phone number
        phone = request.phone.replace("-", "")

        # Check for existing user
        existing = await self._user_repo.find_by_phone(phone)
        if existing:
            raise ValueError(f"User with phone {phone} already exists")

        # Create user
        user = await self._user_repo.create_async(
            phone=phone,
            name=request.name,
            gender=request.gender,
            auth_type=request.auth_type,
            status=UserStatusEnum.DRAFT,
        )

        logger.info(f"Created user {user.id} with phone {phone}")
        return await self.get_user(user.id)

    async def get_user(self, user_id: str) -> UserResponse:
        """Get user by ID."""
        loaded = await self._data_loader.load_user_with_relations(
            user_id,
            include_photos=False,
            include_documents=False,
        )
        if not loaded:
            raise NotFoundError(f"User {user_id} not found")

        return self._to_user_response_from_loaded(loaded)

    async def update_user(
        self,
        user_id: str,
        request: UserUpdateRequest,
    ) -> UserResponse:
        """Update user information."""
        user = await self._user_repo.get_async(user_id)
        if not user or user.deleted_at is not None:
            raise NotFoundError(f"User {user_id} not found")

        # Update user fields
        update_data = {}
        if request.name is not None:
            update_data["name"] = request.name
        if request.status is not None:
            update_data["status"] = request.status

        if update_data:
            await self._user_repo.update_async(user_id, **update_data)

        logger.info(f"Updated user {user_id}")
        return await self.get_user(user_id)

    async def delete_user(self, user_id: str) -> bool:
        """Soft delete a user."""
        result = await self._user_repo.soft_delete(user_id)
        if result:
            logger.info(f"Soft deleted user {user_id}")
        return result

    async def list_users(self, request: UserSearchRequest) -> UserListResponse:
        """List users with search and pagination."""
        users = await self._user_repo.list_async(
            skip=request.skip,
            limit=request.limit,
            order_by="-created_at",
        )

        total = await self._user_repo.count_async(
            filters={"deleted_at": None},
        )

        return UserListResponse(
            users=[self._to_user_summary(u) for u in users],
            total=total,
            skip=request.skip,
            limit=request.limit,
        )

    # ============================================================
    # Audit Operations
    # ============================================================

    async def log_access(
        self,
        accessor_id: str,
        accessor_type: str,
        target_user_id: str,
        resource_type: str,
        action: str,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Log an access event."""
        await self._audit_repo.log_access(
            accessor_id=accessor_id,
            accessor_type=accessor_type,
            target_user_id=target_user_id,
            resource_type=resource_type,
            action=action,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # ============================================================
    # Helper Methods
    # ============================================================

    def _to_user_response_from_loaded(
        self,
        loaded: UserWithRelations,
    ) -> UserResponse:
        """Convert pre-loaded UserWithRelations to response DTO."""
        user = loaded.user
        return UserResponse(
            id=user.id,
            firebase_id=user.firebase_id,
            phone=user.phone or "",
            name=user.name or "",
            gender=user.gender,
            auth_type=user.auth_type,
            status=user.status,
            created_at=user.created_at,
            updated_at=user.updated_at,
            profile=None,
            lifestyle=None,
            preference=None,
            subscription=None,
            photo_count=0,
            document_count=0,
        )

    def _to_user_summary(self, user: User) -> UserSummaryResponse:
        """Convert user model to summary response DTO."""
        return UserSummaryResponse(
            id=user.id,
            name=user.name or "",
            gender=user.gender,
            phone=user.phone or "",
            status=user.status,
            created_at=user.created_at,
        )
