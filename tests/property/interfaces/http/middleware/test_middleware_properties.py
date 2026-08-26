"""Property-based tests for Tenant Data Isolation and Role Permission Enforcement.

**Validates: Requirements 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.5, 10.6**

Properties tested:
- Property 1: Tenant Data Isolation
- Property 3: Role Permission Enforcement
"""

from __future__ import annotations

import time
from typing import Any

import hypothesis.strategies as st
import jwt
import pytest
from hypothesis import given, settings

from domain.entities.user_role import (
    PERMISSION_CREATE,
    PERMISSION_DELETE,
    PERMISSION_INVITE_MEMBERS,
    PERMISSION_MANAGE_MEMBERS,
    PERMISSION_MANAGE_ROLES,
    PERMISSION_MANAGE_USERS,
    PERMISSION_READ,
    PERMISSION_UPDATE,
    RolePermissions,
    get_permissions_for_roles,
)
from interfaces.http.middleware.role_guard_middleware import check_permission, require_permission
from interfaces.http.middleware.tenant_guard_middleware import TenantContext, TenantGuardMiddleware


# ─── Constants ────────────────────────────────────────────────────────────────

JWT_SECRET = "test-secret-key-for-property-tests"
ALL_PERMISSIONS = frozenset({
    PERMISSION_CREATE,
    PERMISSION_READ,
    PERMISSION_UPDATE,
    PERMISSION_DELETE,
    PERMISSION_MANAGE_USERS,
    PERMISSION_MANAGE_ROLES,
    PERMISSION_MANAGE_MEMBERS,
    PERMISSION_INVITE_MEMBERS,
})

WRITE_PERMISSIONS = frozenset({
    PERMISSION_CREATE,
    PERMISSION_UPDATE,
    PERMISSION_DELETE,
})


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid UUID-like tenant IDs
valid_tenant_ids = st.from_regex(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    fullmatch=True,
)

# Valid UUID-like user IDs
valid_user_ids = st.from_regex(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    fullmatch=True,
)

# Valid email addresses
valid_emails = st.from_regex(r"[a-z][a-z0-9]{1,10}@[a-z]{2,6}\.[a-z]{2,4}", fullmatch=True)

# Valid role names
valid_roles = st.sampled_from(["admin", "manager", "viewer"])

# Non-empty role lists (1 to 3 roles)
valid_role_lists = st.lists(valid_roles, min_size=1, max_size=3)

# All defined permission strings
all_permission_strings = st.sampled_from([
    PERMISSION_CREATE,
    PERMISSION_READ,
    PERMISSION_UPDATE,
    PERMISSION_DELETE,
    PERMISSION_MANAGE_USERS,
    PERMISSION_MANAGE_ROLES,
    PERMISSION_MANAGE_MEMBERS,
    PERMISSION_INVITE_MEMBERS,
])


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _build_jwt_token(
    tenant_id: str | None,
    user_id: str = "sub-123",
    email: str = "user@test.com",
    roles: list[str] | None = None,
    secret: str = JWT_SECRET,
) -> str:
    """Build a signed JWT token for testing."""
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "exp": int(time.time()) + 3600,
    }
    if tenant_id is not None:
        payload["custom:tenant_id"] = tenant_id
    if roles is not None:
        payload["cognito:groups"] = roles
    return jwt.encode(payload, secret, algorithm="HS256")


def _build_event(token: str) -> dict[str, Any]:
    """Build an API Gateway event with Authorization header."""
    return {
        "headers": {
            "Authorization": f"Bearer {token}",
        }
    }


# ─── Property 1: Tenant Data Isolation ───────────────────────────────────────


