"""AuthController — handles authentication HTTP endpoints.

Maps API Gateway Lambda events to application-layer use cases for login,
token refresh, and logout. Catches domain errors and returns appropriate
HTTP status codes.

Implements Requirements:
- 1.1: User authentication via email, password, tenant_id
- 2.1: Token refresh delegated to Cognito
- 14.5: Logout via Cognito GlobalSignOut
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from application.dtos.auth.login_input_dto import LoginInputDTO
from domain.errors.domain_error import DomainError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.errors.validation_error import ValidationError

if TYPE_CHECKING:
    from application.ports.i_cognito_service import ICognitoService
    from application.use_cases.auth.login_use_case import LoginUseCase

logger = logging.getLogger(__name__)


class AuthController:
    """Controller for authentication endpoints (login, refresh, logout).

    Receives use cases and the Cognito service via constructor injection.
    Login is handled by the LoginUseCase, while refresh and logout are
    delegated directly to Cognito (tasks 6.3 and 6.5 were removed —
    Cognito manages these operations natively).
    """

    def __init__(
        self,
        login_use_case: LoginUseCase,
        cognito_service: ICognitoService,
    ) -> None:
        """Initialize the AuthController.

        Args:
            login_use_case: Use case for authenticating users.
            cognito_service: Cognito service for refresh and logout operations.
        """
        self._login_use_case = login_use_case
        self._cognito_service = cognito_service

    # ──── Login ───────────────────────────────────────────────────────────────

    async def handle_login(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /auth/login requests.

        Parses the request body, validates input via LoginInputDTO,
        delegates authentication to LoginUseCase, and returns the token
        pair with roles on success.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            API Gateway response dict with statusCode, headers, and body.
        """
        # Parse request body
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        # Validate input DTO
        try:
            input_dto = LoginInputDTO(
                email=body.get("email", ""),
                password=body.get("password", ""),
                tenant_id=body.get("tenant_id", ""),
            )
        except Exception:
            return self._error_response(400, "Invalid request: missing required fields")

        # Execute login use case
        try:
            result = await self._login_use_case.execute(input_dto)
        except InvalidCredentialsError:
            return self._error_response(401, "Invalid credentials")
        except ValidationError as e:
            return self._error_response(400, e.message)
        except DomainError as e:
            # "Account is not active" → 403
            if "not active" in e.message.lower():
                return self._error_response(403, e.message)
            return self._error_response(400, e.message)
        except Exception:
            logger.exception("Unexpected error during login")
            return self._error_response(500, "Internal server error")

        # Map output DTO to response
        return self._success_response(200, {
            "access_token": result.access_token,
            "id_token": result.id_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
            "roles": result.roles,
        })

    # ──── Refresh ─────────────────────────────────────────────────────────────

    async def handle_refresh(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /auth/refresh requests.

        Proxies the refresh_token to Cognito to obtain a new token pair.
        Since Cognito manages token lifecycle directly, this handler
        extracts the refresh token from the request body and calls
        Cognito's initiate_auth with the REFRESH_TOKEN_AUTH flow.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            API Gateway response dict with new tokens on success, 401 on failure.
        """
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        refresh_token = body.get("refresh_token", "").strip()
        if not refresh_token:
            return self._error_response(400, "Missing refresh_token")

        try:
            token_pair = await self._cognito_service.refresh_auth(refresh_token)
        except InvalidCredentialsError:
            return self._error_response(401, "Invalid or expired refresh token")
        except Exception:
            logger.exception("Unexpected error during token refresh")
            return self._error_response(500, "Internal server error")

        return self._success_response(200, {
            "access_token": token_pair.access_token,
            "id_token": token_pair.id_token,
            "expires_in": token_pair.expires_in,
        })

    # ──── Logout ──────────────────────────────────────────────────────────────

    async def handle_logout(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /auth/logout requests.

        Delegates to Cognito GlobalSignOut to invalidate all tokens
        associated with the user's session. Requires the access_token
        to identify the user.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            API Gateway response dict with 204 on success, 401 on failure.
        """
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        access_token = body.get("access_token", "").strip()
        if not access_token:
            return self._error_response(400, "Missing access_token")

        try:
            await self._cognito_service.global_sign_out(access_token)
        except InvalidCredentialsError:
            return self._error_response(401, "Invalid or expired token")
        except Exception:
            logger.exception("Unexpected error during logout")
            return self._error_response(500, "Internal server error")

        return {
            "statusCode": 204,
            "headers": {"Content-Type": "application/json"},
            "body": "",
        }

    # ──── Private Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_body(event: dict[str, Any]) -> dict[str, Any] | None:
        """Parse the JSON body from an API Gateway event.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            Parsed body dict, or None if body is missing or invalid JSON.
        """
        raw_body = event.get("body")
        if not raw_body:
            return None

        if isinstance(raw_body, dict):
            return raw_body

        try:
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                return parsed
            return None
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _success_response(status_code: int, data: dict[str, Any]) -> dict[str, Any]:
        """Build a success response dict for API Gateway.

        Args:
            status_code: HTTP status code (200, 201, etc.).
            data: Response payload to serialize as JSON body.

        Returns:
            API Gateway Lambda response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data),
        }

    @staticmethod
    def _error_response(status_code: int, message: str) -> dict[str, Any]:
        """Build an error response dict for API Gateway.

        Args:
            status_code: HTTP error status code (400, 401, 403, 500).
            message: Human-readable error message.

        Returns:
            API Gateway Lambda response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": message}),
        }
