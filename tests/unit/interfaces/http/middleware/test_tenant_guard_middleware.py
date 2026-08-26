"""Unit tests for TenantGuardMiddleware."""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest

from interfaces.http.middleware.tenant_guard_middleware import (
    TenantContext,
    TenantGuardMiddleware,
)

# ──── Constants ───────────────────────────────────────────────────────────────

JWT_SECRET = "test-secret-key-for-unit-tests"
ALGORITHMS = ["HS256"]


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_token(
    payload: dict[str, Any],
    secret: str = JWT_SECRET,
    algorithm: str = "HS256",
) -> str:
    """Create a signed JWT token with the given payload."""
    return jwt.encode(payload, secret, algorithm=algorithm)


def _make_event(token: str | None = None, auth_header: str | None = None) -> dict[str, Any]:
    """Build a minimal API Gateway event with an optional Authorization header."""
    headers: dict[str, str] = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    elif token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return {"headers": headers}


def _valid_payload(
    *,
    user_id: str = "user-123-sub",
    tenant_id: str = "tenant-456-uuid",
    email: str = "user@example.com",
    roles: list[str] | None = None,
    exp_offset: int = 3600,
) -> dict[str, Any]:
    """Build a valid JWT payload with standard Cognito claims."""
    payload: dict[str, Any] = {
        "sub": user_id,
        "custom:tenant_id": tenant_id,
        "email": email,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    if roles is not None:
        payload["cognito:groups"] = roles
    return payload


# ──── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def middleware() -> TenantGuardMiddleware:
    """Create a TenantGuardMiddleware instance with test secret."""
    return TenantGuardMiddleware(jwt_secret=JWT_SECRET, algorithms=ALGORITHMS)


# ──── Tests: Missing or Invalid Authorization Header (Req 10.4) ───────────────


class TestMissingAuth:
    """Tests for missing or invalid Authorization header — Requirement 10.4."""

    def test_missing_headers_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        event: dict[str, Any] = {"headers": None}
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Missing or invalid authorization header"

    def test_no_authorization_header_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        event = _make_event()
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Missing or invalid authorization header"

    def test_empty_authorization_header_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        event = _make_event(auth_header="")
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_non_bearer_scheme_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        event = _make_event(auth_header="Basic dXNlcjpwYXNz")
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Missing or invalid authorization header"

    def test_bearer_with_empty_token_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        event = _make_event(auth_header="Bearer ")
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_bearer_with_whitespace_token_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        event = _make_event(auth_header="Bearer    ")
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401


# ──── Tests: Invalid or Expired Token ─────────────────────────────────────────


class TestInvalidToken:
    """Tests for invalid or expired JWT tokens."""

    def test_malformed_token_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        event = _make_event(token="not.a.valid.jwt")
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Token expired or invalid"

    def test_wrong_secret_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        payload = _valid_payload()
        token = _make_token(payload, secret="wrong-secret")
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Token expired or invalid"

    def test_expired_token_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        payload = _valid_payload(exp_offset=-3600)  # Expired 1 hour ago
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Token expired or invalid"


# ──── Tests: Missing tenant_id Claim (Req 9.5) ───────────────────────────────


class TestMissingTenantId:
    """Tests for missing tenant_id in JWT — Requirement 9.5."""

    def test_no_tenant_id_claim_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        payload = {
            "sub": "user-123",
            "email": "user@example.com",
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Invalid token: missing tenant context"

    def test_empty_tenant_id_claim_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        payload = {
            "sub": "user-123",
            "email": "user@example.com",
            "custom:tenant_id": "",
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Invalid token: missing tenant context"


# ──── Tests: Successful Validation (Req 9.1, 9.2) ────────────────────────────


class TestSuccessfulValidation:
    """Tests for successful JWT validation and TenantContext extraction."""

    def test_valid_token_returns_tenant_context(self, middleware: TenantGuardMiddleware) -> None:
        payload = _valid_payload(roles=["admin"])
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, TenantContext)
        assert result.user_id == "user-123-sub"
        assert result.tenant_id == "tenant-456-uuid"
        assert result.email == "user@example.com"
        assert result.roles == ["admin"]

    def test_multiple_roles_extracted(self, middleware: TenantGuardMiddleware) -> None:
        payload = _valid_payload(roles=["admin", "manager"])
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, TenantContext)
        assert result.roles == ["admin", "manager"]

    def test_custom_roles_claim_comma_separated(self, middleware: TenantGuardMiddleware) -> None:
        payload = _valid_payload()
        payload["custom:roles"] = "admin,manager"
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, TenantContext)
        assert result.roles == ["admin", "manager"]

    def test_default_viewer_role_when_no_roles(self, middleware: TenantGuardMiddleware) -> None:
        payload = _valid_payload()  # No roles specified
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, TenantContext)
        assert result.roles == ["viewer"]

    def test_tenant_id_from_plain_claim(self, middleware: TenantGuardMiddleware) -> None:
        """Support alternative 'tenant_id' claim name."""
        payload = {
            "sub": "user-abc",
            "tenant_id": "tenant-xyz",
            "email": "test@example.com",
            "exp": int(time.time()) + 3600,
            "cognito:groups": ["viewer"],
        }
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, TenantContext)
        assert result.tenant_id == "tenant-xyz"

    def test_case_insensitive_authorization_header(self, middleware: TenantGuardMiddleware) -> None:
        """API Gateway may pass lowercase 'authorization' header."""
        payload = _valid_payload(roles=["admin"])
        token = _make_token(payload)
        event: dict[str, Any] = {"headers": {"authorization": f"Bearer {token}"}}
        result = middleware.validate(event)

        assert isinstance(result, TenantContext)
        assert result.user_id == "user-123-sub"

    def test_tenant_context_is_immutable(self, middleware: TenantGuardMiddleware) -> None:
        payload = _valid_payload(roles=["admin"])
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, TenantContext)
        with pytest.raises(AttributeError):
            result.user_id = "hacked"  # type: ignore[misc]


# ──── Tests: Missing sub Claim ────────────────────────────────────────────────


class TestMissingSub:
    """Tests for missing 'sub' claim in JWT."""

    def test_no_sub_claim_returns_401(self, middleware: TenantGuardMiddleware) -> None:
        payload = {
            "custom:tenant_id": "tenant-123",
            "email": "user@example.com",
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(payload)
        event = _make_event(token=token)
        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        body = json.loads(result["body"])
        assert body["error"] == "Token expired or invalid"
