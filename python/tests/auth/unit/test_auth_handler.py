"""Unit tests for ``auth_handler`` routing.

Verifies that the auth Lambda handler dispatches POST requests to the
correct ``AuthController`` method based on the resource suffix, guards the
shared ``/forgot-password`` suffix by ordering ``/confirm-forgot-password``
first, returns 405 with an ``Allow: POST`` header for non-POST methods, and
returns 404 for unknown routes.

Requirements: 1.9, 2.13, 3.11, 4.5
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Sentinel responses returned by the mocked controller so tests can assert the
# handler passes the controller's response through unchanged.
_OK = {"statusCode": 200, "body": "ok"}


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_event(method: str, resource: str) -> dict[str, Any]:
    """Build a minimal API Gateway Lambda proxy event."""
    return {
        "httpMethod": method,
        "resource": resource,
        "headers": {},
        "queryStringParameters": None,
        "pathParameters": None,
    }


def _mock_container() -> MagicMock:
    """Create a mock container whose ``auth_controller`` has async handlers."""
    container = MagicMock()
    container.auth_controller.handle_login = AsyncMock(return_value=_OK)
    container.auth_controller.handle_refresh = AsyncMock(return_value=_OK)
    container.auth_controller.handle_logout = AsyncMock(return_value=_OK)
    container.auth_controller.handle_forgot_password = AsyncMock(return_value=_OK)
    container.auth_controller.handle_confirm_forgot_password = AsyncMock(
        return_value=_OK
    )
    container.auth_controller.handle_respond_to_challenge = AsyncMock(
        return_value=_OK
    )
    return container


class TestAuthHandlerRouting:
    """Routing tests for the auth_handler entry point."""

    @patch("api.common.compositionRoot.get_container")
    def test_forgot_password_routes_to_handle_forgot_password(
        self, mock_get_container: MagicMock
    ) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event("POST", "/auth/forgot-password")
        result = handler(event, None)

        container.auth_controller.handle_forgot_password.assert_called_once_with(event)
        assert result is _OK

    @patch("api.common.compositionRoot.get_container")
    def test_confirm_forgot_password_routes_to_confirm_not_forgot(
        self, mock_get_container: MagicMock
    ) -> None:
        # Guards the shared-suffix ordering: /confirm-forgot-password must not
        # fall through to the /forgot-password branch.
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event("POST", "/auth/confirm-forgot-password")
        result = handler(event, None)

        container.auth_controller.handle_confirm_forgot_password.assert_called_once_with(
            event
        )
        container.auth_controller.handle_forgot_password.assert_not_called()
        assert result is _OK

    @patch("api.common.compositionRoot.get_container")
    def test_respond_to_challenge_routes_to_handle_respond_to_challenge(
        self, mock_get_container: MagicMock
    ) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event("POST", "/auth/respond-to-challenge")
        result = handler(event, None)

        container.auth_controller.handle_respond_to_challenge.assert_called_once_with(
            event
        )
        assert result is _OK

    @patch("api.common.compositionRoot.get_container")
    def test_login_still_routes_to_handle_login(
        self, mock_get_container: MagicMock
    ) -> None:
        # Regression: existing routes are unaffected by the new branches.
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event("POST", "/auth/login")
        result = handler(event, None)

        container.auth_controller.handle_login.assert_called_once_with(event)
        assert result is _OK

    @patch("api.common.compositionRoot.get_container")
    def test_non_post_returns_405_with_allow_post_header(
        self, mock_get_container: MagicMock
    ) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event("GET", "/auth/forgot-password")
        result = handler(event, None)

        assert result["statusCode"] == 405
        assert result["headers"]["Allow"] == "POST"
        assert json.loads(result["body"]) == {"error": "Method not allowed"}
        container.auth_controller.handle_forgot_password.assert_not_called()

    @patch("api.common.compositionRoot.get_container")
    def test_unknown_route_returns_404(
        self, mock_get_container: MagicMock
    ) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event("POST", "/auth/unknown")
        result = handler(event, None)

        assert result["statusCode"] == 404
        assert json.loads(result["body"]) == {"error": "Route not found"}
