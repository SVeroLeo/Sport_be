"""Property-based tests for Pending-tenant access control.

Feature: social-login, Property 10: Pending-tenant access control

**Validates: Requirements 5.7**

Property 10 — Pending-tenant access control:
    For any pending-tenant user (``status == "pending_tenant"``) and for any
    request path that is not ``/auth/social/select-tenant`` and not
    ``/auth/logout``, the ``AuthGuardMiddleware`` SHALL return HTTP 403 with
    error code ``"tenant_required"``.

Token handling mirrors the established middleware property tests
(tests/property/interfaces/http/middleware/test_middleware_properties.py):
access tokens are RS256-signed with a module-scoped RSA key and verified
against a mocked JWKSProvider by issuer, and the user profile is resolved from
a mocked IUserRepository. This focuses the test on the pending-tenant path
logic rather than on cryptographic token minting.
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
from api.common.http.authGuardMiddleware import AuthGuardMiddleware

# ─── Constants ────────────────────────────────────────────────────────────────

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"
CLIENT_ID = "test-client-id"
KID = "test-key-id"

# Paths a pending-tenant user IS allowed to reach (Requirement 5.7).
ALLOWED_SUFFIXES = ("/auth/social/select-tenant", "/auth/logout")


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

valid_user_ids = st.from_regex(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    fullmatch=True,
)

valid_emails = st.from_regex(r"[a-z][a-z0-9]{1,10}@[a-z]{2,6}\.[a-z]{2,4}", fullmatch=True)


def _is_disallowed_path(path: str) -> bool:
    """A path is 'disallowed' (must be blocked) iff it ends with neither
    allowed suffix — matching the middleware's ``str.endswith`` check."""
    return not any(path.endswith(suffix) for suffix in ALLOWED_SUFFIXES)


# Arbitrary path strings that are NOT allowed for pending-tenant users.
# We build path-like strings and filter out anything ending with an allowed
# suffix, exactly as the middleware evaluates them.
disallowed_paths = (
    st.text(
        alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
        min_size=1,
        max_size=40,
    )
    .map(lambda s: s if s.startswith("/") else "/" + s)
    .filter(_is_disallowed_path)
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _sign_access_token(
    *,
    user_id: str,
    issuer: str = ISSUER,
    client_id: str = CLIENT_ID,
    token_use: str = "access",
    exp_offset: int = 3600,
    kid: str = KID,
    key: Any = _PRIVATE_KEY,
) -> str:
    """Create an RS256-signed JWT resembling a Cognito access token."""
    payload: dict[str, Any] = {
        "sub": user_id,
        "iss": issuer,
        "client_id": client_id,
        "token_use": token_use,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


def _make_pending_tenant_user(*, user_id: str, email: str) -> User:
    """Build a pending-tenant User profile as returned by the repository."""
    return User.reconstitute(
        user_id=user_id,
        email=email,
        cognito_sub=user_id,
        full_name="Social User",
        status="pending_tenant",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        default_tenant_id=None,
        registration_type="social",
    )


def _jwks_provider() -> MagicMock:
    """Mock JWKSProvider returning the test public key for the known issuer + kid."""
    provider = MagicMock()

    def _get_signing_key(issuer: str, kid: str) -> PyJWK | None:
        if issuer == ISSUER and kid == KID:
            return _public_jwk()
        return None

    provider.get_signing_key.side_effect = _get_signing_key
    return provider


def _user_repository(user: User) -> MagicMock:
    """Mock IUserRepository resolving the given pending-tenant user profile."""
    repo = MagicMock()
    repo.find_by_id.return_value = user
    repo.get_roles_for_tenant.return_value = []
    return repo


def _build_middleware(user: User) -> AuthGuardMiddleware:
    """Create an AuthGuardMiddleware wired with mocked JWKS + repository."""
    return AuthGuardMiddleware(
        allowed_issuers=(ISSUER,),
        allowed_client_ids=(CLIENT_ID,),
        user_repository=_user_repository(user),
        jwks_provider=_jwks_provider(),
    )


# ─── Property 10: Pending-tenant access control ──────────────────────────────


class TestPendingTenantAccessControl:
    """Property 10: Pending-tenant access control.

    For ANY pending-tenant user and ANY protected path other than the
    tenant-selection and logout endpoints, AuthGuard ALWAYS returns HTTP 403
    with ``error == "tenant_required"``.

    **Validates: Requirements 5.7**
    """

    @given(
        path=disallowed_paths,
        user_id=valid_user_ids,
        email=valid_emails,
    )
    @settings(max_examples=200)
    def test_pending_tenant_user_blocked_on_disallowed_paths_via_resource(
        self,
        path: str,
        user_id: str,
        email: str,
    ) -> None:
        """For ANY disallowed path supplied via ``event["resource"]``, a
        pending-tenant user is ALWAYS rejected with 403 ``"tenant_required"``.

        **Validates: Requirements 5.7**
        """
        user = _make_pending_tenant_user(user_id=user_id, email=email)
        middleware = _build_middleware(user)
        token = _sign_access_token(user_id=user_id)
        event = {"headers": {"Authorization": f"Bearer {token}"}, "resource": path}

        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error"] == "tenant_required"

    @given(
        path=disallowed_paths,
        user_id=valid_user_ids,
        email=valid_emails,
    )
    @settings(max_examples=200)
    def test_pending_tenant_user_blocked_on_disallowed_paths_via_path(
        self,
        path: str,
        user_id: str,
        email: str,
    ) -> None:
        """The same 403 ``"tenant_required"`` guarantee holds when the path is
        supplied via ``event["path"]`` (no ``resource`` key present).

        **Validates: Requirements 5.7**
        """
        user = _make_pending_tenant_user(user_id=user_id, email=email)
        middleware = _build_middleware(user)
        token = _sign_access_token(user_id=user_id)
        event = {"headers": {"Authorization": f"Bearer {token}"}, "path": path}

        result = middleware.validate(event)

        assert isinstance(result, dict)
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error"] == "tenant_required"
