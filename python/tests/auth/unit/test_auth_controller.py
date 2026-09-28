"""Unit tests for AuthController."""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.auth.loginOutputDto import LoginOutputDTO
from api.auth.challengeResult import ChallengeResult
from api.auth.tokenPair import TokenPair
from api.common.errors.domainError import DomainError
from api.common.errors.invalidCredentialsError import InvalidCredentialsError
from api.common.errors.rateLimitError import RateLimitError
from api.common.errors.validationError import ValidationError
from api.auth.authController import AuthController


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_login_use_case() -> AsyncMock:
    """Create a mock LoginUseCase."""
    return AsyncMock()


@pytest.fixture
def mock_cognito_service() -> AsyncMock:
    """Create a mock ICognitoService."""
    return AsyncMock()


@pytest.fixture
def controller(mock_login_use_case: AsyncMock, mock_cognito_service: AsyncMock) -> AuthController:
    """Create an AuthController with mocked dependencies."""
    return AuthController(
        login_use_case=mock_login_use_case,
        cognito_service=mock_cognito_service,
    )


def _make_event(body: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """Build a minimal API Gateway event with an optional body."""
    event: dict[str, Any] = {"headers": {}}
    if body is not None:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body
    return event


# ──── handle_login Tests ──────────────────────────────────────────────────────


class TestHandleLogin:
    """Tests for AuthController.handle_login."""

    @pytest.mark.asyncio
    async def test_successful_login_returns_200_with_tokens(
        self, controller: AuthController, mock_login_use_case: AsyncMock
    ) -> None:
        """Successful login returns 200 with token pair and roles."""
        mock_login_use_case.execute.return_value = LoginOutputDTO(
            access_token="access-token-123",
            id_token="id-token-456",
            refresh_token="refresh-token-789",
            expires_in=3600,
            default_tenant_id="550e8400-e29b-41d4-a716-446655440000",
            roles=["admin", "viewer"],
        )

        # Login is tenant-agnostic: request carries only email + password.
        event = _make_event({
            "email": "user@example.com",
            "password": "SecureP@ss1",
        })

        response = await controller.handle_login(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["access_token"] == "access-token-123"
        assert body["id_token"] == "id-token-456"
        assert body["refresh_token"] == "refresh-token-789"
        assert body["expires_in"] == 3600
        # default_tenant_id is returned as informational context only.
        assert body["default_tenant_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert body["roles"] == ["admin", "viewer"]
        assert response["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(self, controller: AuthController) -> None:
        """Request with no body returns 400."""
        event: dict[str, Any] = {"headers": {}}

        response = await controller.handle_login(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"

    @pytest.mark.asyncio
    async def test_invalid_json_body_returns_400(self, controller: AuthController) -> None:
        """Request with invalid JSON body returns 400."""
        event: dict[str, Any] = {"headers": {}, "body": "not json"}

        response = await controller.handle_login(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"

    @pytest.mark.asyncio
    async def test_invalid_credentials_returns_401(
        self, controller: AuthController, mock_login_use_case: AsyncMock
    ) -> None:
        """InvalidCredentialsError from use case returns 401."""
        mock_login_use_case.execute.side_effect = InvalidCredentialsError()

        event = _make_event({
            "email": "bad@example.com",
            "password": "wrong",
        })

        response = await controller.handle_login(event)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_validation_error_returns_400(
        self, controller: AuthController, mock_login_use_case: AsyncMock
    ) -> None:
        """ValidationError from use case returns 400 with the message."""
        mock_login_use_case.execute.side_effect = ValidationError("Invalid email format", field="email")

        event = _make_event({
            "email": "not-valid",
            "password": "Password1!",
        })

        response = await controller.handle_login(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid email format"

    @pytest.mark.asyncio
    async def test_inactive_account_returns_403(
        self, controller: AuthController, mock_login_use_case: AsyncMock
    ) -> None:
        """DomainError 'Account is not active' returns 403."""
        mock_login_use_case.execute.side_effect = DomainError("Account is not active")

        event = _make_event({
            "email": "user@example.com",
            "password": "Password1!",
        })

        response = await controller.handle_login(event)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert body["error"] == "Account is not active"

    @pytest.mark.asyncio
    async def test_generic_domain_error_returns_400(
        self, controller: AuthController, mock_login_use_case: AsyncMock
    ) -> None:
        """Non-specific DomainError returns 400."""
        mock_login_use_case.execute.side_effect = DomainError("Some domain issue")

        event = _make_event({
            "email": "user@example.com",
            "password": "Password1!",
        })

        response = await controller.handle_login(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Some domain issue"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(
        self, controller: AuthController, mock_login_use_case: AsyncMock
    ) -> None:
        """Unexpected exception returns 500."""
        mock_login_use_case.execute.side_effect = RuntimeError("something broke")

        event = _make_event({
            "email": "user@example.com",
            "password": "Password1!",
        })

        response = await controller.handle_login(event)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_body_already_parsed_as_dict(
        self, controller: AuthController, mock_login_use_case: AsyncMock
    ) -> None:
        """Body that's already a dict (pre-parsed by gateway) works."""
        mock_login_use_case.execute.return_value = LoginOutputDTO(
            access_token="at",
            id_token="it",
            refresh_token="rt",
            expires_in=1800,
            default_tenant_id="550e8400-e29b-41d4-a716-446655440000",
            roles=["viewer"],
        )

        event: dict[str, Any] = {
            "headers": {},
            "body": {
                "email": "user@example.com",
                "password": "Password1!",
            },
        }

        response = await controller.handle_login(event)

        assert response["statusCode"] == 200


# ──── handle_refresh Tests ────────────────────────────────────────────────────


class TestHandleRefresh:
    """Tests for AuthController.handle_refresh."""

    @pytest.mark.asyncio
    async def test_successful_refresh_returns_200(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Successful token refresh returns 200 with new tokens."""
        mock_cognito_service.refresh_auth.return_value = TokenPair(
            access_token="new-access-token",
            id_token="new-id-token",
            refresh_token="",
            expires_in=3600,
        )

        event = _make_event({"refresh_token": "valid-refresh-token"})

        response = await controller.handle_refresh(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["access_token"] == "new-access-token"
        assert body["id_token"] == "new-id-token"
        assert body["expires_in"] == 3600
        mock_cognito_service.refresh_auth.assert_called_once_with("valid-refresh-token")

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(self, controller: AuthController) -> None:
        """Request with no body returns 400."""
        event: dict[str, Any] = {"headers": {}}

        response = await controller.handle_refresh(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"

    @pytest.mark.asyncio
    async def test_missing_refresh_token_returns_400(self, controller: AuthController) -> None:
        """Request without refresh_token field returns 400."""
        event = _make_event({"other": "field"})

        response = await controller.handle_refresh(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Missing refresh_token"

    @pytest.mark.asyncio
    async def test_empty_refresh_token_returns_400(self, controller: AuthController) -> None:
        """Request with empty refresh_token returns 400."""
        event = _make_event({"refresh_token": "   "})

        response = await controller.handle_refresh(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Missing refresh_token"

    @pytest.mark.asyncio
    async def test_invalid_refresh_token_returns_401(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Invalid refresh token results in 401."""
        mock_cognito_service.refresh_auth.side_effect = InvalidCredentialsError()

        event = _make_event({"refresh_token": "expired-token"})

        response = await controller.handle_refresh(event)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or expired refresh token"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Unexpected exception during refresh returns 500."""
        mock_cognito_service.refresh_auth.side_effect = RuntimeError("AWS down")

        event = _make_event({"refresh_token": "some-token"})

        response = await controller.handle_refresh(event)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "Internal server error"


# ──── handle_logout Tests ─────────────────────────────────────────────────────


class TestHandleLogout:
    """Tests for AuthController.handle_logout."""

    @pytest.mark.asyncio
    async def test_successful_logout_returns_204(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Successful logout returns 204 with empty body."""
        mock_cognito_service.global_sign_out.return_value = None

        event = _make_event({"access_token": "valid-access-token"})

        response = await controller.handle_logout(event)

        assert response["statusCode"] == 204
        assert response["body"] == ""
        mock_cognito_service.global_sign_out.assert_called_once_with("valid-access-token")

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(self, controller: AuthController) -> None:
        """Request with no body returns 400."""
        event: dict[str, Any] = {"headers": {}}

        response = await controller.handle_logout(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"

    @pytest.mark.asyncio
    async def test_missing_access_token_returns_400(self, controller: AuthController) -> None:
        """Request without access_token field returns 400."""
        event = _make_event({"other": "field"})

        response = await controller.handle_logout(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Missing access_token"

    @pytest.mark.asyncio
    async def test_empty_access_token_returns_400(self, controller: AuthController) -> None:
        """Request with empty access_token returns 400."""
        event = _make_event({"access_token": ""})

        response = await controller.handle_logout(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Missing access_token"

    @pytest.mark.asyncio
    async def test_invalid_access_token_returns_401(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Invalid access token results in 401."""
        mock_cognito_service.global_sign_out.side_effect = InvalidCredentialsError()

        event = _make_event({"access_token": "expired-token"})

        response = await controller.handle_logout(event)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or expired token"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Unexpected exception during logout returns 500."""
        mock_cognito_service.global_sign_out.side_effect = RuntimeError("network error")

        event = _make_event({"access_token": "some-token"})

        response = await controller.handle_logout(event)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "Internal server error"


# ──── handle_forgot_password Tests ────────────────────────────────────────────


class TestHandleForgotPassword:
    """Tests for AuthController.handle_forgot_password."""

    _GENERIC_MESSAGE = "If an account exists for this email, a reset code has been sent."

    @pytest.mark.asyncio
    async def test_successful_forgot_password_returns_200(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Successful request returns 200 with the generic anti-enumeration message."""
        mock_cognito_service.forgot_password.return_value = None

        event = _make_event({"email": "user@example.com"})

        response = await controller.handle_forgot_password(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == self._GENERIC_MESSAGE
        mock_cognito_service.forgot_password.assert_awaited_once_with("user@example.com")

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Request with no body returns 400 and does not call Cognito."""
        event: dict[str, Any] = {"headers": {}}

        response = await controller.handle_forgot_password(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"
        mock_cognito_service.forgot_password.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_json_body_returns_400(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Request with invalid JSON body returns 400 and does not call Cognito."""
        event: dict[str, Any] = {"headers": {}, "body": "not json"}

        response = await controller.handle_forgot_password(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"
        mock_cognito_service.forgot_password.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_email_returns_400_and_skips_cognito(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """A syntactically invalid email returns 400 without invoking Cognito."""
        event = _make_event({"email": "not-an-email"})

        response = await controller.handle_forgot_password(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid request: invalid email"
        mock_cognito_service.forgot_password.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """RateLimitError from Cognito returns 429."""
        mock_cognito_service.forgot_password.side_effect = RateLimitError()

        event = _make_event({"email": "user@example.com"})

        response = await controller.handle_forgot_password(event)

        assert response["statusCode"] == 429
        body = json.loads(response["body"])
        assert body["error"] == "Too many requests, please try again later"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Unexpected exception returns 500."""
        mock_cognito_service.forgot_password.side_effect = RuntimeError("AWS down")

        event = _make_event({"email": "user@example.com"})

        response = await controller.handle_forgot_password(event)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "Internal server error"


# ──── handle_confirm_forgot_password Tests ────────────────────────────────────


class TestHandleConfirmForgotPassword:
    """Tests for AuthController.handle_confirm_forgot_password."""

    @pytest.mark.asyncio
    async def test_successful_confirm_returns_200_without_tokens(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Success returns 200 with a generic message and no auth tokens (Req 2.3)."""
        mock_cognito_service.confirm_forgot_password.return_value = None

        event = _make_event({
            "email": "user@example.com",
            "confirmation_code": "123456",
            "new_password": "NewSecureP@ss1",
        })

        response = await controller.handle_confirm_forgot_password(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "Password has been reset. Please log in."
        # No authentication tokens leak into the confirm response.
        assert "access_token" not in body
        assert "id_token" not in body
        assert "refresh_token" not in body
        mock_cognito_service.confirm_forgot_password.assert_awaited_once_with(
            "user@example.com", "123456", "NewSecureP@ss1"
        )

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Request with no body returns 400 and does not call Cognito."""
        event: dict[str, Any] = {"headers": {}}

        response = await controller.handle_confirm_forgot_password(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"
        mock_cognito_service.confirm_forgot_password.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_field_returns_400_and_skips_cognito(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """A missing required field returns 400 without invoking Cognito."""
        event = _make_event({
            "email": "user@example.com",
            "confirmation_code": "123456",
            # new_password missing
        })

        response = await controller.handle_confirm_forgot_password(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid request: missing required fields"
        mock_cognito_service.confirm_forgot_password.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_error_returns_400_with_message(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """ValidationError from Cognito (e.g. bad code) returns 400 with the message."""
        mock_cognito_service.confirm_forgot_password.side_effect = ValidationError(
            "Invalid confirmation code"
        )

        event = _make_event({
            "email": "user@example.com",
            "confirmation_code": "000000",
            "new_password": "NewSecureP@ss1",
        })

        response = await controller.handle_confirm_forgot_password(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid confirmation code"

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """RateLimitError from Cognito returns 429."""
        mock_cognito_service.confirm_forgot_password.side_effect = RateLimitError()

        event = _make_event({
            "email": "user@example.com",
            "confirmation_code": "123456",
            "new_password": "NewSecureP@ss1",
        })

        response = await controller.handle_confirm_forgot_password(event)

        assert response["statusCode"] == 429
        body = json.loads(response["body"])
        assert body["error"] == "Too many requests, please try again later"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Unexpected exception returns 500."""
        mock_cognito_service.confirm_forgot_password.side_effect = RuntimeError("AWS down")

        event = _make_event({
            "email": "user@example.com",
            "confirmation_code": "123456",
            "new_password": "NewSecureP@ss1",
        })

        response = await controller.handle_confirm_forgot_password(event)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "Internal server error"


# ──── handle_respond_to_challenge Tests ───────────────────────────────────────


class TestHandleRespondToChallenge:
    """Tests for AuthController.handle_respond_to_challenge."""

    @pytest.mark.asyncio
    async def test_authenticated_result_returns_200_with_tokens(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """An authenticated ChallengeResult returns 200 with the token set and no challenge_name."""
        mock_cognito_service.respond_to_challenge.return_value = ChallengeResult.authenticated(
            TokenPair(
                access_token="access-token-123",
                id_token="id-token-456",
                refresh_token="refresh-token-789",
                expires_in=3600,
            )
        )

        event = _make_event({
            "challenge_name": "NEW_PASSWORD_REQUIRED",
            "session": "session-token-abc",
            "challenge_responses": {"NEW_PASSWORD": "NewSecureP@ss1", "USERNAME": "user"},
        })

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["access_token"] == "access-token-123"
        assert body["id_token"] == "id-token-456"
        assert body["refresh_token"] == "refresh-token-789"
        assert body["expires_in"] == 3600
        # Authenticated shape carries no challenge_name.
        assert "challenge_name" not in body
        mock_cognito_service.respond_to_challenge.assert_awaited_once_with(
            "NEW_PASSWORD_REQUIRED",
            "session-token-abc",
            {"NEW_PASSWORD": "NewSecureP@ss1", "USERNAME": "user"},
        )

    @pytest.mark.asyncio
    async def test_next_challenge_result_returns_200_without_tokens(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """A next-challenge ChallengeResult returns 200 with challenge_name + session and no tokens."""
        mock_cognito_service.respond_to_challenge.return_value = ChallengeResult.next_challenge(
            "SMS_MFA", "next-session-xyz"
        )

        event = _make_event({
            "challenge_name": "SOFTWARE_TOKEN_MFA",
            "session": "session-token-abc",
            "challenge_responses": {"SOFTWARE_TOKEN_MFA_CODE": "000111"},
        })

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["challenge_name"] == "SMS_MFA"
        assert body["session"] == "next-session-xyz"
        # Next-challenge shape carries no tokens.
        assert "access_token" not in body
        assert "id_token" not in body
        assert "refresh_token" not in body

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Request with no body returns 400 and does not call Cognito."""
        event: dict[str, Any] = {"headers": {}}

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid or missing request body"
        mock_cognito_service.respond_to_challenge.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsupported_challenge_name_returns_400_and_skips_cognito(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """An unsupported challenge_name returns 400 without invoking Cognito."""
        event = _make_event({
            "challenge_name": "NOT_A_REAL_CHALLENGE",
            "session": "session-token-abc",
            "challenge_responses": {"NEW_PASSWORD": "NewSecureP@ss1"},
        })

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid request: missing or invalid fields"
        mock_cognito_service.respond_to_challenge.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_challenge_responses_returns_400_and_skips_cognito(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """An empty challenge_responses map returns 400 without invoking Cognito."""
        event = _make_event({
            "challenge_name": "NEW_PASSWORD_REQUIRED",
            "session": "session-token-abc",
            "challenge_responses": {},
        })

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Invalid request: missing or invalid fields"
        mock_cognito_service.respond_to_challenge.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_credentials_returns_401(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """InvalidCredentialsError (invalid/expired session) returns 401."""
        mock_cognito_service.respond_to_challenge.side_effect = InvalidCredentialsError()

        event = _make_event({
            "challenge_name": "NEW_PASSWORD_REQUIRED",
            "session": "expired-session",
            "challenge_responses": {"NEW_PASSWORD": "NewSecureP@ss1"},
        })

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "Challenge session is invalid or expired"

    @pytest.mark.asyncio
    async def test_validation_error_returns_400_with_message(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """ValidationError (e.g. password policy) returns 400 with the message."""
        mock_cognito_service.respond_to_challenge.side_effect = ValidationError(
            "Password does not meet policy"
        )

        event = _make_event({
            "challenge_name": "NEW_PASSWORD_REQUIRED",
            "session": "session-token-abc",
            "challenge_responses": {"NEW_PASSWORD": "weak"},
        })

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "Password does not meet policy"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(
        self, controller: AuthController, mock_cognito_service: AsyncMock
    ) -> None:
        """Unexpected exception returns 500."""
        mock_cognito_service.respond_to_challenge.side_effect = RuntimeError("AWS down")

        event = _make_event({
            "challenge_name": "NEW_PASSWORD_REQUIRED",
            "session": "session-token-abc",
            "challenge_responses": {"NEW_PASSWORD": "NewSecureP@ss1"},
        })

        response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "Internal server error"


# ──── Secrets-not-logged Tests ────────────────────────────────────────────────


class TestSecretsNotLogged:
    """Ensure sensitive inputs never reach log output (Req 4.3)."""

    @pytest.mark.asyncio
    async def test_confirm_forgot_password_does_not_log_new_password(
        self, controller: AuthController, mock_cognito_service: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A logged error path for confirm-forgot-password must not leak the new_password."""
        secret_password = "S3cret-N3ver-Log-Me!"
        mock_cognito_service.confirm_forgot_password.side_effect = RuntimeError("AWS down")

        event = _make_event({
            "email": "user@example.com",
            "confirmation_code": "123456",
            "new_password": secret_password,
        })

        with caplog.at_level(logging.DEBUG):
            response = await controller.handle_confirm_forgot_password(event)

        assert response["statusCode"] == 500
        assert secret_password not in caplog.text

    @pytest.mark.asyncio
    async def test_respond_to_challenge_does_not_log_session_or_password(
        self, controller: AuthController, mock_cognito_service: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A logged error path for respond-to-challenge must not leak the session or new_password."""
        secret_session = "sess-DO-NOT-LOG-abcdef123456"
        secret_password = "Ch4llenge-S3cret!"
        mock_cognito_service.respond_to_challenge.side_effect = RuntimeError("AWS down")

        event = _make_event({
            "challenge_name": "NEW_PASSWORD_REQUIRED",
            "session": secret_session,
            "challenge_responses": {"NEW_PASSWORD": secret_password},
        })

        with caplog.at_level(logging.DEBUG):
            response = await controller.handle_respond_to_challenge(event)

        assert response["statusCode"] == 500
        assert secret_session not in caplog.text
        assert secret_password not in caplog.text
