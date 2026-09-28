"""Unit tests for validation middleware."""

from __future__ import annotations

import json
from typing import Any

import pytest

from api.accountType.createAccountTypeRequest import CreateAccountTypeRequest
from api.member.createMemberRequest import CreateMemberRequest
from api.auth.loginRequest import LoginRequest
from api.registration.registerRequest import RegisterRequest
from api.common.http.validationMiddleware import validate_request

# ──── Constants ───────────────────────────────────────────────────────────────

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"
VALID_EMAIL = "user@example.com"
VALID_PASSWORD = "SecurePass1!"


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_event(body: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """Build a minimal API Gateway event with the given body."""
    event: dict[str, Any] = {}
    if body is not None:
        if isinstance(body, dict):
            event["body"] = json.dumps(body)
        else:
            event["body"] = body
    return event


# ──── Body Parsing Tests ─────────────────────────────────────────────────────


class TestBodyParsing:
    """Tests for request body parsing edge cases."""

    def test_missing_body_returns_error(self) -> None:
        model, error = validate_request({}, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400
        body = json.loads(error["body"])
        assert "Invalid or missing request body" in body["message"]

    def test_null_body_returns_error(self) -> None:
        model, error = validate_request({"body": None}, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_empty_string_body_returns_error(self) -> None:
        model, error = validate_request({"body": ""}, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_whitespace_only_body_returns_error(self) -> None:
        model, error = validate_request({"body": "   "}, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_invalid_json_body_returns_error(self) -> None:
        model, error = validate_request({"body": "{invalid json"}, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_non_dict_json_body_returns_error(self) -> None:
        model, error = validate_request({"body": "[1,2,3]"}, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_pre_parsed_dict_body_works(self) -> None:
        """Test that a pre-parsed dict body (from tests or internal routing) works."""
        event = {"body": {
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "tenant_id": VALID_UUID,
        }}
        model, error = validate_request(event, LoginRequest)
        assert model is not None
        assert error is None
        assert model.email == VALID_EMAIL


# ──── LoginRequest Validation ────────────────────────────────────────────────


class TestLoginRequestValidation:
    """Tests for LoginRequest schema validation."""

    def test_valid_login_request(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, LoginRequest)
        assert model is not None
        assert error is None
        assert model.email == VALID_EMAIL
        assert model.password == VALID_PASSWORD
        assert model.tenant_id == VALID_UUID

    def test_invalid_email_format(self) -> None:
        event = _make_event({
            "email": "not-an-email",
            "password": VALID_PASSWORD,
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_email_exceeds_254_chars(self) -> None:
        long_email = "a" * 245 + "@test.com"  # > 254 chars
        event = _make_event({
            "email": long_email,
            "password": VALID_PASSWORD,
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_password_too_short(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": "short",
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_password_too_long(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": "A" * 73,
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_invalid_tenant_id_format(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "tenant_id": "not-a-uuid",
        })
        model, error = validate_request(event, LoginRequest)
        assert model is None
        assert error is not None
        body = json.loads(error["body"])
        assert "Invalid tenant ID" in body["message"]

    def test_empty_tenant_id(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "tenant_id": "",
        })
        model, error = validate_request(event, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_missing_required_field(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            # missing tenant_id
        })
        model, error = validate_request(event, LoginRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400


# ──── RegisterRequest Validation ─────────────────────────────────────────────


class TestRegisterRequestValidation:
    """Tests for RegisterRequest schema validation."""

    def test_valid_register_request(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "full_name": "John Doe",
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, RegisterRequest)
        assert model is not None
        assert error is None
        assert model.full_name == "John Doe"
        assert model.account_type is None

    def test_valid_register_with_account_type(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "full_name": "John Doe",
            "tenant_id": VALID_UUID,
            "account_type": "socio",
        })
        model, error = validate_request(event, RegisterRequest)
        assert model is not None
        assert model.account_type == "socio"

    def test_full_name_blank_whitespace(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "full_name": "   ",
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, RegisterRequest)
        assert model is None
        assert error is not None
        body = json.loads(error["body"])
        assert "empty" in body["message"].lower() or "full_name" in body["message"].lower()

    def test_full_name_too_long(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "full_name": "A" * 201,
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, RegisterRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_full_name_exactly_200_chars(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "full_name": "A" * 200,
            "tenant_id": VALID_UUID,
        })
        model, error = validate_request(event, RegisterRequest)
        assert model is not None
        assert error is None


# ──── CreateMemberRequest Validation ─────────────────────────────────────────


class TestCreateMemberRequestValidation:
    """Tests for CreateMemberRequest schema validation."""

    def test_valid_create_member_request(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "full_name": "Jane Smith",
            "account_type": "socio",
            "roles": ["admin"],
        })
        model, error = validate_request(event, CreateMemberRequest)
        assert model is not None
        assert error is None
        assert model.roles == ["admin"]

    def test_multiple_valid_roles(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "full_name": "Jane Smith",
            "account_type": "socio",
            "roles": ["admin", "manager", "viewer"],
        })
        model, error = validate_request(event, CreateMemberRequest)
        assert model is not None
        assert error is None

    def test_invalid_role_rejected(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "full_name": "Jane Smith",
            "account_type": "socio",
            "roles": ["admin", "superuser"],
        })
        model, error = validate_request(event, CreateMemberRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_empty_roles_rejected(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "full_name": "Jane Smith",
            "account_type": "socio",
            "roles": [],
        })
        model, error = validate_request(event, CreateMemberRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_blank_account_type_rejected(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "full_name": "Jane Smith",
            "account_type": "   ",
            "roles": ["viewer"],
        })
        model, error = validate_request(event, CreateMemberRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_blank_full_name_rejected(self) -> None:
        event = _make_event({
            "email": VALID_EMAIL,
            "full_name": "   ",
            "account_type": "socio",
            "roles": ["viewer"],
        })
        model, error = validate_request(event, CreateMemberRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400


# ──── CreateAccountTypeRequest Validation ────────────────────────────────────


class TestCreateAccountTypeRequestValidation:
    """Tests for CreateAccountTypeRequest schema validation."""

    def test_valid_create_account_type(self) -> None:
        event = _make_event({
            "name": "Socio",
            "description": "A member type",
        })
        model, error = validate_request(event, CreateAccountTypeRequest)
        assert model is not None
        assert error is None
        assert model.name == "Socio"
        assert model.description == "A member type"
        assert model.config is None

    def test_valid_with_config(self) -> None:
        event = _make_event({
            "name": "Premium",
            "config": {"max_bookings": 10},
        })
        model, error = validate_request(event, CreateAccountTypeRequest)
        assert model is not None
        assert model.config == {"max_bookings": 10}

    def test_blank_name_rejected(self) -> None:
        event = _make_event({"name": "   "})
        model, error = validate_request(event, CreateAccountTypeRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_name_too_long_rejected(self) -> None:
        event = _make_event({"name": "A" * 101})
        model, error = validate_request(event, CreateAccountTypeRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400

    def test_name_exactly_100_chars(self) -> None:
        event = _make_event({"name": "A" * 100})
        model, error = validate_request(event, CreateAccountTypeRequest)
        assert model is not None
        assert error is None

    def test_missing_name_rejected(self) -> None:
        event = _make_event({"description": "Some description"})
        model, error = validate_request(event, CreateAccountTypeRequest)
        assert model is None
        assert error is not None
        assert error["statusCode"] == 400


# ──── Error Response Format Tests ────────────────────────────────────────────


class TestErrorResponseFormat:
    """Tests for the error response structure."""

    def test_error_response_has_correct_structure(self) -> None:
        event = _make_event({"email": "bad"})  # Missing many fields
        _, error = validate_request(event, LoginRequest)
        assert error is not None
        assert error["statusCode"] == 400
        assert error["headers"]["Content-Type"] == "application/json"
        body = json.loads(error["body"])
        assert "error" in body
        assert "message" in body
        assert body["error"] == "Validation Error"

    def test_error_response_includes_details(self) -> None:
        event = _make_event({"email": "bad"})  # Multiple validation errors
        _, error = validate_request(event, LoginRequest)
        assert error is not None
        body = json.loads(error["body"])
        assert "details" in body
        assert isinstance(body["details"], list)
        assert len(body["details"]) > 0
        # Each detail has field, message, type
        detail = body["details"][0]
        assert "field" in detail
        assert "message" in detail
        assert "type" in detail
