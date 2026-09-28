"""Unit tests for AuthGuardMiddleware (RS256/JWKS, multi-region, tenant from DynamoDB)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from api.common.user.user import User
from api.common.user.userRole import UserRole
from api.common.http.authGuardMiddleware import (
    AuthContext,
    AuthGuardMiddleware,
)

# ──── Constants ───────────────────────────────────────────────────────────────

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"
OTHER_ISSUER = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_Other"
CLIENT_ID = "test-client-id"
KID = "test-key-id"
USER_SUB = "user-123-sub"
TENANT_ID = "tenant-456-uuid"
EMAIL = "user@example.com"


# ──── RSA key material (module-scoped, generated once) ────────────────────────

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _public_jwk() -> PyJWK:
    """Build a PyJWK from the test public key (what the JWKS would return)."""
    jwk_json = RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key())
    jwk_dict = json.loads(jwk_json)
    jwk_dict["kid"] = KID
    jwk_dict["alg"] = "RS256"
    jwk_dict["use"] = "sig"
    return PyJWK.from_dict(jwk_dict)


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_token(
    *,
    issuer: str = ISSUER,
    client_id: str = CLIENT_ID,
    sub: str = USER_SUB,
    token_use: str = "access",
    exp_offset: int = 3600,
    kid: str = KID,
    algorithm: str = "RS256",
    key: Any = _PRIVATE_KEY,
) -> str:
    """Create a signed JWT resembling a Cognito access token."""
    payload: dict[str, Any] = {
        "sub": sub,
        "iss": issuer,
        "client_id": client_id,
        "token_use": token_use,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    headers = {"kid": kid}
    return jwt.encode(payload, key, algorithm=algorithm, headers=headers)


def _make_event(token: str | None = None, auth_header: str | None = None) -> dict[str, Any]:
    """Build a minimal API Gateway event with an optional Authorization header."""
    headers: dict[str, str] = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    elif token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return {"headers": headers}


def _make_user(*, status: str = "active", default_tenant_id: str | None = TENANT_ID) -> User:
    """Build a User profile as returned by the repository."""
    return User.reconstitute(
        user_id=USER_SUB,
        email=EMAIL,
        cognito_sub=USER_SUB,
        full_name="John Doe",
        status=status,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        default_tenant_id=default_tenant_id,
    )


def _make_roles(*names: str) -> list[UserRole]:
    return [
        UserRole.reconstitute(
            user_id=USER_SUB,
            tenant_id=TENANT_ID,
            role_name=name,
            assigned_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for name in names
    ]


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def user_repository() -> MagicMock:
    """Mock IUserRepository returning an active user with a default tenant + roles."""
    repo = MagicMock()
    repo.find_by_id.return_value = _make_user()
    repo.get_roles_for_tenant.return_value = _make_roles("admin")
    return repo


@pytest.fixture
def jwks_provider() -> MagicMock:
    """Mock JWKSProvider that returns the test public key for the known kid."""
    provider = MagicMock()

    def _get_signing_key(issuer: str, kid: str) -> PyJWK | None:
        if issuer in (ISSUER, OTHER_ISSUER) and kid == KID:
            return _public_jwk()
        return None

    provider.get_signing_key.side_effect = _get_signing_key
    return provider


@pytest.fixture
def middleware(user_repository: MagicMock, jwks_provider: MagicMock) -> AuthGuardMiddleware:
    """Create an AuthGuardMiddleware wired with mocked deps."""
    return AuthGuardMiddleware(
        allowed_issuers=(ISSUER,),
        allowed_client_ids=(CLIENT_ID,),
        user_repository=user_repository,
        jwks_provider=jwks_provider,
    )


# ──── Tests: Missing or Invalid Authorization Header (Req 10.4) ───────────────


class TestMissingAuth:
    """Tests for missing or invalid Authorization header — Requirement 10.4."""

    def test_missing_headers_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        result = middleware.validate({"headers": None})
        assert isinstance(result, dict)
        assert result["statusCode"] == 401
        assert json.loads(result["body"])["error"] == "Missing or invalid authorization header"

    def test_no_authorization_header_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        result = middleware.validate(_make_event())
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_non_bearer_scheme_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        result = middleware.validate(_make_event(auth_header="Basic dXNlcjpwYXNz"))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_bearer_with_empty_token_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        result = middleware.validate(_make_event(auth_header="Bearer "))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401


# ──── Tests: Token Verification Failures (Req 9.6 → 401) ──────────────────────


class TestTokenVerificationFailures:
    """Tokens that fail RS256/JWKS verification must be rejected with 401."""

    def test_malformed_token_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        result = middleware.validate(_make_event(token="not.a.valid.jwt"))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_unknown_issuer_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        token = _make_token(issuer=OTHER_ISSUER)  # not in allow-list
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_unknown_kid_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        token = _make_token(kid="unknown-kid")
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_wrong_signing_key_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        # Sign with a different private key than the one the JWKS provides.
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _make_token(key=other_key)
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_expired_token_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        token = _make_token(exp_offset=-3600)
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_hs256_token_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        # A token signed with HS256 must be rejected: algorithms are pinned to RS256.
        payload: dict[str, Any] = {
            "sub": USER_SUB,
            "iss": ISSUER,
            "client_id": CLIENT_ID,
            "token_use": "access",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "shared-secret", algorithm="HS256", headers={"kid": KID})
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_alg_none_token_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        # An unsigned ('alg': 'none') token must be rejected: algorithms are pinned to RS256.
        payload: dict[str, Any] = {
            "sub": USER_SUB,
            "iss": ISSUER,
            "client_id": CLIENT_ID,
            "token_use": "access",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, key=None, algorithm="none", headers={"kid": KID})
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_wrong_token_use_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        token = _make_token(token_use="id")  # id token, not access
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_disallowed_client_id_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        token = _make_token(client_id="some-other-client")
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_missing_sub_returns_401(self, middleware: AuthGuardMiddleware) -> None:
        token = _make_token(sub="")
        result = middleware.validate(_make_event(token=token))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401


# ──── Tests: Tenant Resolution (Req 9.1, 9.3, 9.5) ────────────────────────────


class TestTenantResolution:
    """The active tenant and roles are resolved from DynamoDB, not the token."""

    def test_unknown_user_returns_401(
        self, middleware: AuthGuardMiddleware, user_repository: MagicMock
    ) -> None:
        user_repository.find_by_id.return_value = None
        result = middleware.validate(_make_event(token=_make_token()))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_inactive_user_returns_401(
        self, middleware: AuthGuardMiddleware, user_repository: MagicMock
    ) -> None:
        user_repository.find_by_id.return_value = _make_user(status="inactive")
        result = middleware.validate(_make_event(token=_make_token()))
        assert isinstance(result, dict)
        assert result["statusCode"] == 401

    def test_no_default_tenant_returns_403(
        self, middleware: AuthGuardMiddleware, user_repository: MagicMock
    ) -> None:
        user_repository.find_by_id.return_value = _make_user(default_tenant_id=None)
        result = middleware.validate(_make_event(token=_make_token()))
        assert isinstance(result, dict)
        assert result["statusCode"] == 403
        assert json.loads(result["body"])["error"] == "User has no default tenant assigned"

    def test_not_a_member_returns_403(
        self, middleware: AuthGuardMiddleware, user_repository: MagicMock
    ) -> None:
        user_repository.get_roles_for_tenant.return_value = []
        result = middleware.validate(_make_event(token=_make_token()))
        assert isinstance(result, dict)
        assert result["statusCode"] == 403
        assert json.loads(result["body"])["error"] == "User is not a member of the resolved tenant"


# ──── Tests: Successful Validation ────────────────────────────────────────────


class TestSuccessfulValidation:
    """Successful verification returns an AuthContext with DynamoDB-resolved data."""

    def test_valid_token_returns_auth_context(self, middleware: AuthGuardMiddleware) -> None:
        result = middleware.validate(_make_event(token=_make_token()))
        assert isinstance(result, AuthContext)
        assert result.user_id == USER_SUB
        assert result.tenant_id == TENANT_ID  # resolved from default_tenant_id, not token
        assert result.email == EMAIL
        assert result.roles == ["admin"]

    def test_roles_come_from_repository_not_token(
        self, middleware: AuthGuardMiddleware, user_repository: MagicMock
    ) -> None:
        user_repository.get_roles_for_tenant.return_value = _make_roles("admin", "manager")
        result = middleware.validate(_make_event(token=_make_token()))
        assert isinstance(result, AuthContext)
        assert result.roles == ["admin", "manager"]

    def test_case_insensitive_authorization_header(self, middleware: AuthGuardMiddleware) -> None:
        token = _make_token()
        result = middleware.validate({"headers": {"authorization": f"Bearer {token}"}})
        assert isinstance(result, AuthContext)
        assert result.user_id == USER_SUB

    def test_tenant_resolved_via_find_by_id_with_sub(
        self, middleware: AuthGuardMiddleware, user_repository: MagicMock
    ) -> None:
        middleware.validate(_make_event(token=_make_token()))
        user_repository.find_by_id.assert_called_once_with(USER_SUB)
        user_repository.get_roles_for_tenant.assert_called_once_with(USER_SUB, TENANT_ID)

    def test_auth_context_is_immutable(self, middleware: AuthGuardMiddleware) -> None:
        result = middleware.validate(_make_event(token=_make_token()))
        assert isinstance(result, AuthContext)
        with pytest.raises(AttributeError):
            result.user_id = "hacked"  # type: ignore[misc]
