"""Unit tests for Lambda handler routing logic.

Verifies that each handler correctly routes requests to the
appropriate controller method based on httpMethod and resource path,
and returns 405 for unsupported methods.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_event(
    method: str = "POST",
    resource: str = "",
    path: str = "",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal API Gateway Lambda proxy event."""
    event: dict[str, Any] = {
        "httpMethod": method,
        "headers": {},
        "queryStringParameters": None,
        "pathParameters": None,
    }
    if resource:
        event["resource"] = resource
    if path:
        event["path"] = path
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _mock_container() -> MagicMock:
    """Create a mock container with all controller mocks returning sample responses."""
    container = MagicMock()

    # Auth controller
    container.auth_controller.handle_login = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    container.auth_controller.handle_refresh = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    container.auth_controller.handle_logout = AsyncMock(return_value={"statusCode": 204, "body": ""})

    # Registration controller
    container.registration_controller.handle_register = AsyncMock(return_value={"statusCode": 201, "body": "{}"})

    # Account type controller
    container.account_type_controller.handle_create = AsyncMock(return_value={"statusCode": 201, "body": "{}"})
    container.account_type_controller.handle_list = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    container.account_type_controller.handle_update = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    container.account_type_controller.handle_delete = AsyncMock(return_value={"statusCode": 204, "body": ""})

    # Member controller
    container.member_controller.handle_create = AsyncMock(return_value={"statusCode": 201, "body": "{}"})
    container.member_controller.handle_list = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    container.member_controller.handle_update = AsyncMock(return_value={"statusCode": 200, "body": "{}"})
    container.member_controller.handle_deactivate = AsyncMock(return_value={"statusCode": 204, "body": ""})

    return container


# ──── Auth Handler Tests ──────────────────────────────────────────────────────


