"""User domain - Core user management and authentication."""

from backend.domain.user.model import User
from backend.domain.user.repository import (
    UserAccessAuditRepository,
    UserRepository,
    UserDataLoader,
    UserWithRelations,
)
from backend.domain.user.service import UserService
from backend.domain.user.auth_service import AuthService, get_user_id

__all__ = [
    # Models
    "User",
    # Repositories
    "UserRepository",
    "UserAccessAuditRepository",
    "UserDataLoader",
    "UserWithRelations",
    # Services
    "UserService",
    "AuthService",
    "get_user_id",
]
