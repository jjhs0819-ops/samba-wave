"""
User domain repository with CRUD operations and custom queries.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.user.model import (
    User,
    UserAccessAudit,
    UserLifestyle,
    UserPhoto,
    UserDocument,
    UserPreference,
    UserProfile,
    UserSubscription,
)
from backend.utils.logger import logger


@dataclass
class UserWithRelations:
    """
    Data class holding User with all related entities.
    """

    user: User
    profile: Optional[UserProfile] = None
    lifestyle: Optional[UserLifestyle] = None
    preference: Optional[UserPreference] = None
    subscription: Optional[UserSubscription] = None
    photos: List[UserPhoto] = None  # type: ignore
    documents: List[UserDocument] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.photos is None:
            self.photos = []
        if self.documents is None:
            self.documents = []


class UserRepository(BaseRepository[User]):
    """Repository for User entity with extended queries."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def find_by_phone(self, phone: str) -> Optional[User]:
        """Find user by phone number."""
        normalized_phone = phone.replace("-", "")
        stmt = select(User).where(
            and_(
                User.phone == normalized_phone,
                User.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_email(self, email: str) -> Optional[User]:
        """Find user by email."""
        stmt = select(User).where(
            and_(
                User.email == email,
                User.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, user_id: str) -> bool:
        """Soft delete a user by setting deleted_at."""
        user = await self.get_async(user_id)
        if not user or user.deleted_at is not None:
            return False

        user.deleted_at = datetime.now(tz=timezone.utc)
        user.updated_at = datetime.now(tz=timezone.utc)
        self.session.add(user)
        await self.session.commit()
        return True


class UserDataLoader:
    """
    Optimized data loader for User with relations.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def load_user_with_relations(
        self,
        user_id: str,
        include_photos: bool = True,
        include_documents: bool = True,
    ) -> Optional[UserWithRelations]:
        """Load user with all related entities in parallel queries."""
        # First, fetch user
        user_stmt = select(User).where(
            and_(User.id == user_id, User.deleted_at.is_(None))
        )
        user_result = await self.session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if not user:
            return None

        # Prepare all queries
        profile_stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        lifestyle_stmt = select(UserLifestyle).where(UserLifestyle.user_id == user_id)
        preference_stmt = select(UserPreference).where(
            UserPreference.user_id == user_id
        )
        subscription_stmt = select(UserSubscription).where(
            UserSubscription.user_id == user_id
        )

        # Execute all queries in parallel
        queries = [
            self.session.execute(profile_stmt),
            self.session.execute(lifestyle_stmt),
            self.session.execute(preference_stmt),
            self.session.execute(subscription_stmt),
        ]

        results = await asyncio.gather(*queries)

        # Extract results
        profile = results[0].scalar_one_or_none()
        lifestyle = results[1].scalar_one_or_none()
        preference = results[2].scalar_one_or_none()
        subscription = results[3].scalar_one_or_none()

        return UserWithRelations(
            user=user,
            profile=profile,
            lifestyle=lifestyle,
            preference=preference,
            subscription=subscription,
            photos=[],
            documents=[],
        )


class UserAccessAuditRepository(BaseRepository[UserAccessAudit]):
    """Repository for UserAccessAudit entity."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, UserAccessAudit)

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
    ) -> UserAccessAudit:
        """Log an access event."""
        audit = UserAccessAudit(
            accessor_id=accessor_id,
            accessor_type=accessor_type,
            target_user_id=target_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(audit)
        await self.session.commit()
        await self.session.refresh(audit)
        logger.info(
            f"Access audit logged: {accessor_type}:{accessor_id} "
            f"{action} {resource_type}:{resource_id} of user {target_user_id}"
        )
        return audit