class TestAuthHandler:
    """Tests for auth_handler routing."""

    @patch("api.common.compositionRoot.get_container")
    def test_post_login_routes_to_handle_login(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event(method="POST", resource="/auth/login")
        result = handler(event, None)

        container.auth_controller.handle_login.assert_called_once_with(event)
        assert result["statusCode"] == 200

    @patch("api.common.compositionRoot.get_container")
    def test_post_refresh_routes_to_handle_refresh(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event(method="POST", resource="/auth/refresh")
        result = handler(event, None)

        container.auth_controller.handle_refresh.assert_called_once_with(event)
        assert result["statusCode"] == 200

    @patch("api.common.compositionRoot.get_container")
    def test_post_logout_routes_to_handle_logout(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event(method="POST", resource="/auth/logout")
        result = handler(event, None)

        container.auth_controller.handle_logout.assert_called_once_with(event)
        assert result["statusCode"] == 204

    @patch("api.common.compositionRoot.get_container")
    def test_get_method_returns_405(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event(method="GET", resource="/auth/login")
        result = handler(event, None)

        assert result["statusCode"] == 405
        assert "Method not allowed" in result["body"]

    @patch("api.common.compositionRoot.get_container")
    def test_unknown_route_returns_404(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event(method="POST", resource="/auth/unknown")
        result = handler(event, None)

        assert result["statusCode"] == 404
        assert "Route not found" in result["body"]

    @patch("api.common.compositionRoot.get_container")
    def test_path_fallback_when_no_resource(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.auth.authHandler import handler

        event = _make_event(method="POST", path="/auth/login")
        result = handler(event, None)

        container.auth_controller.handle_login.assert_called_once_with(event)
        assert result["statusCode"] == 200


# ──── Registration Handler Tests ──────────────────────────────────────────────


class TestRegistrationHandler:
    """Tests for registration_handler routing."""

    @patch("api.common.compositionRoot.get_container")
    def test_post_routes_to_handle_register(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.registration.registrationHandler import handler

        event = _make_event(method="POST")
        result = handler(event, None)

        container.registration_controller.handle_register.assert_called_once_with(event)
        assert result["statusCode"] == 201

    @patch("api.common.compositionRoot.get_container")
    def test_get_method_returns_405(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.registration.registrationHandler import handler

        event = _make_event(method="GET")
        result = handler(event, None)

        assert result["statusCode"] == 405
        assert "Method not allowed" in result["body"]

    @patch("api.common.compositionRoot.get_container")
    def test_put_method_returns_405(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.registration.registrationHandler import handler

        event = _make_event(method="PUT")
        result = handler(event, None)

        assert result["statusCode"] == 405


# ──── Account Type Handler Tests ──────────────────────────────────────────────


class TestAccountTypeHandler:
    """Tests for account_type_handler routing."""

    @patch("api.common.compositionRoot.get_container")
    def test_post_routes_to_handle_create(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.accountType.accountTypeHandler import handler

        event = _make_event(method="POST")
        result = handler(event, None)

        container.account_type_controller.handle_create.assert_called_once_with(event)
        assert result["statusCode"] == 201

    @patch("api.common.compositionRoot.get_container")
    def test_get_routes_to_handle_list(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.accountType.accountTypeHandler import handler

        event = _make_event(method="GET")
        result = handler(event, None)

        container.account_type_controller.handle_list.assert_called_once_with(event)
        assert result["statusCode"] == 200

    @patch("api.common.compositionRoot.get_container")
    def test_put_routes_to_handle_update(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.accountType.accountTypeHandler import handler

        event = _make_event(method="PUT")
        result = handler(event, None)

        container.account_type_controller.handle_update.assert_called_once_with(event)
        assert result["statusCode"] == 200

    @patch("api.common.compositionRoot.get_container")
    def test_delete_routes_to_handle_delete(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.accountType.accountTypeHandler import handler

        event = _make_event(method="DELETE")
        result = handler(event, None)

        container.account_type_controller.handle_delete.assert_called_once_with(event)
        assert result["statusCode"] == 204

    @patch("api.common.compositionRoot.get_container")
    def test_patch_returns_405(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.accountType.accountTypeHandler import handler

        event = _make_event(method="PATCH")
        result = handler(event, None)

        assert result["statusCode"] == 405
        assert "Method not allowed" in result["body"]


# ──── Member Handler Tests ────────────────────────────────────────────────────


class TestMemberHandler:
    """Tests for member_handler routing."""

    @patch("api.common.compositionRoot.get_container")
    def test_post_routes_to_handle_create(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.member.memberHandler import handler

        event = _make_event(method="POST")
        result = handler(event, None)

        container.member_controller.handle_create.assert_called_once_with(event)
        assert result["statusCode"] == 201

    @patch("api.common.compositionRoot.get_container")
    def test_get_routes_to_handle_list(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.member.memberHandler import handler

        event = _make_event(method="GET")
        result = handler(event, None)

        container.member_controller.handle_list.assert_called_once_with(event)
        assert result["statusCode"] == 200

    @patch("api.common.compositionRoot.get_container")
    def test_put_routes_to_handle_update(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.member.memberHandler import handler

        event = _make_event(method="PUT")
        result = handler(event, None)

        container.member_controller.handle_update.assert_called_once_with(event)
        assert result["statusCode"] == 200

    @patch("api.common.compositionRoot.get_container")
    def test_delete_routes_to_handle_deactivate(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.member.memberHandler import handler

        event = _make_event(method="DELETE")
        result = handler(event, None)

        container.member_controller.handle_deactivate.assert_called_once_with(event)
        assert result["statusCode"] == 204

    @patch("api.common.compositionRoot.get_container")
    def test_options_returns_405(self, mock_get_container: MagicMock) -> None:
        container = _mock_container()
        mock_get_container.return_value = container

        from api.member.memberHandler import handler

        event = _make_event(method="OPTIONS")
        result = handler(event, None)

        assert result["statusCode"] == 405
        assert "Method not allowed" in result["body"]


# ──── Error Handling Tests ────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests for unexpected error handling in handlers."""

    @patch("api.common.compositionRoot.get_container")
    def test_auth_handler_returns_500_on_unexpected_error(self, mock_get_container: MagicMock) -> None:
        mock_get_container.side_effect = RuntimeError("Unexpected")

        from api.auth.authHandler import handler

        event = _make_event(method="POST", resource="/auth/login")
        result = handler(event, None)

        assert result["statusCode"] == 500
        assert "Internal server error" in result["body"]

    @patch("api.common.compositionRoot.get_container")
    def test_registration_handler_returns_500_on_unexpected_error(self, mock_get_container: MagicMock) -> None:
        mock_get_container.side_effect = RuntimeError("Unexpected")

        from api.registration.registrationHandler import handler

        event = _make_event(method="POST")
        result = handler(event, None)

        assert result["statusCode"] == 500
        assert "Internal server error" in result["body"]

    @patch("api.common.compositionRoot.get_container")
    def test_account_type_handler_returns_500_on_unexpected_error(self, mock_get_container: MagicMock) -> None:
        mock_get_container.side_effect = RuntimeError("Unexpected")

        from api.accountType.accountTypeHandler import handler

        event = _make_event(method="GET")
        result = handler(event, None)

        assert result["statusCode"] == 500
        assert "Internal server error" in result["body"]

    @patch("api.common.compositionRoot.get_container")
    def test_member_handler_returns_500_on_unexpected_error(self, mock_get_container: MagicMock) -> None:
        mock_get_container.side_effect = RuntimeError("Unexpected")

        from api.member.memberHandler import handler

        event = _make_event(method="POST")
        result = handler(event, None)

        assert result["statusCode"] == 500
        assert "Internal server error" in result["body"]
