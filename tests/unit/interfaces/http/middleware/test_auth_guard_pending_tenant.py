"""Unit tests for AuthGuardMiddleware pending-tenant enforcement (Requirement 5.7).

While a user's status is "pending_tenant" (completed OAuth but not yet associated
with a tenant), only the tenant-selection and logout endpoints are reachable; every
other protected path is rejected with 403 "tenant_required".

These tests reuse the RSA key material, token/event builders, and fixtures from the
sibling ``test_auth_guard_middleware`` module to match the existing conventions.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from interfaces.http.middleware.auth_guard_middleware import (
    AuthContext,
    AuthGuardMiddleware,
)

from .test_auth_guard_middleware import (
    EMAIL,
    TENANT_ID,
    USER_SUB,
    _make_token,
    _make_user,
)

# Re-export the sibling module's fixtures so pytest can resolve them here.
from .test_auth_guard_middleware import (  # noqa: F401
    jwks_provider,
    middleware,
    user_repository,
)

# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_event_with_path(token: str, *, resource: str | None = None, path: str | None = None,
                          http_path: str | None = None) -> dict[str, Any]:
    """Build an API Gateway event with a Bearer token and a request path.

    Mirrors the middleware's ``_request_path`` precedence: ``resource`` then
    ``path`` then ``requestContext.http.path``.
    """
    event: dict[str, Any] = {"headers": {"Authorization": f"Bearer {token}"}}
    if resource is not None:
        event["resource"] = resource
    if path is not None:
        event["path"] = path
    if http_path is not None:
        event["requestContext"] = {"http": {"path": http_path}}
    return event


# ──── Tests: Pending-tenant enforcement (Req 5.7) ─────────────────────────────


class TestPendingTenantEnforcement:
    """A pending_tenant user may reach only tenant-selection and logout paths."""

    def test_select_tenant_path_returns_auth_context(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # A pending_tenant user hitting the tenant-selection endpoint is allowed.
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event = _make_event_with_path(_make_token(), resource="/auth/social/select-tenant")

        result = middleware.validate(event)

        assert isinstance(result, AuthContext)
        assert result.user_id == USER_SUB
        assert result.tenant_id == ""
        assert result.roles == []
        assert result.email == EMAIL

    def test_logout_path_returns_auth_context(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # A pending_tenant user hitting logout is allowed.
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event = _make_event_with_path(_make_token(), resource="/auth/logout")

        result = middleware.validate(event)

        assert isinstance(result, AuthContext)
        assert result.user_id == USER_SUB
        assert result.tenant_id == ""
        assert result.roles == []

    def test_blocked_path_returns_403_tenant_required(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # Any other protected path is rejected with 403 "tenant_required".
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event = _make_event_with_path(_make_token(), resource="/members")

        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 403
        assert json.loads(result["body"])["error"] == "tenant_required"

    def test_stage_prefixed_select_tenant_path_is_allowed(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # Paths carrying a stage prefix still match via str.endswith semantics.
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event = _make_event_with_path(
            _make_token(), resource="/prod/auth/social/select-tenant"
        )

        result = middleware.validate(event)

        assert isinstance(result, AuthContext)
        assert result.tenant_id == ""

    def test_stage_prefixed_blocked_path_returns_403(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # A stage-prefixed non-allowed path is still blocked.
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event = _make_event_with_path(_make_token(), resource="/prod/members")

        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 403
        assert json.loads(result["body"])["error"] == "tenant_required"

    def test_path_read_from_path_key_when_no_resource(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # When no ``resource`` is present, the path falls back to ``path``.
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event = _make_event_with_path(_make_token(), path="/auth/logout")

        result = middleware.validate(event)

        assert isinstance(result, AuthContext)
        assert result.tenant_id == ""

    def test_path_read_from_http_context_when_no_resource_or_path(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # HTTP API v2 events expose the path under requestContext.http.path.
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event = _make_event_with_path(
            _make_token(), http_path="/auth/social/select-tenant"
        )

        result = middleware.validate(event)

        assert isinstance(result, AuthContext)
        assert result.tenant_id == ""

    def test_missing_path_blocks_pending_tenant_user(
        self, middleware: AuthGuardMiddleware, user_repository: Any
    ) -> None:
        # With no discernible path, a pending_tenant user is blocked (403).
        user_repository.find_by_id.return_value = _make_user(
            status="pending_tenant", default_tenant_id=None
        )
        event: dict[str, Any] = {"headers": {"Authorization": f"Bearer {_make_token()}"}}

        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 403
        assert json.loads(result["body"])["error"] == "tenant_required"


# ──── Tests: Regression for active users ──────────────────────────────────────


class TestActiveUserRegression:
    """Active users continue to authenticate normally, regardless of path."""

    def test_active_user_authenticates_with_tenant_and_roles(
        self, middleware: AuthGuardMiddleware
    ) -> None:
        # Default fixture user is active with a default tenant and an "admin" role.
        event = _make_event_with_path(_make_token(), resource="/members")

        result = middleware.validate(event)

        assert isinstance(result, AuthContext)
        assert result.user_id == USER_SUB
        assert result.tenant_id == TENANT_ID
        assert result.roles == ["admin"]
        assert result.email == EMAIL
