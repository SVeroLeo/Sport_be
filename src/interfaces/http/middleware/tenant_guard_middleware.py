"""TenantGuard middleware — extracts and validates tenant context from JWT tokens.

Implements Requirements:
- 9.1: Every authenticated query includes tenantId from JWT as mandatory filter
- 9.2: Extract tenantId from JWT payload for all data access operations
- 9.5: Reject requests with 401 if JWT lacks tenantId claim
- 10.4: Return 401 "Missing or invalid authorization header" for missing auth
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import jwt

logger = logging.getLogger(__name__)


# ──── TenantContext ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Authenticated user context extracted from a verified Cognito JWT.

    Attributes:
        user_id: The Cognito sub (unique user identifier).
        tenant_id: The tenant the user belongs to (from custom:tenant_id claim).
        roles: List of role names assigned to the user in this tenant.
        email: The user's email address from the token.
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
    import json

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


# ──── TenantGuard Middleware ──────────────────────────────────────────────────


class TenantGuardMiddleware:
    """Middleware that validates JWT tokens and extracts tenant context.

    Extracts the Bearer token from the Authorization header, verifies
    the JWT signature and claims, and returns a TenantContext containing
    the authenticated user's identity and tenant information.

    This middleware uses HS256 verification with the configured JWT secret.
    For production Cognito deployments, this should be replaced with RS256
    verification using Cognito JWKS keys. The current implementation supports
    both approaches via configuration.
    """

    def __init__(self, jwt_secret: str, algorithms: list[str] | None = None) -> None:
        """Initialize the TenantGuard middleware.

        Args:
            jwt_secret: Secret key used for JWT signature verification.
                        For Cognito RS256, this would be the public key.
            algorithms: List of accepted JWT algorithms.
                        Defaults to ["HS256"].
        """
        self._jwt_secret = jwt_secret
        self._algorithms = algorithms or ["HS256"]

    def validate(
        self, event: dict[str, Any]
    ) -> TenantContext | dict[str, Any]:
        """Validate the JWT token from the request and extract tenant context.

        Implements the TenantGuard algorithm from the design document:
        1. Extract Bearer token from Authorization header
        2. Verify JWT signature and decode payload
        3. Extract tenant_id from payload, reject if missing
        4. Return TenantContext with user identity

        Args:
            event: API Gateway Lambda event dict containing 'headers'.

        Returns:
            TenantContext on success, or an error response dict on failure.
        """
        # Step 1: Extract Authorization header
        headers = event.get("headers") or {}
        # API Gateway may pass headers with various casings
        auth_header = headers.get("Authorization") or headers.get("authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return _error_response(401, "Missing or invalid authorization header")

        token = auth_header[7:]  # Strip "Bearer " prefix

        if not token.strip():
            return _error_response(401, "Missing or invalid authorization header")

        # Step 2: Verify JWT and decode payload
        payload = self._verify_token(token)
        if payload is None:
            return _error_response(401, "Token expired or invalid")

        # Step 3: Extract tenant_id — reject if missing (Requirement 9.5)
        tenant_id = payload.get("custom:tenant_id") or payload.get("tenant_id")

        if not tenant_id:
            return _error_response(401, "Invalid token: missing tenant context")

        # Step 4: Extract user identity claims
        user_id = payload.get("sub", "")
        email = payload.get("email", "")
        # Roles can come from cognito:groups or custom:roles claim
        roles = self._extract_roles(payload)

        if not user_id:
            return _error_response(401, "Token expired or invalid")

        return TenantContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            email=email,
        )

    def _verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify JWT signature and decode the payload.

        Args:
            token: The raw JWT string (without "Bearer " prefix).

        Returns:
            Decoded payload dict on success, None on failure.
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=self._algorithms,
                options={
                    "verify_exp": True,
                    "verify_aud": False,  # Cognito tokens may not have 'aud' in access_token
                },
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.debug("JWT token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug("JWT token validation failed: %s", e)
            return None

    @staticmethod
    def _extract_roles(payload: dict[str, Any]) -> list[str]:
        """Extract user roles from the JWT payload.

        Cognito tokens may include roles in different claims:
        - cognito:groups — standard Cognito groups
        - custom:roles — custom attribute (comma-separated or JSON list)

        Args:
            payload: Decoded JWT payload dict.

        Returns:
            List of role name strings. Returns ["viewer"] as default
            if no roles are found.
        """
        # Try cognito:groups first (list of group names)
        groups = payload.get("cognito:groups")
        if isinstance(groups, list) and groups:
            return [str(g) for g in groups]

        # Try custom:roles claim (comma-separated string)
        custom_roles = payload.get("custom:roles")
        if isinstance(custom_roles, str) and custom_roles.strip():
            return [r.strip() for r in custom_roles.split(",") if r.strip()]

        # Try a plain 'roles' claim (for flexibility)
        roles = payload.get("roles")
        if isinstance(roles, list) and roles:
            return [str(r) for r in roles]

        # Default to viewer if no roles found
        return ["viewer"]
