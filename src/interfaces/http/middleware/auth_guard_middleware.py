"""AuthGuard middleware — verifies Cognito access tokens and builds the auth context.

Multi-region Cognito: access tokens are signed with RS256. This guard verifies a
token against the JWKS of the User Pool identified by the token's ``iss`` claim
(one pool/issuer per region), then resolves the active tenant and the user's
current roles from DynamoDB — the token itself is tenant-agnostic.

Implements Requirements:
- 9.1: Every authenticated query uses the tenant resolved from the user's
       default_tenant_id (DynamoDB) as a mandatory filter.
- 9.2: Verify the access token with RS256/JWKS by issuer; identify the user by `sub`.
- 9.3: Reject (403) when the user is not a member of the resolved tenant.
- 9.5: Reject (403) when the user has no default tenant assigned.
- 9.6: Reject (401) on any token verification failure.
- 10.4: Return 401 "Missing or invalid authorization header" for missing auth.
- 5.7: While a user has status "pending_tenant", allow only the tenant-selection
       and logout endpoints; reject (403) "tenant_required" for any other path.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import jwt
from jwt import PyJWK

if TYPE_CHECKING:
    from application.ports.i_user_repository import IUserRepository
    from infrastructure.auth.jwks_provider import JWKSProvider

logger = logging.getLogger(__name__)

# Endpoints a "pending_tenant" user may reach before selecting a tenant (Req 5.7).
_PENDING_TENANT_ALLOWED_PATHS = ("/auth/social/select-tenant", "/auth/logout")


# ──── AuthContext ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Authenticated user context for a request.

    Attributes:
        user_id: The Cognito sub (unique user identifier), from the access token.
        tenant_id: The active tenant, resolved from the user's default_tenant_id
            in DynamoDB (never carried in the token).
        roles: The user's current roles for the resolved tenant, loaded from DynamoDB.
        email: The user's email address, from the profile in DynamoDB.
    """

    user_id: str
    tenant_id: str
    roles: list[str]
    email: str


# ──── Error Response Helper ───────────────────────────────────────────────────


def _error_response(status_code: int, message: str) -> dict[str, Any]:
    """Build a standardized error response dict for API Gateway Lambda responses.

    Args:
        status_code: HTTP status code (401, 403, etc.).
        message: Human-readable error message.

    Returns:
        A dict with statusCode, headers, and JSON body.
    """
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


# ──── AuthGuard Middleware ────────────────────────────────────────────────────


