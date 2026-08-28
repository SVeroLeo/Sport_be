"""RoleGuard middleware — enforces role-based permission checks.

Validates that the authenticated user's roles grant the required permission
for the requested action. Uses the union of permissions across all assigned
roles (least restrictive access per Requirement 10.6).

Requirements: 10.1, 10.2, 10.3, 10.5, 10.6
"""

from __future__ import annotations

import json
from typing import Any

from domain.entities.user_role import get_permissions_for_roles
from interfaces.http.middleware.auth_guard_middleware import AuthContext


def _forbidden_response() -> dict[str, Any]:
    """Build a 403 Forbidden response dict for API Gateway."""
    return {
        "statusCode": 403,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"message": "Insufficient permissions"}),
    }


def check_permission(auth_context: AuthContext, required_permission: str) -> dict[str, Any] | None:
    """Check if the user's roles grant the required permission.

    Implements the union of permissions across multiple roles (Req 10.6):
    if any of the user's roles includes the required permission, access is allowed.

    Args:
        auth_context: The authenticated user context from AuthGuard.
        required_permission: The permission string required for the action
            (e.g., PERMISSION_CREATE, PERMISSION_DELETE, PERMISSION_MANAGE_MEMBERS).

    Returns:
        None if the user has the required permission (request proceeds).
        A dict with statusCode 403 and "Insufficient permissions" body if unauthorized.
    """
    user_permissions = get_permissions_for_roles(auth_context.roles)

    if required_permission not in user_permissions:
        return _forbidden_response()

    return None


def require_permission(required_permission: str):
    """Create a role guard function bound to a specific permission.

    This factory enables composable middleware stacking. The returned callable
    accepts an AuthContext and returns None (allow) or a 403 response (deny).

    Usage:
        guard = require_permission(PERMISSION_CREATE)
        result = guard(auth_context)
        if result is not None:
            return result  # 403 response
        # proceed with handler logic

    Args:
        required_permission: The permission string that the user must have.

    Returns:
        A callable that takes an AuthContext and returns None or a 403 response dict.
    """

    def guard(auth_context: AuthContext) -> dict[str, Any] | None:
        return check_permission(auth_context, required_permission)

    return guard
