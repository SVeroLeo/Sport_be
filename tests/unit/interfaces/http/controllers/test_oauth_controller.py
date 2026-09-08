"""Unit tests for OAuthController.

Covers the cross-cutting and error-mapping behaviour of the social-login
endpoints:

* Missing ``provider`` on authorize maps a domain ``ValidationError`` to 400
  (Requirement 2.3).
* Missing ``code`` on callback returns 400 directly before invoking the use case
  (Requirement 3.3).
* A plain-HTTP request is answered with a 301 redirect to HTTPS
  (Requirement 7.5).
* A pending-tenant callback surfaces ``requires_tenant_selection: true`` in the
  200 response body (Requirements 7.4).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.dtos.social_login_dtos import (
    SocialAuthorizeOutputDTO,
    SocialLoginOutputDTO,
)
from domain.errors.validation_error import ValidationError
from interfaces.http.controllers.oauth_controller import OAuthController


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_social_authorize_use_case() -> MagicMock:
    """Create a mock SocialAuthorizeUseCase (execute is synchronous)."""
    return MagicMock()


@pytest.fixture
def mock_social_callback_use_case() -> AsyncMock:
    """Create a mock SocialCallbackUseCase (execute is async)."""
    return AsyncMock()


@pytest.fixture
def mock_tenant_association_use_case() -> AsyncMock:
    """Create a mock TenantAssociationUseCase (execute is async)."""
    return AsyncMock()


@pytest.fixture
def mock_auth_guard() -> MagicMock:
    """Create a mock AuthGuardMiddleware."""
    return MagicMock()


@pytest.fixture
def controller(
    mock_social_authorize_use_case: MagicMock,
    mock_social_callback_use_case: AsyncMock,
    mock_tenant_association_use_case: AsyncMock,
    mock_auth_guard: MagicMock,
) -> OAuthController:
    """Create an OAuthController with mocked dependencies."""
    return OAuthController(
        social_authorize_use_case=mock_social_authorize_use_case,
        social_callback_use_case=mock_social_callback_use_case,
        tenant_association_use_case=mock_tenant_association_use_case,
        auth_guard=mock_auth_guard,
    )


def _make_event(
    *,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    path: str = "/auth/social/authorize",
) -> dict[str, Any]:
    """Build a minimal API Gateway proxy event.

    Defaults to an HTTPS request (``X-Forwarded-Proto: https``) so tests that do
    not care about scheme are not accidentally redirected.
    """
    request_headers = {"X-Forwarded-Proto": "https", "Host": "api.example.com"}
    if headers:
        request_headers.update(headers)
    return {
        "path": path,
        "headers": request_headers,
        "queryStringParameters": query,
        "requestContext": {"identity": {"sourceIp": "203.0.113.42"}},
    }


# ──── handle_authorize Tests ──────────────────────────────────────────────────


class TestHandleAuthorize:
    """Tests for OAuthController.handle_authorize."""

    def test_missing_provider_returns_400(
        self, controller: OAuthController, mock_social_authorize_use_case: MagicMock
    ) -> None:
        """Missing provider -> use case raises ValidationError -> 400.

        Validates: Requirements 2.3
        """
        mock_social_authorize_use_case.execute.side_effect = ValidationError("invalid_provider")

        event = _make_event(query=None)

        response = controller.handle_authorize(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "invalid_provider"

    def test_http_request_returns_301_to_https(
        self, controller: OAuthController, mock_social_authorize_use_case: MagicMock
    ) -> None:
        """A plain-HTTP authorize request is answered with a 301 to HTTPS.

        Validates: Requirements 7.5
        """
        event = _make_event(
            query={"provider": "Google"},
            headers={"X-Forwarded-Proto": "http"},
            path="/auth/social/authorize",
        )

        response = controller.handle_authorize(event)

        assert response["statusCode"] == 301
        location = response["headers"]["Location"]
        assert location.startswith("https://")
        assert location == "https://api.example.com/auth/social/authorize?provider=Google"
        # The use case must not run for a redirect.
        mock_social_authorize_use_case.execute.assert_not_called()

    def test_valid_provider_returns_200(
        self, controller: OAuthController, mock_social_authorize_use_case: MagicMock
    ) -> None:
        """A valid provider returns 200 with the authorization URL."""
        mock_social_authorize_use_case.execute.return_value = SocialAuthorizeOutputDTO(
            authorization_url="https://auth.example.com/oauth2/authorize?provider=Google"
        )

        event = _make_event(query={"provider": "Google"})

        response = controller.handle_authorize(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["authorization_url"].startswith("https://auth.example.com")


# ──── handle_callback Tests ───────────────────────────────────────────────────


class TestHandleCallback:
    """Tests for OAuthController.handle_callback."""

    @pytest.mark.asyncio
    async def test_missing_code_returns_400(
        self, controller: OAuthController, mock_social_callback_use_case: AsyncMock
    ) -> None:
        """Missing code query param -> 400 before the use case is called.

        Validates: Requirements 3.3
        """
        event = _make_event(
            query={"state": "some-state"},
            path="/auth/social/callback",
        )

        response = await controller.handle_callback(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "invalid_request"
        mock_social_callback_use_case.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_http_request_returns_301_to_https(
        self, controller: OAuthController, mock_social_callback_use_case: AsyncMock
    ) -> None:
        """A plain-HTTP callback request is answered with a 301 to HTTPS.

        Validates: Requirements 7.5
        """
        event = _make_event(
            query={"code": "auth-code", "state": "state-token"},
            headers={"X-Forwarded-Proto": "http"},
            path="/auth/social/callback",
        )

        response = await controller.handle_callback(event)

        assert response["statusCode"] == 301
        assert response["headers"]["Location"].startswith("https://")
        mock_social_callback_use_case.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_tenant_response_includes_requires_tenant_selection(
        self, controller: OAuthController, mock_social_callback_use_case: AsyncMock
    ) -> None:
        """Pending-tenant callback surfaces requires_tenant_selection: true.

        Validates: Requirements 7.4
        """
        mock_social_callback_use_case.execute.return_value = SocialLoginOutputDTO(
            access_token="access-token-123",
            id_token="id-token-456",
            refresh_token="refresh-token-789",
            expires_in=3600,
            user_id="550e8400-e29b-41d4-a716-446655440000",
            requires_tenant_selection=True,
        )

        event = _make_event(
            query={"code": "auth-code", "state": "state-token"},
            path="/auth/social/callback",
        )

        response = await controller.handle_callback(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["requires_tenant_selection"] is True
        assert body["access_token"] == "access-token-123"
        mock_social_callback_use_case.execute.assert_awaited_once_with(
            code="auth-code", state="state-token"
        )