class AuthGuardMiddleware:
    """Verifies Cognito access tokens (RS256/JWKS) and resolves the auth context.

    Verification is multi-region aware: the signing keys are resolved from the
    JWKS of the pool identified by the token's ``iss`` claim, which must be in the
    configured allow-list. After the signature and standard claims are validated,
    the active tenant and roles are resolved from DynamoDB using the token's ``sub``.
    """

    def __init__(
        self,
        allowed_issuers: tuple[str, ...] | list[str],
        allowed_client_ids: tuple[str, ...] | list[str],
        user_repository: IUserRepository,
        jwks_provider: JWKSProvider,
    ) -> None:
        """Initialize the AuthGuard middleware.

        Args:
            allowed_issuers: Allow-list of accepted Cognito token issuers
                (one User Pool issuer per region).
            allowed_client_ids: Allow-list of accepted Cognito app client ids.
            user_repository: Repository used to load the user profile (for
                default_tenant_id) and the user's roles for the resolved tenant.
            jwks_provider: Provider that resolves RS256 signing keys per issuer.
        """
        self._allowed_issuers = frozenset(allowed_issuers)
        self._allowed_client_ids = frozenset(allowed_client_ids)
        self._user_repository = user_repository
        self._jwks_provider = jwks_provider

    def validate(self, event: dict[str, Any]) -> AuthContext | dict[str, Any]:
        """Verify the request's access token and resolve the auth context.

        Steps:
        1. Extract the Bearer access token from the Authorization header.
        2. Verify it with RS256 against the JWKS of the pool named by its ``iss``.
        3. Resolve the active tenant from the user's default_tenant_id (DynamoDB).
        4. Load the user's current roles for that tenant (DynamoDB).

        Args:
            event: API Gateway Lambda event dict containing 'headers'.

        Returns:
            AuthContext on success, or an error response dict on failure.
        """
        # Step 1: Extract Authorization header (API Gateway may vary the casing).
        headers = event.get("headers") or {}
        auth_header = headers.get("Authorization") or headers.get("authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return _error_response(401, "Missing or invalid authorization header")

        token = auth_header[7:].strip()  # Strip "Bearer " prefix
        if not token:
            return _error_response(401, "Missing or invalid authorization header")

        # Step 2: Verify the access token (RS256/JWKS, multi-region by issuer).
        payload = self._verify_token(token)
        if payload is None:
            return _error_response(401, "Token expired or invalid")

        user_id = payload.get("sub", "")
        if not user_id:
            return _error_response(401, "Token expired or invalid")

        # Step 3: Resolve the active tenant from the user's profile (DynamoDB).
        # The token is tenant-agnostic; tenant/roles are authoritative in the store.
        user = self._user_repository.find_by_id(user_id)
        if user is None:
            return _error_response(401, "Token expired or invalid")

        # Step 3a: Pending-tenant access control (Requirement 5.7).
        # A user who completed OAuth but has not yet chosen a tenant may only reach
        # the tenant-selection and logout endpoints; every other protected path is
        # rejected with 403 "tenant_required" until the tenant association completes.
        if user.status == "pending_tenant":
            path = self._request_path(event)
            if not any(path.endswith(allowed) for allowed in _PENDING_TENANT_ALLOWED_PATHS):
                return _error_response(403, "tenant_required")
            # Allowed path: the user has no tenant/roles yet; downstream use cases
            # (e.g. select-tenant) authorize by user_id and re-check the status.
            return AuthContext(
                user_id=user_id,
                tenant_id="",
                roles=[],
                email=user.email.value,
            )

        if user.status != "active":
            return _error_response(401, "Token expired or invalid")

        tenant_id = user.default_tenant_id
        if not tenant_id:
            return _error_response(403, "User has no default tenant assigned")

        # Step 4: Load current roles for the resolved tenant (DynamoDB).
        user_roles = self._user_repository.get_roles_for_tenant(user_id, tenant_id)
        role_names: list[str] = [str(role.role_name) for role in user_roles]

        if not role_names:
            return _error_response(403, "User is not a member of the resolved tenant")

        return AuthContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=role_names,
            email=user.email.value,
        )

    @staticmethod
    def _request_path(event: dict[str, Any]) -> str:
        """Extract the request path from an API Gateway Lambda event.

        Mirrors the routing convention used by the HTTP handlers, preferring the
        REST API ``resource`` template and falling back to ``path`` (and the
        HTTP API v2 ``requestContext.http.path``) so the pending-tenant check
        works across API Gateway payload formats.

        Args:
            event: API Gateway Lambda event dict.

        Returns:
            The request path, or an empty string when none is present.
        """
        resource = event.get("resource") or event.get("path")
        if resource:
            return str(resource)
        request_context = event.get("requestContext") or {}
        http = request_context.get("http") or {}
        return str(http.get("path") or "")

    def _verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify a Cognito access token with RS256 against the issuer's JWKS.

        Validates, in order:
        - the ``iss`` claim is in the allow-list of known pools;
        - the signing key (by ``kid``) can be resolved from that issuer's JWKS;
        - the signature is valid using RS256 only (rejecting ``none``/HS*);
        - ``token_use == "access"`` and ``client_id`` is in the allow-list;
        - the token is not expired.

        Args:
            token: The raw JWT string (without the "Bearer " prefix).

        Returns:
            The decoded payload dict on success, or None on any failure.
        """
        # 2a. Read the unverified issuer and header to route to the right JWKS.
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            issuer = unverified.get("iss", "")
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            logger.debug("Malformed token: %s", exc)
            return None

        # 2b. Reject issuers that are not in the allow-list of known pools.
        if issuer not in self._allowed_issuers:
            logger.debug("Rejected token from unknown issuer: %s", issuer)
            return None

        kid = header.get("kid")
        if not kid:
            logger.debug("Token header missing 'kid'")
            return None

        # 2c. Resolve the signing key for this issuer + kid (cached JWKS).
        signing_key: PyJWK | None = self._jwks_provider.get_signing_key(issuer, kid)
        if signing_key is None:
            return None

        # 2d. Verify signature (RS256 only) and standard claims.
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=issuer,
                options={
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": False,  # Cognito access tokens use client_id, not aud
                },
            )
        except jwt.ExpiredSignatureError:
            logger.debug("Access token expired")
            return None
        except jwt.InvalidTokenError as exc:
            logger.debug("Access token verification failed: %s", exc)
            return None

        # 2e. Enforce this is an access token from an allowed client.
        if payload.get("token_use") != "access":
            logger.debug("Rejected token with token_use=%s (expected 'access')", payload.get("token_use"))
            return None

        if payload.get("client_id") not in self._allowed_client_ids:
            logger.debug("Rejected token from disallowed client_id")
            return None

        return payload
