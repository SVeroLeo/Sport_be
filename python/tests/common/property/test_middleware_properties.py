"""Property-based tests for Tenant Data Isolation and Role Permission Enforcement.

**Validates: Requirements 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.5, 10.6**

Properties tested:
- Property 1: Tenant Data Isolation
- Property 3: Role Permission Enforcement

AuthGuard is exercised through the current RS256/JWKS + DynamoDB API: access
tokens are RS256-signed and verified against a mocked JWKS by issuer, and the
active tenant / roles are resolved from a mocked IUserRepository (the token is
tenant-agnostic).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import hypothesis.strategies as st
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from hypothesis import given, settings
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from api.common.user.users import User
from api.common.user.userRole import (
    PERMISSION_CREATE,
    PERMISSION_DELETE,
    PERMISSION_INVITE_MEMBERS,
    PERMISSION_MANAGE_MEMBERS,
    PERMISSION_MANAGE_ROLES,
    PERMISSION_MANAGE_USERS,
    PERMISSION_READ,
    PERMISSION_UPDATE,
    RolePermissions,
    UserRole,
    get_permissions_for_roles,
)
from api.common.http.authGuardMiddleware import AuthContext, AuthGuardMiddleware
from api.common.http.roleGuardMiddleware import check_permission, require_permission

# ─── Constants ────────────────────────────────────────────────────────────────

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"
OTHER_ISSUER = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_Other"
CLIENT_ID = "test-client-id"
KID = "test-key-id"

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


# ─── RSA key material (module-scoped, generated once) ─────────────────────────

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _public_jwk() -> PyJWK:
    """Build a PyJWK from the test public key (what the JWKS would return)."""
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key()))
    jwk_dict["kid"] = KID
    jwk_dict["alg"] = "RS256"
    jwk_dict["use"] = "sig"
    return PyJWK.from_dict(jwk_dict)


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


def _sign_access_token(
    *,
    user_id: str,
    issuer: str = ISSUER,
    client_id: str = CLIENT_ID,
    token_use: str = "access",
    exp_offset: int = 3600,
    kid: str = KID,
    algorithm: str = "RS256",
    key: Any = _PRIVATE_KEY,
) -> str:
    """Create an RS256-signed JWT resembling a Cognito access token (tenant-agnostic)."""
    payload: dict[str, Any] = {
        "sub": user_id,
        "iss": issuer,
        "client_id": client_id,
        "token_use": token_use,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid})


def _build_event(token: str) -> dict[str, Any]:
    """Build an API Gateway event with Authorization header."""
    return {"headers": {"Authorization": f"Bearer {token}"}}


def _make_user(
    *,
    user_id: str,
    email: str,
    default_tenant_id: str | None,
    status: str = "active",
) -> User:
    """Build a User profile as returned by the repository."""
    return User.reconstitute(
        user_id=user_id,
        email=email,
        cognito_sub=user_id,
        full_name="Test User",
        status=status,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        default_tenant_id=default_tenant_id,
    )


def _make_roles(user_id: str, tenant_id: str, names: list[str]) -> list[UserRole]:
    return [
        UserRole.reconstitute(
            user_id=user_id,
            tenant_id=tenant_id,
            role_name=name,
            assigned_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for name in names
    ]


def _jwks_provider() -> MagicMock:
    """Mock JWKSProvider returning the test public key for the known issuer + kid."""
    provider = MagicMock()

    def _get_signing_key(issuer: str, kid: str) -> PyJWK | None:
        if issuer in (ISSUER, OTHER_ISSUER) and kid == KID:
            return _public_jwk()
        return None

    provider.get_signing_key.side_effect = _get_signing_key
    return provider


def _user_repository(user: User | None, roles: list[UserRole]) -> MagicMock:
    """Mock IUserRepository resolving the given user profile and roles."""
    repo = MagicMock()
    repo.find_by_id.return_value = user
    repo.get_roles_for_tenant.return_value = roles
    return repo


def _build_middleware(user: User | None, roles: list[UserRole]) -> AuthGuardMiddleware:
    """Create an AuthGuardMiddleware wired with mocked JWKS + repository."""
    return AuthGuardMiddleware(
        allowed_issuers=(ISSUER,),
        allowed_client_ids=(CLIENT_ID,),
        user_repository=_user_repository(user, roles),
        jwks_provider=_jwks_provider(),
    )


# ─── Property 1: Tenant Data Isolation ───────────────────────────────────────


class TestTenantDataIsolation:
    """Property 1: Tenant Data Isolation.

    Access tokens are tenant-agnostic; the active tenant is resolved from the
    user's default_tenant_id in DynamoDB. For any user whose profile carries a
    default_tenant_id, AuthGuard ALWAYS resolves that exact tenant into the
    AuthContext and never cross-contaminates. Users with no default tenant are
    ALWAYS rejected, and invalid tokens ALWAYS get 401.

    **Validates: Requirements 9.1, 9.2**
    """

    @given(
        tenant_id=valid_tenant_ids,
        user_id=valid_user_ids,
        email=valid_emails,
        roles=valid_role_lists,
    )
    @settings(max_examples=200)
    def test_tenant_id_always_resolved_from_repository(
        self,
        tenant_id: str,
        user_id: str,
        email: str,
        roles: list[str],
    ) -> None:
        """For ANY user whose default_tenant_id is set, AuthGuard ALWAYS
        resolves that tenant (and the sub/email) into the AuthContext.

        **Validates: Requirements 9.1, 9.2**
        """
        user = _make_user(user_id=user_id, email=email, default_tenant_id=tenant_id)
        middleware = _build_middleware(user, _make_roles(user_id, tenant_id, roles))
        token = _sign_access_token(user_id=user_id)

        result = middleware.validate(_build_event(token))

        assert isinstance(result, AuthContext)
        assert result.tenant_id == tenant_id
        assert result.user_id == user_id
        assert result.email == email

    @given(
        tenant_id=valid_tenant_ids,
        user_id=valid_user_ids,
    )
    @settings(max_examples=200)
    def test_auth_context_never_cross_contaminates(
        self,
        tenant_id: str,
        user_id: str,
    ) -> None:
        """For ANY user default tenant, the AuthContext ALWAYS carries exactly
        that tenant_id — never a different one — regardless of token contents.

        **Validates: Requirements 9.1, 9.2**
        """
        user = _make_user(user_id=user_id, email="user@test.com", default_tenant_id=tenant_id)
        middleware = _build_middleware(user, _make_roles(user_id, tenant_id, ["viewer"]))
        token = _sign_access_token(user_id=user_id)

        result = middleware.validate(_build_event(token))

        assert isinstance(result, AuthContext)
        assert result.tenant_id == tenant_id
        assert result.user_id == user_id

    @given(
        user_id=valid_user_ids,
        email=valid_emails,
    )
    @settings(max_examples=200)
    def test_users_without_default_tenant_always_rejected(
        self,
        user_id: str,
        email: str,
    ) -> None:
        """For ANY user that lacks a default tenant, AuthGuard ALWAYS rejects
        with 403 (no tenant can be resolved).

        **Validates: Requirements 9.5**
        """
        user = _make_user(user_id=user_id, email=email, default_tenant_id=None)
        middleware = _build_middleware(user, [])
        token = _sign_access_token(user_id=user_id)

        result = middleware.validate(_build_event(token))

        assert isinstance(result, dict)
        assert result["statusCode"] == 403

    @given(
        tenant_id_1=valid_tenant_ids,
        tenant_id_2=valid_tenant_ids,
        user_id=valid_user_ids,
    )
    @settings(max_examples=200)
    def test_different_users_yield_different_contexts(
        self,
        tenant_id_1: str,
        tenant_id_2: str,
        user_id: str,
    ) -> None:
        """For ANY two users with different default tenants, AuthGuard returns
        distinct AuthContexts that faithfully reflect each user's tenant.

        **Validates: Requirements 9.1, 9.2**
        """
        user_1 = _make_user(user_id=user_id, email="user@test.com", default_tenant_id=tenant_id_1)
        middleware_1 = _build_middleware(user_1, _make_roles(user_id, tenant_id_1, ["viewer"]))

        user_2 = _make_user(user_id=user_id, email="user@test.com", default_tenant_id=tenant_id_2)
        middleware_2 = _build_middleware(user_2, _make_roles(user_id, tenant_id_2, ["viewer"]))

        token = _sign_access_token(user_id=user_id)

        result_1 = middleware_1.validate(_build_event(token))
        result_2 = middleware_2.validate(_build_event(token))

        assert isinstance(result_1, AuthContext)
        assert isinstance(result_2, AuthContext)
        assert result_1.tenant_id == tenant_id_1
        assert result_2.tenant_id == tenant_id_2

        if tenant_id_1 != tenant_id_2:
            assert result_1.tenant_id != result_2.tenant_id

    def test_missing_authorization_header_always_returns_401(self) -> None:
        """Requests without a valid Authorization header ALWAYS get 401.

        **Validates: Requirements 10.4**
        """
        user = _make_user(
            user_id="00000000-0000-4000-8000-000000000000",
            email="user@test.com",
            default_tenant_id="11111111-1111-4111-8111-111111111111",
        )
        middleware = _build_middleware(user, _make_roles(user.user_id, "11111111-1111-4111-8111-111111111111", ["admin"]))

        # No headers at all
        result = middleware.validate({"headers": {}})
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

        # Empty Authorization header
        result = middleware.validate({"headers": {"Authorization": ""}})
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

        # Non-Bearer scheme
        result = middleware.validate({"headers": {"Authorization": "Basic abc123"}})
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_invalid_jwt_signature_always_returns_401(self) -> None:
        """Tokens signed with a key the JWKS does not provide ALWAYS get 401.

        **Validates: Requirements 9.6**
        """
        user = _make_user(
            user_id="00000000-0000-4000-8000-000000000000",
            email="user@test.com",
            default_tenant_id="11111111-1111-4111-8111-111111111111",
        )
        middleware = _build_middleware(user, _make_roles(user.user_id, "11111111-1111-4111-8111-111111111111", ["admin"]))

        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _sign_access_token(user_id=user.user_id, key=wrong_key)

        result = middleware.validate(_build_event(token))

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
        viewer_context = AuthContext(
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
        manager_context = AuthContext(
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
        admin_context = AuthContext(
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
        empty_context = AuthContext(
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
        extended_roles = [*base_roles, additional_role]
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
        context = AuthContext(
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

        context = AuthContext(
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
