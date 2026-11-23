"""Authentication readiness interfaces.

These are NOT implemented yet — they prepare the structure for future
FastAPI authentication integration.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    REVIEWER = "reviewer"
    READ_ONLY = "read_only"


class User(BaseModel):
    """User interface — ready for future auth integration."""

    id: str = ""
    email: str = ""
    name: str = ""
    role: UserRole = UserRole.DEVELOPER
    is_active: bool = True
    organization_id: str = ""


class Organization(BaseModel):
    """Organization interface."""

    id: str = ""
    name: str = ""
    slug: str = ""
    is_active: bool = True
    members: list[str] = Field(default_factory=list)


class RepositoryPermission(BaseModel):
    """Repository access permission."""

    repository_id: str = ""
    user_id: str = ""
    role: UserRole = UserRole.DEVELOPER
    can_read: bool = True
    can_write: bool = False
    can_admin: bool = False


class AuthContext(BaseModel):
    """Authentication context — passed through service calls when auth is enabled."""

    user: User | None = None
    organization: Organization | None = None
    permissions: list[RepositoryPermission] = Field(default_factory=list)
    authenticated: bool = False

    def has_permission(self, repository_id: str, required_role: UserRole) -> bool:
        """Check if user has required role for a repository."""
        if not self.authenticated or not self.user:
            return False
        if self.user.role == UserRole.ADMIN:
            return True
        role_hierarchy = {
            UserRole.READ_ONLY: 0,
            UserRole.REVIEWER: 1,
            UserRole.DEVELOPER: 2,
            UserRole.ADMIN: 3,
        }
        for perm in self.permissions:
            if perm.repository_id == repository_id:
                return role_hierarchy.get(perm.role, 0) >= role_hierarchy.get(required_role, 0)
        return False