class TestTenantDataIsolation:
    """Property 1: Tenant Data Isolation.

    For any tenant_id in JWT, TenantGuard ALWAYS extracts and returns it.
    Tokens without tenant_id ALWAYS get rejected (401).
    TenantContext always contains the same tenant_id as was in the token.
    The system never cross-contaminates tenant IDs.

    **Validates: Requirements 9.1, 9.2**
    """

    @given(
        tenant_id=valid_tenant_ids,
        user_id=valid_user_ids,
        email=valid_emails,
        roles=valid_role_lists,
    )
    @settings(max_examples=200)
    def test_tenant_id_always_extracted_from_jwt(
        self,
        tenant_id: str,
        user_id: str,
        email: str,
        roles: list[str],
    ) -> None:
        """For ANY valid tenant_id in the JWT payload, TenantGuard ALWAYS
        extracts and returns it in TenantContext.

        **Validates: Requirements 9.1, 9.2**
        """
        # Arrange
        middleware = TenantGuardMiddleware(jwt_secret=JWT_SECRET)
        token = _build_jwt_token(
            tenant_id=tenant_id,
            user_id=user_id,
            email=email,
            roles=roles,
        )
        event = _build_event(token)

        # Act
        result = middleware.validate(event)

        # Assert: result is a TenantContext with the correct tenant_id
        assert isinstance(result, TenantContext)
        assert result.tenant_id == tenant_id
        assert result.user_id == user_id
        assert result.email == email

    @given(
        tenant_id=valid_tenant_ids,
        user_id=valid_user_ids,
    )
    @settings(max_examples=200)
    def test_tenant_context_never_cross_contaminates(
        self,
        tenant_id: str,
        user_id: str,
    ) -> None:
        """For ANY tenant_id in the token, the extracted TenantContext
        ALWAYS contains exactly that tenant_id — never a different one.

        **Validates: Requirements 9.1, 9.2**
        """
        # Arrange
        middleware = TenantGuardMiddleware(jwt_secret=JWT_SECRET)
        token = _build_jwt_token(tenant_id=tenant_id, user_id=user_id)
        event = _build_event(token)

        # Act
        result = middleware.validate(event)

        # Assert
        assert isinstance(result, TenantContext)
        # The tenant_id in the context is EXACTLY what was in the token
        assert result.tenant_id == tenant_id
        # It's not some other value
        assert result.user_id == user_id

    @given(
        user_id=valid_user_ids,
        email=valid_emails,
    )
    @settings(max_examples=200)
    def test_tokens_without_tenant_id_always_rejected(
        self,
        user_id: str,
        email: str,
    ) -> None:
        """For ANY token that lacks a tenant_id claim, TenantGuard ALWAYS
        rejects with a 401 error indicating an invalid token.

        **Validates: Requirements 9.5**
        """
        # Arrange: token WITHOUT tenant_id
        middleware = TenantGuardMiddleware(jwt_secret=JWT_SECRET)
        token = _build_jwt_token(tenant_id=None, user_id=user_id, email=email)
        event = _build_event(token)

        # Act
        result = middleware.validate(event)

        # Assert: result is an error response, not a TenantContext
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    @given(
        tenant_id_1=valid_tenant_ids,
        tenant_id_2=valid_tenant_ids,
        user_id=valid_user_ids,
    )
    @settings(max_examples=200)
    def test_different_tokens_yield_different_contexts(
        self,
        tenant_id_1: str,
        tenant_id_2: str,
        user_id: str,
    ) -> None:
        """For ANY two tokens with different tenant IDs, TenantGuard returns
        distinct TenantContexts that faithfully reflect each token.

        **Validates: Requirements 9.1, 9.2**
        """
        # Arrange
        middleware = TenantGuardMiddleware(jwt_secret=JWT_SECRET)

        token_1 = _build_jwt_token(tenant_id=tenant_id_1, user_id=user_id)
        token_2 = _build_jwt_token(tenant_id=tenant_id_2, user_id=user_id)

        event_1 = _build_event(token_1)
        event_2 = _build_event(token_2)

        # Act
        result_1 = middleware.validate(event_1)
        result_2 = middleware.validate(event_2)

        # Assert: both are valid contexts
        assert isinstance(result_1, TenantContext)
        assert isinstance(result_2, TenantContext)

        # Each context reflects its own token's tenant_id
        assert result_1.tenant_id == tenant_id_1
        assert result_2.tenant_id == tenant_id_2

        # If the tenant IDs are different, the contexts are different
        if tenant_id_1 != tenant_id_2:
            assert result_1.tenant_id != result_2.tenant_id

    def test_missing_authorization_header_always_returns_401(self) -> None:
        """Requests without an Authorization header ALWAYS get 401.

        **Validates: Requirements 10.4**
        """
        middleware = TenantGuardMiddleware(jwt_secret=JWT_SECRET)

        # No headers at all
        result = middleware.validate({"headers": {}})
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

        # Empty Authorization header
        result = middleware.validate({"headers": {"Authorization": ""}})
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

        # Non-Bearer token
        result = middleware.validate({"headers": {"Authorization": "Basic abc123"}})
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_invalid_jwt_signature_always_returns_401(self) -> None:
        """Tokens signed with a different secret ALWAYS get 401.

        **Validates: Requirements 9.5**
        """
        middleware = TenantGuardMiddleware(jwt_secret=JWT_SECRET)
        token = _build_jwt_token(
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            secret="wrong-secret-key",
        )
        event = _build_event(token)

        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401


