"""AuthController — handles authentication HTTP endpoints.

Maps API Gateway Lambda events to application-layer use cases for login,
token refresh, and logout. Catches domain errors and returns appropriate
HTTP status codes.

Implements Requirements:
- 1.1: User authentication via email + password (tenant-agnostic; tenant resolved
       from the user's default_tenant_id)
- 2.1: Token refresh delegated to Cognito
- 14.5: Logout via Cognito GlobalSignOut
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from application.dtos.auth.confirm_forgot_password_input_dto import (
    ConfirmForgotPasswordInputDTO,
)
from application.dtos.auth.forgot_password_input_dto import ForgotPasswordInputDTO
from application.dtos.auth.login_input_dto import LoginInputDTO
from application.dtos.auth.respond_to_challenge_input_dto import (
    RespondToChallengeInputDTO,
)
from domain.errors.domain_error import DomainError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.errors.rate_limit_error import RateLimitError
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

        # Validate input DTO (login is tenant-agnostic: email + password only)
        try:
            input_dto = LoginInputDTO(
                email=body.get("email", ""),
                password=body.get("password", ""),
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

        # Map output DTO to response. default_tenant_id is informational context;
        # the access token itself is tenant-agnostic (resolved per-request server-side).
        return self._success_response(200, {
            "access_token": result.access_token,
            "id_token": result.id_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
            "default_tenant_id": result.default_tenant_id,
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

    # ──── Forgot Password ─────────────────────────────────────────────────────

    async def handle_forgot_password(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /auth/forgot-password requests.

        Initiates password recovery via Cognito. To prevent user enumeration,
        the response is byte-identical whether or not the email is registered:
        the adapter swallows ``UserNotFoundException`` and this handler always
        returns the same generic 200 message on success.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            API Gateway response dict. Always 200 with a generic message on
            success; 400 for invalid input, 429 on rate limit, 500 on error.
        """
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        try:
            input_dto = ForgotPasswordInputDTO(email=body.get("email", ""))
        except Exception:
            return self._error_response(400, "Invalid request: invalid email")

        try:
            await self._cognito_service.forgot_password(input_dto.email)
        except RateLimitError:
            return self._error_response(429, "Too many requests, please try again later")
        except Exception:
            logger.exception("Unexpected error during forgot-password")
            return self._error_response(500, "Internal server error")

        # Always the same generic response (anti-enumeration; the adapter
        # already swallows UserNotFound).
        return self._success_response(200, {
            "message": "If an account exists for this email, a reset code has been sent.",
        })

    # ──── Confirm Forgot Password ─────────────────────────────────────────────

    async def handle_confirm_forgot_password(
        self, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle POST /auth/confirm-forgot-password requests.

        Completes the password reset using the confirmation code emailed to
        the user plus a new password. The success response never contains
        authentication tokens — the user must log in afterward.

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            API Gateway response dict. 200 with a generic message on success;
            400 for invalid input or policy/code errors, 429 on rate limit,
            500 on unexpected error.
        """
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        try:
            input_dto = ConfirmForgotPasswordInputDTO(
                email=body.get("email", ""),
                confirmation_code=body.get("confirmation_code", ""),
                new_password=body.get("new_password", ""),
            )
        except Exception:
            return self._error_response(400, "Invalid request: missing required fields")

        try:
            await self._cognito_service.confirm_forgot_password(
                input_dto.email,
                input_dto.confirmation_code,
                input_dto.new_password,
            )
        except ValidationError as e:
            return self._error_response(400, e.message)
        except RateLimitError:
            return self._error_response(429, "Too many requests, please try again later")
        except Exception:
            logger.exception("Unexpected error during confirm-forgot-password")
            return self._error_response(500, "Internal server error")

        # Success response never carries tokens (Req 2.3).
        return self._success_response(200, {
            "message": "Password has been reset. Please log in.",
        })

    # ──── Respond To Challenge ────────────────────────────────────────────────

    async def handle_respond_to_challenge(
        self, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle POST /auth/respond-to-challenge requests.

        Answers a pending Cognito authentication challenge. On success the
        result is bimodal: either an authenticated Token_Set (same shape as
        login, without a ``challenge_name``) or the next challenge to solve
        (``challenge_name`` + ``session``, without tokens).

        Args:
            event: API Gateway Lambda proxy event dict.

        Returns:
            API Gateway response dict. 200 with tokens or next-challenge on
            success; 400 for invalid input/policy errors, 401 for an invalid
            or expired session, 500 on unexpected error.
        """
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        try:
            input_dto = RespondToChallengeInputDTO(
                challenge_name=body.get("challenge_name", ""),
                session=body.get("session", ""),
                # Default to an empty dict so a missing value fails validation
                # (challenge_responses must be a non-empty map).
                challenge_responses=body.get("challenge_responses", {}),
            )
        except Exception:
            return self._error_response(400, "Invalid request: missing or invalid fields")

        try:
            result = await self._cognito_service.respond_to_challenge(
                input_dto.challenge_name,
                input_dto.session,
                input_dto.challenge_responses,
            )
        except InvalidCredentialsError:
            return self._error_response(401, "Challenge session is invalid or expired")
        except ValidationError as e:
            return self._error_response(400, e.message)
        except Exception:
            logger.exception("Unexpected error during respond-to-challenge")
            return self._error_response(500, "Internal server error")

        if result.is_authenticated():
            token_pair = result.token_pair
            return self._success_response(200, {
                "access_token": token_pair.access_token,
                "id_token": token_pair.id_token,
                "refresh_token": token_pair.refresh_token,
                "expires_in": token_pair.expires_in,
            })

        return self._success_response(200, {
            "challenge_name": result.next_challenge_name,
            "session": result.next_session,
        })

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
