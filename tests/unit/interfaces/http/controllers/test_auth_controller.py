"""Unit tests for AuthController."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.dtos.auth.login_output_dto import LoginOutputDTO
from domain.entities.token_pair import TokenPair
from domain.errors.domain_error import DomainError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.errors.validation_error import ValidationError
from interfaces.http.controllers.auth_controller import AuthController


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