# ─── Property 3: Role Permission Enforcement ─────────────────────────────────


class TestRolePermissionEnforcement:
    """Property 3: Role Permission Enforcement.

    For any combination of roles, the effective permissions are ALWAYS the union.
    A viewer can NEVER perform write operations.
    A manager can NEVER manage_users or manage_roles.
    An admin ALWAYS has all permissions.
    Adding more roles NEVER reduces permissions (monotonic escalation).

    **Validates: Requirements 10.1, 10.2, 10.3, 10.5, 10.6**
    """

    @given(roles=valid_role_lists)
    @settings(max_examples=200)
    def test_effective_permissions_are_always_union_of_role_permissions(
        self,
        roles: list[str],
    ) -> None:
        """For ANY combination of roles, the effective permissions are
        ALWAYS exactly the union of all individual role permissions.

        **Validates: Requirements 10.6**
        """
        # Act
        effective = get_permissions_for_roles(roles)

        # Assert: effective permissions = union of individual role permissions
        expected_union: set[str] = set()
        for role in roles:
            expected_union |= RolePermissions.get_permissions(role)

        assert effective == expected_union

    @given(
        extra_params=st.tuples(valid_tenant_ids, valid_user_ids, valid_emails),
    )
    @settings(max_examples=200)
    def test_viewer_can_never_perform_write_operations(
        self,
        extra_params: tuple[str, str, str],
    ) -> None:
        """A user with ONLY the "viewer" role can NEVER perform write
        operations (create, update, delete) — always gets 403.

        **Validates: Requirements 10.1**
        """
        tenant_id, user_id, email = extra_params

        # Arrange: viewer-only context
        viewer_context = TenantContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=["viewer"],
            email=email,
        )

        # Assert: all write permissions are denied
        for write_perm in WRITE_PERMISSIONS:
            result = check_permission(viewer_context, write_perm)
            assert result is not None
            assert result["statusCode"] == 403

        # Also check manage_users, manage_roles, manage_members
        for manage_perm in [PERMISSION_MANAGE_USERS, PERMISSION_MANAGE_ROLES, PERMISSION_MANAGE_MEMBERS]:
            result = check_permission(viewer_context, manage_perm)
            assert result is not None
            assert result["statusCode"] == 403

    @given(
        extra_params=st.tuples(valid_tenant_ids, valid_user_ids, valid_emails),
    )
    @settings(max_examples=200)
    def test_manager_can_never_manage_users_or_manage_roles(
        self,
        extra_params: tuple[str, str, str],
    ) -> None:
        """A user with ONLY the "manager" role can NEVER manage_users
        or manage_roles — always gets 403.

        **Validates: Requirements 10.2**
        """
        tenant_id, user_id, email = extra_params

        # Arrange: manager-only context
        manager_context = TenantContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=["manager"],
            email=email,
        )

        # Assert: manage_users is denied
        result = check_permission(manager_context, PERMISSION_MANAGE_USERS)
        assert result is not None
        assert result["statusCode"] == 403

        # Assert: manage_roles is denied
        result = check_permission(manager_context, PERMISSION_MANAGE_ROLES)
        assert result is not None
        assert result["statusCode"] == 403

    @given(
        extra_params=st.tuples(valid_tenant_ids, valid_user_ids, valid_emails),
        permission=all_permission_strings,
    )
    @settings(max_examples=200)
    def test_admin_always_has_all_permissions(
        self,
        extra_params: tuple[str, str, str],
        permission: str,
    ) -> None:
        """A user with the "admin" role ALWAYS has all permissions —
        check_permission ALWAYS returns None (allow).

        **Validates: Requirements 10.3**
        """
        tenant_id, user_id, email = extra_params

        # Arrange: admin context
        admin_context = TenantContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=["admin"],
            email=email,
        )

        # Assert: every permission is granted
        result = check_permission(admin_context, permission)
        assert result is None  # None means "allowed"

    @given(
        extra_params=st.tuples(valid_tenant_ids, valid_user_ids, valid_emails),
        permission=all_permission_strings,
    )
    @settings(max_examples=200)
    def test_empty_roles_always_deny_everything(
        self,
        extra_params: tuple[str, str, str],
        permission: str,
    ) -> None:
        """A user with NO roles can NEVER perform any action —
        always gets 403.

        **Validates: Requirements 10.5**
        """
        tenant_id, user_id, email = extra_params

        # Arrange: empty roles context
        empty_context = TenantContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[],
            email=email,
        )

        # Assert: every permission is denied
        result = check_permission(empty_context, permission)
        assert result is not None
        assert result["statusCode"] == 403

    @given(
        base_roles=valid_role_lists,
        additional_role=valid_roles,
    )
    @settings(max_examples=200)
    def test_adding_roles_never_reduces_permissions(
        self,
        base_roles: list[str],
        additional_role: str,
    ) -> None:
        """Adding more roles NEVER reduces the effective permission set.
        Permissions are monotonically increasing (union semantics).

        **Validates: Requirements 10.6**
        """
        # Act: compute permissions with base roles
        base_permissions = get_permissions_for_roles(base_roles)

        # Act: compute permissions with additional role
        extended_roles = base_roles + [additional_role]
        extended_permissions = get_permissions_for_roles(extended_roles)

        # Assert: adding a role never removes permissions
        assert base_permissions.issubset(extended_permissions)

    @given(
        roles=valid_role_lists,
        permission=all_permission_strings,
        extra_params=st.tuples(valid_tenant_ids, valid_user_ids, valid_emails),
    )
    @settings(max_examples=200)
    def test_check_permission_matches_role_definitions(
        self,
        roles: list[str],
        permission: str,
        extra_params: tuple[str, str, str],
    ) -> None:
        """For ANY combination of roles and permission, check_permission
        returns None (allow) if and only if the union of role permissions
        contains the required permission.

        **Validates: Requirements 10.5, 10.6**
        """
        tenant_id, user_id, email = extra_params

        # Arrange
        context = TenantContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            email=email,
        )

        # Act
        result = check_permission(context, permission)

        # Assert: result matches whether the permission is in the union
        effective = get_permissions_for_roles(roles)
        if permission in effective:
            assert result is None  # allowed
        else:
            assert result is not None
            assert result["statusCode"] == 403

    @given(
        extra_params=st.tuples(valid_tenant_ids, valid_user_ids, valid_emails),
        permission=all_permission_strings,
    )
    @settings(max_examples=200)
    def test_require_permission_factory_behaves_same_as_check_permission(
        self,
        extra_params: tuple[str, str, str],
        permission: str,
    ) -> None:
        """The require_permission factory creates a guard that behaves
        identically to calling check_permission directly.

        **Validates: Requirements 10.5**
        """
        tenant_id, user_id, email = extra_params

        context = TenantContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=["manager"],
            email=email,
        )

        # Act: using the factory
        guard = require_permission(permission)
        factory_result = guard(context)

        # Act: using check_permission directly
        direct_result = check_permission(context, permission)

        # Assert: both produce the same result
        assert factory_result == direct_result
