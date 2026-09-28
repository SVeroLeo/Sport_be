"""Unit tests for AccountTypeController.

Tests HTTP request handling, authentication/authorization middleware integration,
input parsing, use case delegation, and domain error-to-HTTP status mapping.

Requirements validated: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.accountType.accountTypeOutputDto import AccountTypeOutputDTO
from api.accountType.paginatedAccountTypesDto import (
    PaginatedAccountTypesDTO,
)
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.accountType.accountTypeController import AccountTypeController
from api.common.http.authGuardMiddleware import AuthContext


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def auth_context() -> AuthContext:
    """A valid auth context representing an admin user."""
    return AuthContext(
        user_id="user-123",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        roles=["admin"],
        email="admin@example.com",
    )


@pytest.fixture
def mock_auth_guard(auth_context: AuthContext) -> MagicMock:
    """AuthGuardMiddleware that always returns a valid AuthContext."""
    guard = MagicMock()
    guard.validate.return_value = auth_context
    return guard


@pytest.fixture
def mock_create_use_case() -> AsyncMock:
    """Mock CreateAccountTypeUseCase."""
    return AsyncMock()


@pytest.fixture
def mock_list_use_case() -> AsyncMock:
    """Mock ListAccountTypesUseCase."""
    return AsyncMock()


@pytest.fixture
def mock_update_use_case() -> AsyncMock:
    """Mock UpdateAccountTypeUseCase."""
    return AsyncMock()


@pytest.fixture
def mock_delete_use_case() -> AsyncMock:
    """Mock DeleteAccountTypeUseCase."""
    return AsyncMock()


@pytest.fixture
def controller(
    mock_auth_guard: MagicMock,
    mock_create_use_case: AsyncMock,
    mock_list_use_case: AsyncMock,
    mock_update_use_case: AsyncMock,
    mock_delete_use_case: AsyncMock,
) -> AccountTypeController:
    """Create an AccountTypeController with all mocked dependencies."""
    return AccountTypeController(
        auth_guard=mock_auth_guard,
        create_use_case=mock_create_use_case,
        list_use_case=mock_list_use_case,
        update_use_case=mock_update_use_case,
        delete_use_case=mock_delete_use_case,
    )


@pytest.fixture
def sample_output_dto() -> AccountTypeOutputDTO:
    """Sample AccountTypeOutputDTO for success responses."""
    return AccountTypeOutputDTO(
        account_type_id="at-001",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        name="Socio",
        description="Miembro asociado",
        config={"fee": 100},
        status="active",
        created_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        updated_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
    )


# ──── Create Handler Tests ────────────────────────────────────────────────────


class TestHandleCreate:
    """Tests for handle_create (POST /account-types)."""

    @pytest.mark.asyncio
    async def test_success_returns_201(
        self,
        controller: AccountTypeController,
        mock_create_use_case: AsyncMock,
        sample_output_dto: AccountTypeOutputDTO,
    ) -> None:
        """Valid create request returns 201 with account type data."""
        mock_create_use_case.execute.return_value = sample_output_dto
        event = {
            "body": json.dumps({"name": "Socio", "description": "Miembro asociado", "config": {"fee": 100}}),
            "headers": {"Authorization": "Bearer valid-token"},
        }

        response = await controller.handle_create(event)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert body["name"] == "Socio"
        assert body["account_type_id"] == "at-001"
        assert body["status"] == "active"
        assert body["description"] == "Miembro asociado"
        assert body["config"] == {"fee": 100}

    @pytest.mark.asyncio
    async def test_success_serializes_datetime_as_iso(
        self,
        controller: AccountTypeController,
        mock_create_use_case: AsyncMock,
        sample_output_dto: AccountTypeOutputDTO,
    ) -> None:
        """Datetime fields are serialized as ISO format strings."""
        mock_create_use_case.execute.return_value = sample_output_dto
        event = {
            "body": json.dumps({"name": "Socio"}),
            "headers": {"Authorization": "Bearer valid-token"},
        }

        response = await controller.handle_create(event)

        body = json.loads(response["body"])
        assert "2024-01-15" in body["created_at"]
        assert "2024-01-15" in body["updated_at"]

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(
        self,
        controller: AccountTypeController,
    ) -> None:
        """Missing request body returns 400."""
        event: dict = {"body": None, "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "body" in body["message"].lower() or "required" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(
        self,
        controller: AccountTypeController,
    ) -> None:
        """Invalid JSON body returns 400."""
        event = {"body": "not-json{{", "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 400

    @pytest.mark.asyncio
    async def test_missing_name_returns_400(
        self,
        controller: AccountTypeController,
    ) -> None:
        """Missing 'name' field returns 400."""
        event = {"body": json.dumps({"description": "no name"}), "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "name" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_validation_error_returns_400(
        self,
        controller: AccountTypeController,
        mock_create_use_case: AsyncMock,
    ) -> None:
        """ValidationError from use case maps to 400."""
        mock_create_use_case.execute.side_effect = ValidationError(
            "Name cannot exceed 100 characters", field="name"
        )
        event = {"body": json.dumps({"name": "x" * 101}), "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "100 characters" in body["message"]

    @pytest.mark.asyncio
    async def test_conflict_error_returns_409(
        self,
        controller: AccountTypeController,
        mock_create_use_case: AsyncMock,
    ) -> None:
        """ConflictError (duplicate name) maps to 409 (Req 5.2)."""
        mock_create_use_case.execute.side_effect = ConflictError(
            "Account type name already exists in this tenant", resource="account_type"
        )
        event = {"body": json.dumps({"name": "Socio"}), "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 409
        body = json.loads(response["body"])
        assert "already exists" in body["message"]

    @pytest.mark.asyncio
    async def test_not_found_error_returns_404(
        self,
        controller: AccountTypeController,
        mock_create_use_case: AsyncMock,
    ) -> None:
        """NotFoundError (tenant not found) maps to 404."""
        mock_create_use_case.execute.side_effect = NotFoundError(
            "Tenant not found", resource="tenant"
        )
        event = {"body": json.dumps({"name": "Socio"}), "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(
        self,
        controller: AccountTypeController,
        mock_auth_guard: MagicMock,
    ) -> None:
        """AuthGuard returning error dict results in that error being returned."""
        mock_auth_guard.validate.return_value = {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing or invalid authorization header"}),
        }
        event = {"body": json.dumps({"name": "Socio"}), "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 401

    @pytest.mark.asyncio
    async def test_unauthorized_viewer_returns_403(
        self,
        controller: AccountTypeController,
        mock_auth_guard: MagicMock,
    ) -> None:
        """Viewer role lacking create permission gets 403."""
        mock_auth_guard.validate.return_value = AuthContext(
            user_id="user-123",
            tenant_id="tenant-456",
            roles=["viewer"],
            email="viewer@example.com",
        )
        event = {"body": json.dumps({"name": "Socio"}), "headers": {}}

        response = await controller.handle_create(event)

        assert response["statusCode"] == 403

    @pytest.mark.asyncio
    async def test_passes_tenant_id_from_context(
        self,
        controller: AccountTypeController,
        mock_create_use_case: AsyncMock,
        sample_output_dto: AccountTypeOutputDTO,
    ) -> None:
        """The tenant_id from AuthContext is passed to the use case DTO."""
        mock_create_use_case.execute.return_value = sample_output_dto
        event = {"body": json.dumps({"name": "Socio"}), "headers": {}}

        await controller.handle_create(event)

        call_dto = mock_create_use_case.execute.call_args[0][0]
        assert call_dto.tenant_id == "550e8400-e29b-41d4-a716-446655440000"


# ──── List Handler Tests ──────────────────────────────────────────────────────


class TestHandleList:
    """Tests for handle_list (GET /account-types)."""

    @pytest.mark.asyncio
    async def test_success_returns_200(
        self,
        controller: AccountTypeController,
        mock_list_use_case: AsyncMock,
        sample_output_dto: AccountTypeOutputDTO,
    ) -> None:
        """Valid list request returns 200 with paginated results."""
        mock_list_use_case.execute.return_value = PaginatedAccountTypesDTO(
            items=[sample_output_dto],
            next_key=None,
        )
        event = {"headers": {"Authorization": "Bearer token"}, "queryStringParameters": None}

        response = await controller.handle_list(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Socio"
        assert body["next_key"] is None

    @pytest.mark.asyncio
    async def test_pagination_params_passed_correctly(
        self,
        controller: AccountTypeController,
        mock_list_use_case: AsyncMock,
    ) -> None:
        """Query string pagination parameters are passed to the use case."""
        mock_list_use_case.execute.return_value = PaginatedAccountTypesDTO(items=[], next_key=None)
        event = {
            "headers": {"Authorization": "Bearer token"},
            "queryStringParameters": {"limit": "50", "cursor": "abc123"},
        }

        await controller.handle_list(event)

        call_args = mock_list_use_case.execute.call_args[0]
        assert call_args[0] == "550e8400-e29b-41d4-a716-446655440000"  # tenant_id
        pagination = call_args[1]
        assert pagination.limit == 50
        assert pagination.cursor == "abc123"

    @pytest.mark.asyncio
    async def test_default_pagination_when_no_params(
        self,
        controller: AccountTypeController,
        mock_list_use_case: AsyncMock,
    ) -> None:
        """Defaults to limit=20, cursor=None when no params provided."""
        mock_list_use_case.execute.return_value = PaginatedAccountTypesDTO(items=[], next_key=None)
        event = {"headers": {}, "queryStringParameters": None}

        await controller.handle_list(event)

        pagination = mock_list_use_case.execute.call_args[0][1]
        assert pagination.limit == 20
        assert pagination.cursor is None

    @pytest.mark.asyncio
    async def test_limit_clamped_to_max_100(
        self,
        controller: AccountTypeController,
        mock_list_use_case: AsyncMock,
    ) -> None:
        """Limit values above 100 are clamped to 100."""
        mock_list_use_case.execute.return_value = PaginatedAccountTypesDTO(items=[], next_key=None)
        event = {
            "headers": {},
            "queryStringParameters": {"limit": "500"},
        }

        await controller.handle_list(event)

        pagination = mock_list_use_case.execute.call_args[0][1]
        assert pagination.limit == 100

    @pytest.mark.asyncio
    async def test_invalid_limit_uses_default(
        self,
        controller: AccountTypeController,
        mock_list_use_case: AsyncMock,
    ) -> None:
        """Non-numeric limit falls back to default."""
        mock_list_use_case.execute.return_value = PaginatedAccountTypesDTO(items=[], next_key=None)
        event = {
            "headers": {},
            "queryStringParameters": {"limit": "not-a-number"},
        }

        await controller.handle_list(event)

        pagination = mock_list_use_case.execute.call_args[0][1]
        assert pagination.limit == 20

    @pytest.mark.asyncio
    async def test_viewer_can_list(
        self,
        controller: AccountTypeController,
        mock_auth_guard: MagicMock,
        mock_list_use_case: AsyncMock,
    ) -> None:
        """Viewer role has read permission and can list account types (Req 5.4)."""
        mock_auth_guard.validate.return_value = AuthContext(
            user_id="user-123",
            tenant_id="tenant-456",
            roles=["viewer"],
            email="viewer@example.com",
        )
        mock_list_use_case.execute.return_value = PaginatedAccountTypesDTO(items=[], next_key=None)
        event = {"headers": {}, "queryStringParameters": None}

        response = await controller.handle_list(event)

        assert response["statusCode"] == 200

    @pytest.mark.asyncio
    async def test_next_key_included_in_response(
        self,
        controller: AccountTypeController,
        mock_list_use_case: AsyncMock,
    ) -> None:
        """When more pages exist, next_key is included in response."""
        mock_list_use_case.execute.return_value = PaginatedAccountTypesDTO(
            items=[], next_key="next-cursor-abc"
        )
        event = {"headers": {}, "queryStringParameters": None}

        response = await controller.handle_list(event)

        body = json.loads(response["body"])
        assert body["next_key"] == "next-cursor-abc"


# ──── Update Handler Tests ────────────────────────────────────────────────────


class TestHandleUpdate:
    """Tests for handle_update (PUT /account-types/{id})."""

    @pytest.mark.asyncio
    async def test_success_returns_200(
        self,
        controller: AccountTypeController,
        mock_update_use_case: AsyncMock,
        sample_output_dto: AccountTypeOutputDTO,
    ) -> None:
        """Valid update returns 200 with updated account type."""
        mock_update_use_case.execute.return_value = sample_output_dto
        event = {
            "body": json.dumps({"name": "Socio Updated"}),
            "headers": {},
            "pathParameters": {"id": "at-001"},
        }

        response = await controller.handle_update(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["account_type_id"] == "at-001"

    @pytest.mark.asyncio
    async def test_missing_path_parameter_returns_400(
        self,
        controller: AccountTypeController,
    ) -> None:
        """Missing 'id' path parameter returns 400."""
        event = {
            "body": json.dumps({"name": "Updated"}),
            "headers": {},
            "pathParameters": {},
        }

        response = await controller.handle_update(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "id" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(
        self,
        controller: AccountTypeController,
    ) -> None:
        """Missing request body returns 400."""
        event = {
            "body": None,
            "headers": {},
            "pathParameters": {"id": "at-001"},
        }

        response = await controller.handle_update(event)

        assert response["statusCode"] == 400

    @pytest.mark.asyncio
    async def test_not_found_returns_404(
        self,
        controller: AccountTypeController,
        mock_update_use_case: AsyncMock,
    ) -> None:
        """NotFoundError maps to 404 (Req 5.5)."""
        mock_update_use_case.execute.side_effect = NotFoundError(
            "Account type not found", resource="account_type"
        )
        event = {
            "body": json.dumps({"name": "New Name"}),
            "headers": {},
            "pathParameters": {"id": "nonexistent"},
        }

        response = await controller.handle_update(event)

        assert response["statusCode"] == 404

    @pytest.mark.asyncio
    async def test_conflict_error_returns_409(
        self,
        controller: AccountTypeController,
        mock_update_use_case: AsyncMock,
    ) -> None:
        """ConflictError (name duplicate) maps to 409 (Req 5.5)."""
        mock_update_use_case.execute.side_effect = ConflictError(
            "Account type name already exists in this tenant", resource="account_type"
        )
        event = {
            "body": json.dumps({"name": "Duplicate"}),
            "headers": {},
            "pathParameters": {"id": "at-001"},
        }

        response = await controller.handle_update(event)

        assert response["statusCode"] == 409

    @pytest.mark.asyncio
    async def test_passes_account_type_id_and_tenant_id(
        self,
        controller: AccountTypeController,
        mock_update_use_case: AsyncMock,
        sample_output_dto: AccountTypeOutputDTO,
    ) -> None:
        """Update passes both account_type_id from path and tenant_id from context."""
        mock_update_use_case.execute.return_value = sample_output_dto
        event = {
            "body": json.dumps({"name": "Updated"}),
            "headers": {},
            "pathParameters": {"id": "at-999"},
        }

        await controller.handle_update(event)

        call_dto = mock_update_use_case.execute.call_args[0][0]
        assert call_dto.account_type_id == "at-999"
        assert call_dto.tenant_id == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_viewer_cannot_update(
        self,
        controller: AccountTypeController,
        mock_auth_guard: MagicMock,
    ) -> None:
        """Viewer role cannot update (Req 10.1)."""
        mock_auth_guard.validate.return_value = AuthContext(
            user_id="user-123",
            tenant_id="tenant-456",
            roles=["viewer"],
            email="viewer@example.com",
        )
        event = {
            "body": json.dumps({"name": "Updated"}),
            "headers": {},
            "pathParameters": {"id": "at-001"},
        }

        response = await controller.handle_update(event)

        assert response["statusCode"] == 403


# ──── Delete Handler Tests ────────────────────────────────────────────────────


class TestHandleDelete:
    """Tests for handle_delete (DELETE /account-types/{id})."""

    @pytest.mark.asyncio
    async def test_success_returns_204(
        self,
        controller: AccountTypeController,
        mock_delete_use_case: AsyncMock,
    ) -> None:
        """Successful deletion returns 204 No Content (Req 5.6)."""
        mock_delete_use_case.execute.return_value = None
        event = {
            "headers": {},
            "pathParameters": {"id": "at-001"},
        }

        response = await controller.handle_delete(event)

        assert response["statusCode"] == 204
        assert response["body"] == ""

    @pytest.mark.asyncio
    async def test_missing_path_parameter_returns_400(
        self,
        controller: AccountTypeController,
    ) -> None:
        """Missing 'id' path parameter returns 400."""
        event = {"headers": {}, "pathParameters": {}}

        response = await controller.handle_delete(event)

        assert response["statusCode"] == 400

    @pytest.mark.asyncio
    async def test_not_found_returns_404(
        self,
        controller: AccountTypeController,
        mock_delete_use_case: AsyncMock,
    ) -> None:
        """NotFoundError maps to 404."""
        mock_delete_use_case.execute.side_effect = NotFoundError(
            "Account type not found", resource="account_type"
        )
        event = {"headers": {}, "pathParameters": {"id": "nonexistent"}}

        response = await controller.handle_delete(event)

        assert response["statusCode"] == 404

    @pytest.mark.asyncio
    async def test_active_members_returns_400(
        self,
        controller: AccountTypeController,
        mock_delete_use_case: AsyncMock,
    ) -> None:
        """DomainError (active members using type) maps to 400 (Req 5.7)."""
        mock_delete_use_case.execute.side_effect = DomainError(
            "Cannot delete account type: active members are using it"
        )
        event = {"headers": {}, "pathParameters": {"id": "at-001"}}

        response = await controller.handle_delete(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "active members" in body["message"]

    @pytest.mark.asyncio
    async def test_viewer_cannot_delete(
        self,
        controller: AccountTypeController,
        mock_auth_guard: MagicMock,
    ) -> None:
        """Viewer role cannot delete (Req 10.1)."""
        mock_auth_guard.validate.return_value = AuthContext(
            user_id="user-123",
            tenant_id="tenant-456",
            roles=["viewer"],
            email="viewer@example.com",
        )
        event = {"headers": {}, "pathParameters": {"id": "at-001"}}

        response = await controller.handle_delete(event)

        assert response["statusCode"] == 403

    @pytest.mark.asyncio
    async def test_passes_tenant_id_and_account_type_id(
        self,
        controller: AccountTypeController,
        mock_delete_use_case: AsyncMock,
    ) -> None:
        """Delete passes tenant_id from context and id from path."""
        mock_delete_use_case.execute.return_value = None
        event = {"headers": {}, "pathParameters": {"id": "at-555"}}

        await controller.handle_delete(event)

        call_args = mock_delete_use_case.execute.call_args[0]
        assert call_args[0] == "550e8400-e29b-41d4-a716-446655440000"  # tenant_id
        assert call_args[1] == "at-555"  # account_type_id


# ──── Response Format Tests ───────────────────────────────────────────────────


class TestResponseFormat:
    """All responses follow API Gateway Lambda proxy format."""

    @pytest.mark.asyncio
    async def test_success_response_has_content_type(
        self,
        controller: AccountTypeController,
        mock_create_use_case: AsyncMock,
        sample_output_dto: AccountTypeOutputDTO,
    ) -> None:
        """Success responses include Content-Type: application/json."""
        mock_create_use_case.execute.return_value = sample_output_dto
        event = {"body": json.dumps({"name": "Socio"}), "headers": {}}

        response = await controller.handle_create(event)

        assert response["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_error_response_has_content_type(
        self,
        controller: AccountTypeController,
    ) -> None:
        """Error responses include Content-Type: application/json."""
        event = {"body": None, "headers": {}}

        response = await controller.handle_create(event)

        assert response["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_delete_204_has_content_type(
        self,
        controller: AccountTypeController,
        mock_delete_use_case: AsyncMock,
    ) -> None:
        """204 responses also include Content-Type header."""
        mock_delete_use_case.execute.return_value = None
        event = {"headers": {}, "pathParameters": {"id": "at-001"}}

        response = await controller.handle_delete(event)

        assert response["headers"]["Content-Type"] == "application/json"
