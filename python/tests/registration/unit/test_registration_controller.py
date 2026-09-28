"""Unit tests for RegistrationController.

Tests the HTTP request handling, input validation, use case delegation,
and error-to-status-code mapping for the registration endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.auth.registerOutputDto import RegisterOutputDTO
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.registration.registrationController import RegistrationController


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_register_use_case() -> AsyncMock:
    """Create a mock RegisterUseCase with an async execute method."""
    use_case = AsyncMock()
    use_case.execute = AsyncMock()
    return use_case


@pytest.fixture
def controller(mock_register_use_case: AsyncMock) -> RegistrationController:
    """Create a RegistrationController with the mocked use case."""
    return RegistrationController(register_use_case=mock_register_use_case)


@pytest.fixture
def valid_register_body() -> dict:
    """A valid registration request body."""
    return {
        "email": "user@example.com",
        "password": "SecurePass1!",
        "full_name": "John Doe",
        "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    }


@pytest.fixture
def valid_event(valid_register_body: dict) -> dict:
    """A valid API Gateway Lambda event for registration."""
    return {
        "body": json.dumps(valid_register_body),
        "headers": {"Content-Type": "application/json"},
    }


@pytest.fixture
def success_output() -> RegisterOutputDTO:
    """A successful registration output DTO."""
    return RegisterOutputDTO(
        user_id="cognito-sub-12345",
        email="user@example.com",
        full_name="John Doe",
        status="pending_confirmation",
        message="Registration successful. Please verify your email to activate your account.",
    )


# ──── Success Case ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_register_success(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    valid_event: dict,
    success_output: RegisterOutputDTO,
) -> None:
    """Registration with valid input returns 201 with user data."""
    mock_register_use_case.execute.return_value = success_output

    response = await controller.handle_register(valid_event)

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert body["user_id"] == "cognito-sub-12345"
    assert body["email"] == "user@example.com"
    assert body["full_name"] == "John Doe"
    assert body["status"] == "pending_confirmation"
    assert "message" in body


@pytest.mark.asyncio
async def test_handle_register_success_with_account_type(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    success_output: RegisterOutputDTO,
) -> None:
    """Registration with explicit account_type is passed to the use case."""
    mock_register_use_case.execute.return_value = success_output
    event = {
        "body": json.dumps({
            "email": "user@example.com",
            "password": "SecurePass1!",
            "full_name": "John Doe",
            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            "account_type": "socio",
        }),
    }

    response = await controller.handle_register(event)

    assert response["statusCode"] == 201
    # Verify the DTO was constructed with account_type
    call_args = mock_register_use_case.execute.call_args[0][0]
    assert call_args.account_type == "socio"


# ──── Input Validation Errors ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_register_missing_body(controller: RegistrationController) -> None:
    """Missing body returns 400."""
    event: dict = {"body": None}

    response = await controller.handle_register(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "error" in body
    assert "required" in body["error"].lower()


@pytest.mark.asyncio
async def test_handle_register_invalid_json(controller: RegistrationController) -> None:
    """Malformed JSON body returns 400."""
    event = {"body": "not valid json{{{"}

    response = await controller.handle_register(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "Invalid JSON" in body["error"]


@pytest.mark.asyncio
async def test_handle_register_missing_required_field(controller: RegistrationController) -> None:
    """Missing required field (email) returns 400 with field info."""
    event = {
        "body": json.dumps({
            "password": "SecurePass1!",
            "full_name": "John Doe",
            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
        }),
    }

    response = await controller.handle_register(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "error" in body
    assert "email" in body["error"].lower()


# ──── Domain Error Mapping ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_register_validation_error_returns_400(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    valid_event: dict,
) -> None:
    """ValidationError from use case maps to 400."""
    mock_register_use_case.execute.side_effect = ValidationError(
        "Invalid email format", field="email"
    )

    response = await controller.handle_register(valid_event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"] == "Invalid email format"


@pytest.mark.asyncio
async def test_handle_register_conflict_error_returns_409(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    valid_event: dict,
) -> None:
    """ConflictError (email already registered) maps to 409."""
    mock_register_use_case.execute.side_effect = ConflictError(
        "Email already registered", resource="user"
    )

    response = await controller.handle_register(valid_event)

    assert response["statusCode"] == 409
    body = json.loads(response["body"])
    assert body["error"] == "Email already registered"


@pytest.mark.asyncio
async def test_handle_register_not_found_error_returns_404(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    valid_event: dict,
) -> None:
    """NotFoundError (tenant not found) maps to 404."""
    mock_register_use_case.execute.side_effect = NotFoundError(
        "Tenant not found", resource="tenant"
    )

    response = await controller.handle_register(valid_event)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"] == "Tenant not found"


@pytest.mark.asyncio
async def test_handle_register_domain_error_tenant_not_active_returns_403(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    valid_event: dict,
) -> None:
    """DomainError (tenant not active) maps to 403."""
    mock_register_use_case.execute.side_effect = DomainError("Tenant is not active")

    response = await controller.handle_register(valid_event)

    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error"] == "Tenant is not active"


@pytest.mark.asyncio
async def test_handle_register_domain_error_self_registration_disabled_returns_403(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    valid_event: dict,
) -> None:
    """DomainError (self-registration not allowed) maps to 403."""
    mock_register_use_case.execute.side_effect = DomainError(
        "Self-registration is not allowed for this institution"
    )

    response = await controller.handle_register(valid_event)

    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error"] == "Self-registration is not allowed for this institution"


# ──── Response Format ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_response_has_correct_headers(
    controller: RegistrationController,
    mock_register_use_case: AsyncMock,
    valid_event: dict,
    success_output: RegisterOutputDTO,
) -> None:
    """All responses include Content-Type: application/json header."""
    mock_register_use_case.execute.return_value = success_output

    response = await controller.handle_register(valid_event)

    assert response["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_error_response_has_correct_headers(
    controller: RegistrationController,
) -> None:
    """Error responses also include Content-Type: application/json header."""
    event: dict = {"body": None}

    response = await controller.handle_register(event)

    assert response["headers"]["Content-Type"] == "application/json"
