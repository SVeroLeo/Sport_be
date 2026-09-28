"""User entity ↔ DynamoDB item mapper.

Maps User entities to/from DynamoDB items using the single table design:
- PK=USER#{email}, SK=PROFILE

Also includes mappers for TenantMembership and UserRole entities:
- TenantMembership: PK=TENANT#{tenant_id}#USER#{user_id}, SK=MEMBERSHIP
- UserRole: PK=TENANT#{tenant_id}#USER#{user_id}, SK=ROLE#{role_name}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.user import User
from api.common.user.userRole import UserRole


# ──── User Mapper ─────────────────────────────────────────────────────────────


def user_to_item(user: User) -> dict[str, Any]:
    """Convert a User entity to a DynamoDB item.

    Args:
        user: The User domain entity.

    Returns:
        A dictionary representing the DynamoDB item.
    """
    item: dict[str, Any] = {
        "PK": f"USER#{user.email.value}",
        "SK": "PROFILE",
        "user_id": user.user_id,
        "email": user.email.value,
        "cognito_sub": user.cognito_sub,
        "full_name": user.full_name.value,
        "status": user.status,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }
    # Only persist default_tenant_id when set, to keep items clean and avoid
    # writing null attributes for users not yet associated with a tenant.
    if user.default_tenant_id is not None:
        item["default_tenant_id"] = user.default_tenant_id
    return item


def user_from_item(item: dict[str, Any]) -> User:
    """Convert a DynamoDB item to a User entity.

    Uses the User.reconstitute() factory method to rebuild the entity
    from persisted data.

    Args:
        item: The DynamoDB item dictionary.

    Returns:
        A User domain entity.
    """
    return User.reconstitute(
        user_id=item["user_id"],
        email=item["email"],
        cognito_sub=item["cognito_sub"],
        full_name=item["full_name"],
        status=item["status"],
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        default_tenant_id=item.get("default_tenant_id"),
    )


# ──── TenantMembership Mapper ─────────────────────────────────────────────────


def tenant_membership_to_item(membership: TenantMembership) -> dict[str, Any]:
    """Convert a TenantMembership entity to a DynamoDB item.

    Key pattern: PK=TENANT#{tenant_id}#USER#{user_id}, SK=MEMBERSHIP

    Args:
        membership: The TenantMembership domain entity.

    Returns:
        A dictionary representing the DynamoDB item.
    """
    return {
        "PK": f"TENANT#{membership.tenant_id}#USER#{membership.user_id}",
        "SK": "MEMBERSHIP",
        "user_id": membership.user_id,
        "tenant_id": membership.tenant_id,
        "status": membership.status,
        "joined_at": membership.joined_at.isoformat(),
    }


def tenant_membership_from_item(item: dict[str, Any]) -> TenantMembership:
    """Convert a DynamoDB item to a TenantMembership entity.

    Uses the TenantMembership.reconstitute() factory method.

    Args:
        item: The DynamoDB item dictionary.

    Returns:
        A TenantMembership domain entity.
    """
    return TenantMembership.reconstitute(
        user_id=item["user_id"],
        tenant_id=item["tenant_id"],
        status=item["status"],
        joined_at=datetime.fromisoformat(item["joined_at"]),
    )


# ──── UserRole Mapper ─────────────────────────────────────────────────────────


def user_role_to_item(role: UserRole) -> dict[str, Any]:
    """Convert a UserRole entity to a DynamoDB item.

    Key pattern: PK=TENANT#{tenant_id}#USER#{user_id}, SK=ROLE#{role_name}

    Args:
        role: The UserRole domain entity.

    Returns:
        A dictionary representing the DynamoDB item.
    """
    return {
        "PK": f"TENANT#{role.tenant_id}#USER#{role.user_id}",
        "SK": f"ROLE#{role.role_name}",
        "user_id": role.user_id,
        "tenant_id": role.tenant_id,
        "role_name": role.role_name,
        "permissions": sorted(role.permissions),
        "assigned_at": role.assigned_at.isoformat(),
    }


def user_role_from_item(item: dict[str, Any]) -> UserRole:
    """Convert a DynamoDB item to a UserRole entity.

    Uses the UserRole.reconstitute() factory method.

    Args:
        item: The DynamoDB item dictionary.

    Returns:
        A UserRole domain entity.
    """
    return UserRole.reconstitute(
        user_id=item["user_id"],
        tenant_id=item["tenant_id"],
        role_name=item["role_name"],
        assigned_at=datetime.fromisoformat(item["assigned_at"]),
    )
