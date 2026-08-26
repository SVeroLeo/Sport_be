"""Unit tests for the shared error handler."""

from __future__ import annotations

import json
import logging

from domain.errors.conflict_error import ConflictError
from domain.errors.domain_error import DomainError
from domain.errors.forbidden_error import ForbiddenError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.errors.not_found_error import NotFoundError
from domain.errors.tenant_not_found_error import TenantNotFoundError
from domain.errors.validation_error import ValidationError
from interfaces.shared.error_handler import handle_error


class TestHandleErrorValidation:
    """Tests for ValidationError mapping."""

    def test_returns_400(self) -> None:
        error = ValidationError("Invalid email format", field="email")
        result = handle_error(error)
        assert result["statusCode"] == 400

    def test_body_contains_message(self) -> None:
        error = ValidationError("Too short", field="password")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "Too short"


class TestHandleErrorInvalidCredentials:
    """Tests for InvalidCredentialsError mapping."""

    def test_returns_401(self) -> None:
        error = InvalidCredentialsError()
        result = handle_error(error)
        assert result["statusCode"] == 401

    def test_body_contains_message(self) -> None:
        error = InvalidCredentialsError("Bad creds")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "Bad creds"


class TestHandleErrorForbidden:
    """Tests for ForbiddenError mapping."""

    def test_returns_403(self) -> None:
        error = ForbiddenError()
        result = handle_error(error)
        assert result["statusCode"] == 403

    def test_body_contains_message(self) -> None:
        error = ForbiddenError("No access")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "No access"


class TestHandleErrorNotFound:
    """Tests for NotFoundError mapping."""

    def test_returns_404(self) -> None:
        error = NotFoundError("User not found", resource="user")
        result = handle_error(error)
        assert result["statusCode"] == 404

    def test_body_contains_message(self) -> None:
        error = NotFoundError("Missing resource")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "Missing resource"


class TestHandleErrorTenantNotFound:
    """Tests for TenantNotFoundError mapping."""

    def test_returns_404(self) -> None:
        error = TenantNotFoundError("tenant-123")
        result = handle_error(error)
        assert result["statusCode"] == 404

    def test_body_contains_message(self) -> None:
        error = TenantNotFoundError("abc-def")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "Tenant not found: abc-def"


class TestHandleErrorConflict:
    """Tests for ConflictError mapping."""

    def test_returns_409(self) -> None:
        error = ConflictError("Already exists", resource="account_type")
        result = handle_error(error)
        assert result["statusCode"] == 409

    def test_body_contains_message(self) -> None:
        error = ConflictError("Duplicate name")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "Duplicate name"


class TestHandleErrorGenericDomain:
    """Tests for generic DomainError mapping."""

    def test_returns_400(self) -> None:
        error = DomainError("Something went wrong in domain")
        result = handle_error(error)
        assert result["statusCode"] == 400

    def test_body_contains_message(self) -> None:
        error = DomainError("Domain issue")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "Domain issue"


class TestHandleErrorUnknown:
    """Tests for unknown/unexpected exceptions."""

    def test_returns_500(self) -> None:
        error = RuntimeError("Something unexpected")
        result = handle_error(error)
        assert result["statusCode"] == 500

    def test_body_contains_generic_message(self) -> None:
        error = ValueError("oops")
        result = handle_error(error)
        body = json.loads(result["body"])
        assert body["error"] == "Internal server error"

    def test_logs_unexpected_error(self, caplog) -> None:  # type: ignore[no-untyped-def]
        """Verify that unexpected errors are logged at ERROR level."""
        with caplog.at_level(logging.ERROR, logger="interfaces.shared.error_handler"):
            handle_error(RuntimeError("kaboom"))
        assert any("kaboom" in record.message for record in caplog.records)


class TestHandleErrorIncludesCorsHeaders:
    """Verify all responses include CORS headers."""

    def test_validation_error_has_cors(self) -> None:
        result = handle_error(ValidationError("x"))
        assert result["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_unknown_error_has_cors(self) -> None:
        result = handle_error(RuntimeError("x"))
        assert result["headers"]["Access-Control-Allow-Origin"] == "*"
