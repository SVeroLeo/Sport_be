"""UserRole entity — role assignment for a user within a tenant, with permission definitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar, Literal

from api.common.errors.validationError import ValidationError

RoleNameStr = Literal["admin", "manager", "viewer"]

_VALID_ROLES: frozenset[str] = frozenset({"admin", "manager", "viewer"})


# ──── Permission Constants ────────────────────────────────────────────────────

PERMISSION_CREATE = "create"
PERMISSION_READ = "read"
PERMISSION_UPDATE = "update"
PERMISSION_DELETE = "delete"
PERMISSION_MANAGE_USERS = "manage_users"
PERMISSION_MANAGE_ROLES = "manage_roles"
PERMISSION_MANAGE_MEMBERS = "manage_members"
PERMISSION_INVITE_MEMBERS = "invite_members"


# ──── Role Permission Definitions ─────────────────────────────────────────────

class RolePermissions:
    """Defines the permission sets for each role in the system.

    Permission matrix:
    - admin: Full access — create, read, update, delete, manage_users, manage_roles,
             manage_members, invite_members
    - manager: create, read, update, delete, manage_members (cannot deactivate members,
               cannot manage_users or manage_roles)
    - viewer: read-only access
    """

    ADMIN_PERMISSIONS: frozenset[str] = frozenset({
        PERMISSION_CREATE,
        PERMISSION_READ,
        PERMISSION_UPDATE,
        PERMISSION_DELETE,
        PERMISSION_MANAGE_USERS,
        PERMISSION_MANAGE_ROLES,
        PERMISSION_MANAGE_MEMBERS,
        PERMISSION_INVITE_MEMBERS,
    })

    MANAGER_PERMISSIONS: frozenset[str] = frozenset({
        PERMISSION_CREATE,
        PERMISSION_READ,
        PERMISSION_UPDATE,
        PERMISSION_DELETE,
        PERMISSION_MANAGE_MEMBERS,
    })

    VIEWER_PERMISSIONS: frozenset[str] = frozenset({
        PERMISSION_READ,
    })

    _ROLE_MAP: ClassVar[dict[str, frozenset[str]]] = {
        "admin": ADMIN_PERMISSIONS,
        "manager": MANAGER_PERMISSIONS,
        "viewer": VIEWER_PERMISSIONS,
    }

    @classmethod
    def get_permissions(cls, role_name: str) -> frozenset[str]:
        """Get the permission set for a single role.

        Args:
            role_name: One of "admin", "manager", "viewer".

        Returns:
            Frozen set of permission strings for the role.

        Raises:
            ValidationError: If role_name is not recognized.
        """
        permissions = cls._ROLE_MAP.get(role_name)
        if permissions is None:
            raise ValidationError(
                f"Unknown role: '{role_name}'. Must be one of: {sorted(_VALID_ROLES)}",
                field="role_name",
            )
        return permissions


def get_permissions_for_roles(roles: list[str]) -> set[str]:
    """Get the union of permissions across multiple roles.

    Implements Requirement 10.6: If a user has multiple roles within a tenant,
    the system grants the union of all permissions (least restrictive access).

    Args:
        roles: List of role name strings.

    Returns:
        Combined set of all permissions from all provided roles.

    Raises:
        ValidationError: If any role name is not recognized.
    """
    combined: set[str] = set()
    for role in roles:
        combined |= RolePermissions.get_permissions(role)
    return combined


# ──── UserRole Entity ─────────────────────────────────────────────────────────

class UserRole:
    """Domain entity representing a role assignment for a user within a tenant.

    Each user can have one or more roles within a tenant. The effective
    permissions are the union of all assigned role permissions.
    """

    __slots__ = (
        "_assigned_at",
        "_role_name",
        "_tenant_id",
        "_user_id",
    )

    _user_id: str
    _tenant_id: str
    _role_name: RoleNameStr
    _assigned_at: datetime

    def __init__(
        self,
        user_id: str,
        tenant_id: str,
        role_name: RoleNameStr,
        assigned_at: datetime,
    ) -> None:
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_tenant_id", tenant_id)
        object.__setattr__(self, "_role_name", role_name)
        object.__setattr__(self, "_assigned_at", assigned_at)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    # ──── Properties ──────────────────────────────────────────────────────────

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def role_name(self) -> RoleNameStr:
        return self._role_name

    @property
    def assigned_at(self) -> datetime:
        return self._assigned_at

    @property
    def permissions(self) -> frozenset[str]:
        """Get the permissions granted by this role."""
        return RolePermissions.get_permissions(self._role_name)

    # ──── Factory Methods ─────────────────────────────────────────────────────

    @staticmethod
    def create(user_id: str, tenant_id: str, role_name: str) -> UserRole:
        """Create a new UserRole assignment.

        Args:
            user_id: UUID of the user receiving the role.
            tenant_id: UUID of the tenant where the role applies.
            role_name: Role to assign ("admin", "manager", or "viewer").

        Returns:
            A new UserRole entity with assigned_at set to now.

        Raises:
            ValidationError: If any field is invalid.
        """
        if not user_id or not user_id.strip():
            raise ValidationError("User ID cannot be empty", field="user_id")
        if not tenant_id or not tenant_id.strip():
            raise ValidationError("Tenant ID cannot be empty", field="tenant_id")
        if not role_name or not role_name.strip():
            raise ValidationError("Role name cannot be empty", field="role_name")

        normalized_role = role_name.strip().lower()
        if normalized_role not in _VALID_ROLES:
            raise ValidationError(
                f"Invalid role name: '{role_name}'. Must be one of: {sorted(_VALID_ROLES)}",
                field="role_name",
            )

        return UserRole(
            user_id=user_id.strip(),
            tenant_id=tenant_id.strip(),
            role_name=normalized_role,  # type: ignore[arg-type]
            assigned_at=datetime.now(UTC),
        )

    @staticmethod
    def reconstitute(
        user_id: str,
        tenant_id: str,
        role_name: str,
        assigned_at: datetime,
    ) -> UserRole:
        """Reconstitute a UserRole from persisted data.

        Used by repository mappers to rebuild entities from the data store.

        Args:
            user_id: Stored user UUID.
            tenant_id: Stored tenant UUID.
            role_name: Stored role name.
            assigned_at: Original assignment timestamp.

        Returns:
            A UserRole entity reconstituted from stored data.

        Raises:
            ValidationError: If role_name is not a recognized value.
        """
        if role_name not in _VALID_ROLES:
            raise ValidationError(
                f"Invalid role name: '{role_name}'. Must be one of: {sorted(_VALID_ROLES)}",
                field="role_name",
            )

        return UserRole(
            user_id=user_id,
            tenant_id=tenant_id,
            role_name=role_name,  # type: ignore[arg-type]
            assigned_at=assigned_at,
        )

    # ──── Domain Queries ──────────────────────────────────────────────────────

    def has_permission(self, permission: str) -> bool:
        """Check if this role grants a specific permission.

        Args:
            permission: The permission string to check.

        Returns:
            True if this role includes the specified permission.
        """
        return permission in self.permissions

    # ──── Equality & Representation ───────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UserRole):
            return NotImplemented
        return (
            self._user_id == other._user_id
            and self._tenant_id == other._tenant_id
            and self._role_name == other._role_name
        )

    def __hash__(self) -> int:
        return hash((self._user_id, self._tenant_id, self._role_name))

    def __repr__(self) -> str:
        return (
            f"UserRole(user_id={self._user_id!r}, "
            f"tenant_id={self._tenant_id!r}, "
            f"role_name={self._role_name!r})"
        )
