"""Organization RBAC — local roles & permissions (no authentication).

Roles are stored on member profiles for UI and soft API checks.
Login / SSO / OAuth remain out of scope (Enterprise).
"""

from __future__ import annotations

from enum import Enum


class OrgRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MAINTAINER = "maintainer"
    REVIEWER = "reviewer"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class TeamRole(str, Enum):
    LEAD = "lead"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(str, Enum):
    GENERATE_REVIEW = "generate_review"
    APPROVE_PATCH = "approve_patch"
    APPLY_PATCH = "apply_patch"
    MANAGE_RULES = "manage_rules"
    MANAGE_ORGANIZATION = "manage_organization"
    INVITE_USERS = "invite_users"
    VIEW_ANALYTICS = "view_analytics"
    EXPORT_REPORTS = "export_reports"
    MANAGE_REPOSITORIES = "manage_repositories"


# Role → permissions (higher roles include lower privileges)
_ROLE_PERMISSIONS: dict[OrgRole, frozenset[Permission]] = {
    OrgRole.VIEWER: frozenset(
        {
            Permission.VIEW_ANALYTICS,
            Permission.EXPORT_REPORTS,
        }
    ),
    OrgRole.DEVELOPER: frozenset(
        {
            Permission.VIEW_ANALYTICS,
            Permission.EXPORT_REPORTS,
            Permission.GENERATE_REVIEW,
            Permission.APPLY_PATCH,
        }
    ),
    OrgRole.REVIEWER: frozenset(
        {
            Permission.VIEW_ANALYTICS,
            Permission.EXPORT_REPORTS,
            Permission.GENERATE_REVIEW,
            Permission.APPLY_PATCH,
            Permission.APPROVE_PATCH,
        }
    ),
    OrgRole.MAINTAINER: frozenset(
        {
            Permission.VIEW_ANALYTICS,
            Permission.EXPORT_REPORTS,
            Permission.GENERATE_REVIEW,
            Permission.APPLY_PATCH,
            Permission.APPROVE_PATCH,
            Permission.MANAGE_RULES,
            Permission.MANAGE_REPOSITORIES,
        }
    ),
    OrgRole.ADMIN: frozenset(set(Permission)),
    OrgRole.OWNER: frozenset(set(Permission)),
}


def permissions_for(role: str | OrgRole) -> frozenset[Permission]:
    try:
        key = role if isinstance(role, OrgRole) else OrgRole(str(role).lower())
    except ValueError:
        return frozenset()
    return _ROLE_PERMISSIONS.get(key, frozenset())


def has_permission(role: str | OrgRole, permission: Permission | str) -> bool:
    try:
        perm = (
            permission
            if isinstance(permission, Permission)
            else Permission(str(permission))
        )
    except ValueError:
        return False
    return perm in permissions_for(role)


def role_hierarchy_rank(role: str | OrgRole) -> int:
    order = [
        OrgRole.VIEWER,
        OrgRole.DEVELOPER,
        OrgRole.REVIEWER,
        OrgRole.MAINTAINER,
        OrgRole.ADMIN,
        OrgRole.OWNER,
    ]
    try:
        key = role if isinstance(role, OrgRole) else OrgRole(str(role).lower())
    except ValueError:
        return -1
    try:
        return order.index(key)
    except ValueError:
        return -1
