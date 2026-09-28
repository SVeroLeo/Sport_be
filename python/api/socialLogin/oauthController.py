"""OAuthController — handles social (federated) login HTTP endpoints.

Maps API Gateway Lambda proxy events to the social-login application use cases
and translates domain errors into the HTTP status codes defined in the design
"Error Handling" table. Three routes are served:

| Route | Method | Use case |
|---|---|---|
| `/auth/social/authorize`     | GET  | `SocialAuthorizeUseCase` (public) |
| `/auth/social/callback`      | GET  | `SocialCallbackUseCase` (public) |
| `/auth/social/select-tenant` | POST | `TenantAssociationUseCase` (auth required) |

Cross-cutting behaviour:
- HTTPS enforcement: a request that arrives over plain HTTP is answered with a
  301 redirect to the same URL over HTTPS (Requirement 7.5).
- `state` validation failures on the callback are logged at ``WARNING`` with the
  source IP masked (last octet zeroed) before the 400 response is returned
  (Requirement 10.5).

Error response shape (consistent with the rest of the API):
``{"error": "<error_code>", "message": "<human-readable description>"}``.

Requirements satisfied: 2.1, 2.3, 2.5, 3.1, 3.3, 3.5, 3.9, 5.2, 5.4, 5.5, 5.6,
7.1, 7.3, 7.4, 7.5, 8.1
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from api.socialLogin.socialLoginDtos import SelectTenantInputDTO
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.common.http.authGuardMiddleware import (
    AuthContext,
    AuthGuardMiddleware,
)

if TYPE_CHECKING:
    from api.socialLogin.socialAuthorizeUseCase import SocialAuthorizeUseCase
    from api.socialLogin.socialCallbackUseCase import SocialCallbackUseCase
    from api.socialLogin.tenantAssociationUseCase import (
        TenantAssociationUseCase,
    )

logger = logging.getLogger(__name__)

# Error codes carried in the ``message`` of domain errors raised downstream.
# The HTTP status for a domain error is selected by matching on these codes so
# the controller stays aligned with the design "Error Handling" table.
_STATUS_BY_ERROR_CODE: dict[str, int] = {
    "invalid_provider": 400,
    "invalid_state": 400,
    "token_exchange_failed": 400,
    "invalid_provider_email": 422,
    "provider_link_failed": 409,
    "provisioning_failed": 500,
}

# Human-readable descriptions paired with each error code in responses.
_MESSAGE_BY_ERROR_CODE: dict[str, str] = {
    "invalid_provider": "The requested social provider is not supported.",
    "invalid_state": "The state token is missing, invalid, or expired.",
    "token_exchange_failed": "Failed to exchange the authorization code for tokens.",
    "invalid_provider_email": "The social provider did not supply a valid email.",
    "provider_link_failed": "Failed to link the social provider to the account.",
    "provisioning_failed": "Failed to provision the user account.",
    "tenant_not_found": "The requested tenant was not found or is inactive.",
    "already_member": "The user is already a member of the requested tenant.",
}


class OAuthController:
    """Controller for the social-login endpoints.

    Receives the three social-login use cases and the shared
    :class:`AuthGuardMiddleware` via constructor injection. The authorize and
    callback endpoints are public; select-tenant requires a valid access token
    and resolves the caller's identity from the auth context (never the body).
    """

    def __init__(
        self,
        social_authorize_use_case: SocialAuthorizeUseCase,
        social_callback_use_case: SocialCallbackUseCase,
        tenant_association_use_case: TenantAssociationUseCase,
        auth_guard: AuthGuardMiddleware,
    ) -> None:
        """Initialize the OAuthController.

        Args:
            social_authorize_use_case: Builds the Hosted UI authorization URL.
            social_callback_use_case: Handles the OAuth callback / token exchange.
            tenant_association_use_case: Associates a pending-tenant user with a tenant.
            auth_guard: Middleware used to authenticate the select-tenant request.
        """
        self._social_authorize_use_case = social_authorize_use_case
        self._social_callback_use_case = social_callback_use_case
        self._tenant_association_use_case = tenant_association_use_case
        self._auth_guard = auth_guard

    # ──── Authorize ───────────────────────────────────────────────────────────

    def handle_authorize(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle GET /auth/social/authorize.

        Extracts the ``provider`` query parameter, builds the Cognito Hosted UI
        authorization URL, and returns it as JSON.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            200 with ``{"authorization_url": ...}`` on success, 301 when the
            request is not HTTPS, or 400 on an invalid provider.
        """
        redirect = self._https_redirect_if_needed(event)
        if redirect is not None:
            return redirect

        query_params = event.get("queryStringParameters") or {}
        provider = (query_params.get("provider") or "").strip()

        try:
            result = self._social_authorize_use_case.execute(provider)
        except DomainError as exc:
            return self._domain_error_response(exc)
        except Exception:
            logger.exception("Unexpected error building authorization URL")
            return self._error_response(500, "internal_error", "Internal server error")

        return self._success_response(200, result.model_dump())

    # ──── Callback ────────────────────────────────────────────────────────────

    async def handle_callback(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle GET /auth/social/callback.

        Extracts the ``code`` and ``state`` query parameters, runs the callback
        use case (state validation, token exchange, user resolution), and returns
        the resulting token set.

        Error codes are mapped to HTTP statuses per the design table:
        ``invalid_state`` / ``token_exchange_failed`` → 400,
        ``invalid_provider_email`` → 422, ``provider_link_failed`` → 409,
        ``provisioning_failed`` → 500.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            200 with the :class:`SocialLoginOutputDTO` on success, 301 when not
            HTTPS, or a mapped error response.
        """
        redirect = self._https_redirect_if_needed(event)
        if redirect is not None:
            return redirect

        query_params = event.get("queryStringParameters") or {}
        code = (query_params.get("code") or "").strip()
        state = (query_params.get("state") or "").strip()

        if not code:
            return self._error_response(400, "invalid_request", "Missing 'code' query parameter")
        if not state:
            return self._error_response(400, "invalid_request", "Missing 'state' query parameter")

        try:
            result = await self._social_callback_use_case.execute(code=code, state=state)
        except ValidationError as exc:
            # A state validation failure is logged at WARNING with the source IP
            # masked (last octet zeroed) before returning the mapped 400 (Req 10.5).
            if exc.message == "invalid_state":
                self._log_state_validation_failure(event)
            return self._domain_error_response(exc)
        except (ConflictError, NotFoundError) as exc:
            return self._domain_error_response(exc)
        except DomainError as exc:
            return self._domain_error_response(exc)
        except Exception:
            logger.exception("Unexpected error during social login callback")
            return self._error_response(500, "internal_error", "Internal server error")

        return self._success_response(200, result.model_dump())

    # ──── Select tenant ───────────────────────────────────────────────────────

    async def handle_select_tenant(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /auth/social/select-tenant.

        Requires a valid access token. The caller's ``user_id`` is taken from the
        authenticated context, never from the request body. The ``tenant_id`` is
        read from the body and passed to the tenant-association use case.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            200 with the :class:`TenantAssociationOutputDTO` on success, 301 when
            not HTTPS, 401/403 from the auth guard, 400 on invalid input, 404 when
            the tenant is missing/inactive, or 409 when already a member.
        """
        redirect = self._https_redirect_if_needed(event)
        if redirect is not None:
            return redirect

        # Authenticate: resolve the caller's identity from the access token.
        auth_result = self._auth_guard.validate(event)
        if not isinstance(auth_result, AuthContext):
            return auth_result

        # Parse and validate the request body (tenant_id only).
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "invalid_request", "Invalid or missing request body")

        try:
            input_dto = SelectTenantInputDTO(tenant_id=body.get("tenant_id", ""))
        except Exception:
            return self._error_response(400, "invalid_request", "Missing required field: tenant_id")

        if not input_dto.tenant_id:
            return self._error_response(400, "invalid_request", "Missing required field: tenant_id")

        # Execute using the authenticated user_id (not the body).
        try:
            result = await self._tenant_association_use_case.execute(
                user_id=auth_result.user_id,
                tenant_id=input_dto.tenant_id,
            )
        except NotFoundError as exc:
            return self._domain_error_response(exc, default_status=404)
        except ConflictError as exc:
            return self._domain_error_response(exc, default_status=409)
        except ValidationError as exc:
            return self._domain_error_response(exc, default_status=400)
        except DomainError as exc:
            return self._domain_error_response(exc, default_status=400)
        except Exception:
            logger.exception("Unexpected error during tenant selection")
            return self._error_response(500, "internal_error", "Internal server error")

        return self._success_response(200, result.model_dump())

    # ──── HTTPS enforcement (Req 7.5) ───────────────────────────────────────────

    def _https_redirect_if_needed(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Return a 301 redirect to HTTPS when the request arrived over HTTP.

        API Gateway forwards the original scheme in the ``X-Forwarded-Proto``
        header. When that scheme is ``http`` the request is answered with a 301
        redirect to the same host and path over HTTPS (Req 7.5). If the scheme
        cannot be determined it is assumed to be HTTPS (the API Gateway default)
        and no redirect is issued.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            A 301 redirect response dict, or ``None`` when the request is already
            HTTPS (or the scheme is unknown).
        """
        headers = self._normalized_headers(event)
        proto = (headers.get("x-forwarded-proto") or "").strip().lower()
        if proto != "http":
            return None

        host = headers.get("host") or ""
        path = event.get("path") or event.get("rawPath") or ""
        raw_query = event.get("queryStringParameters") or {}
        query = ""
        if raw_query:
            query = "?" + urlencode({k: v for k, v in raw_query.items() if v is not None})

        location = f"https://{host}{path}{query}"
        return {
            "statusCode": 301,
            "headers": {"Location": location, "Content-Type": "application/json"},
            "body": "",
        }

    # ──── State-failure logging (Req 10.5) ──────────────────────────────────────

    def _log_state_validation_failure(self, event: dict[str, Any]) -> None:
        """Log a state validation failure at WARNING with a masked source IP.

        The source IP is taken from the API Gateway request context (or the
        ``X-Forwarded-For`` header as a fallback) and masked by zeroing the last
        octet so the log never records a full client IP (Req 10.5).

        Args:
            event: API Gateway Lambda proxy event dict.
        """
        source_ip = self._extract_source_ip(event)
        masked_ip = self._mask_ip(source_ip)
        logger.warning(
            json.dumps(
                {
                    "event_type": "social_state_validation_failed",
                    "level": "WARNING",
                    "source_ip": masked_ip,
                }
            )
        )

    @staticmethod
    def _extract_source_ip(event: dict[str, Any]) -> str:
        """Extract the client source IP from the event.

        Prefers ``requestContext.identity.sourceIp`` (the API Gateway-provided
        value); falls back to the first entry of the ``X-Forwarded-For`` header.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            The source IP string, or an empty string when unavailable.
        """
        request_context = event.get("requestContext") or {}
        identity = request_context.get("identity") or {}
        source_ip = identity.get("sourceIp")
        if source_ip:
            return str(source_ip)

        headers = event.get("headers") or {}
        forwarded_for = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
        if forwarded_for:
            return str(forwarded_for).split(",")[0].strip()

        return ""

    @staticmethod
    def _mask_ip(source_ip: str) -> str:
        """Mask an IP address by zeroing its last octet (Req 10.5).

        IPv4 addresses have their final octet replaced with ``0`` (e.g.
        ``203.0.113.42`` → ``203.0.113.0``). Values that are not dotted-quad
        IPv4 (empty, IPv6, malformed) are reported as ``"unknown"`` so no full
        address is ever logged.

        Args:
            source_ip: The raw source IP string.

        Returns:
            The masked IP string, or ``"unknown"`` when it cannot be masked.
        """
        parts = source_ip.split(".")
        if len(parts) == 4 and all(part.isdigit() for part in parts):
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
        return "unknown"

    # ──── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _normalized_headers(event: dict[str, Any]) -> dict[str, str]:
        """Return the event headers keyed by lowercase name.

        API Gateway does not guarantee header-name casing, so headers are
        lower-cased for consistent lookups.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            A dict of the request headers with lowercase keys.
        """
        headers = event.get("headers") or {}
        return {str(k).lower(): v for k, v in headers.items()}

    @staticmethod
    def _parse_body(event: dict[str, Any]) -> dict[str, Any] | None:
        """Parse the JSON body from an API Gateway event.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            The parsed body dict, or ``None`` if the body is missing or invalid JSON.
        """
        raw_body = event.get("body")
        if not raw_body:
            return None

        if isinstance(raw_body, dict):
            return raw_body

        try:
            parsed = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError):
            return None

        return parsed if isinstance(parsed, dict) else None

    def _domain_error_response(
        self,
        error: DomainError,
        default_status: int = 400,
    ) -> dict[str, Any]:
        """Map a domain error to an error response using its message as the code.

        The domain-error ``message`` carries the error code string (e.g.
        ``"invalid_state"``). The HTTP status is looked up from the design's
        error-code→status mapping, falling back to ``default_status`` when the
        code is not in the table.

        Args:
            error: The raised domain error whose ``message`` is the error code.
            default_status: Status to use when the code is not in the mapping.

        Returns:
            An API Gateway error response dict.
        """
        code = error.message
        status_code = _STATUS_BY_ERROR_CODE.get(code, default_status)
        message = _MESSAGE_BY_ERROR_CODE.get(code, code)
        return self._error_response(status_code, code, message)

    @staticmethod
    def _success_response(status_code: int, data: dict[str, Any]) -> dict[str, Any]:
        """Build a success response dict for API Gateway.

        Args:
            status_code: HTTP status code.
            data: Response payload to serialize as JSON body.

        Returns:
            An API Gateway Lambda proxy response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data),
        }

    @staticmethod
    def _error_response(status_code: int, code: str, message: str) -> dict[str, Any]:
        """Build an error response dict for API Gateway.

        Args:
            status_code: HTTP status code.
            code: Machine-readable error code (the ``error`` field).
            message: Human-readable description (the ``message`` field).

        Returns:
            An API Gateway Lambda proxy response dict with the shape
            ``{"error": <code>, "message": <message>}``.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": code, "message": message}),
        }
