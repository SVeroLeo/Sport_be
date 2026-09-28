"""Unit tests for MemberController.

Tests the HTTP request handling, auth/permission validation, use case delegation,
and error-to-status-code mapping for member management endpoints.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.member.memberOutputDto import MemberOutputDTO
from api.member.paginatedMembersDto import PaginatedMembersDTO
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.member.memberController import MemberController
from api.common.http.authGuardMiddleware import AuthContext


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def auth_context() -> AuthContext:
    """An authenticated admin auth context."""
    return AuthContext(
        user_id="user-123",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        roles=["admin"],
        email="admin@example.com",
    )


@pytest.fixture
def viewer_context() -> AuthContext:
    """An authenticated viewer tenant context (limited permissions)."""
    return AuthContext(
        user_id="user-456",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        roles=["viewer"],
        email="viewer@example.com",
    )


@pytest.fixture
def mock_auth_guard(auth_context: AuthContext) -> MagicMock:
    """Mock AuthGuardMiddleware that returns a valid admin context."""
    guard = MagicMock()
    guard.validate.return_value = auth_context
    return guard


@pytest.fixture
def mock_invite_use_case() -> AsyncMock:
    """Mock InviteUserUseCase."""
    return AsyncMock()


@pytest.fixture
def mock_list_use_case() -> AsyncMock:
    """Mock ListMembersUseCase."""
    return AsyncMock()


@pytest.fixture
def mock_update_use_case() -> AsyncMock:
    """Mock UpdateMemberUseCase."""
    return AsyncMock()


@pytest.fixture
def mock_deactivate_use_case() -> AsyncMock:
    """Mock DeactivateMemberUseCase."""
    return AsyncMock()


@pytest.fixture
def controller(
    mock_invite_use_case: AsyncMock,
    mock_list_use_case: AsyncMock,
    mock_update_use_case: AsyncMock,
    mock_deactivate_use_case: AsyncMock,
    mock_auth_guard: MagicMock,
) -> MemberController:
    """Create a MemberController with all mocked dependencies."""
    return MemberController(
        invite_user_use_case=mock_invite_use_case,
        list_members_use_case=mock_list_use_case,
        update_member_use_case=mock_update_use_case,
        deactivate_member_use_case=mock_deactivate_use_case,
        auth_guard=mock_auth_guard,
    )


@pytest.fixture
def member_output() -> MemberOutputDTO:
    """A sample MemberOutputDTO for use case return values."""
    return MemberOutputDTO(
        member_id="member-001",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        user_id="user-789",
        account_type="socio",
        account_type_id="acctype-001",
        full_name="Jane Doe",
        email="jane@example.com",
        status="active",
        registration_type="invited",
        invited_by="user-123",
        metadata=None,
        created_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )


# ──── handle_create Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_create_success(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
    member_output: MemberOutputDTO,
) -> None:
    """Create member with valid input returns 201 with member data."""
    mock_invite_use_case.execute.return_value = member_output
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "socio",
            "roles": ["viewer"],
        }),
    }

    response = await controller.handle_create(event)

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert body["member_id"] == "member-001"
    assert body["email"] == "jane@example.com"
    assert body["full_name"] == "Jane Doe"
    assert body["status"] == "active"
    assert body["registration_type"] == "invited"


@pytest.mark.asyncio
async def test_handle_create_missing_body_returns_400(
    controller: MemberController,
) -> None:
    """Create member without body returns 400."""
    event = {"headers": {"Authorization": "Bearer valid-token"}, "body": None}

    response = await controller.handle_create(event)

    assert response["statusCode"] == 400


@pytest.mark.asyncio
async def test_handle_create_invalid_json_returns_400(
    controller: MemberController,
) -> None:
    """Create member with invalid JSON body returns 400."""
    event = {"headers": {"Authorization": "Bearer valid-token"}, "body": "not json{{{"}

    response = await controller.handle_create(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "Invalid request body" in body["message"]


@pytest.mark.asyncio
async def test_handle_create_conflict_error_returns_409(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
) -> None:
    """ConflictError (user already member) maps to 409."""
    mock_invite_use_case.execute.side_effect = ConflictError(
        "User is already a member of this tenant", resource="member"
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "socio",
            "roles": ["viewer"],
        }),
    }

    response = await controller.handle_create(event)

    assert response["statusCode"] == 409
    body = json.loads(response["body"])
    assert "already a member" in body["message"]


@pytest.mark.asyncio
async def test_handle_create_not_found_error_returns_404(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
) -> None:
    """NotFoundError (account type not found) maps to 404."""
    mock_invite_use_case.execute.side_effect = NotFoundError(
        "Account type does not exist in this tenant", resource="account_type"
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "nonexistent",
            "roles": ["viewer"],
        }),
    }

    response = await controller.handle_create(event)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert "Account type does not exist" in body["message"]


@pytest.mark.asyncio
async def test_handle_create_validation_error_returns_400(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
) -> None:
    """ValidationError maps to 400."""
    mock_invite_use_case.execute.side_effect = ValidationError(
        "Invalid email format", field="email"
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "invalid",
            "full_name": "Jane Doe",
            "account_type": "socio",
            "roles": ["viewer"],
        }),
    }

    response = await controller.handle_create(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "Invalid email" in body["message"]


@pytest.mark.asyncio
async def test_handle_create_domain_error_returns_400(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
) -> None:
    """DomainError (account type not active) maps to 400."""
    mock_invite_use_case.execute.side_effect = DomainError("Account type is not active")
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "inactive_type",
            "roles": ["viewer"],
        }),
    }

    response = await controller.handle_create(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "not active" in body["message"]


@pytest.mark.asyncio
async def test_handle_create_uses_tenant_from_context(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
    member_output: MemberOutputDTO,
) -> None:
    """Create member uses tenant_id from AuthContext, not from body."""
    mock_invite_use_case.execute.return_value = member_output
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "socio",
            "roles": ["viewer"],
        }),
    }

    await controller.handle_create(event)

    call_kwargs = mock_invite_use_case.execute.call_args[1]
    assert call_kwargs["input_dto"].tenant_id == "550e8400-e29b-41d4-a716-446655440000"
    assert call_kwargs["created_by_user_id"] == "user-123"


# ──── handle_create Permission Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_create_viewer_gets_403(
    mock_invite_use_case: AsyncMock,
    mock_list_use_case: AsyncMock,
    mock_update_use_case: AsyncMock,
    mock_deactivate_use_case: AsyncMock,
    viewer_context: AuthContext,
) -> None:
    """Viewer role cannot create members — returns 403."""
    guard = MagicMock()
    guard.validate.return_value = viewer_context
    ctrl = MemberController(
        invite_user_use_case=mock_invite_use_case,
        list_members_use_case=mock_list_use_case,
        update_member_use_case=mock_update_use_case,
        deactivate_member_use_case=mock_deactivate_use_case,
        auth_guard=guard,
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "socio",
            "roles": ["viewer"],
        }),
    }

    response = await ctrl.handle_create(event)

    assert response["statusCode"] == 403


@pytest.mark.asyncio
async def test_handle_create_auth_failure_returns_401(
    mock_invite_use_case: AsyncMock,
    mock_list_use_case: AsyncMock,
    mock_update_use_case: AsyncMock,
    mock_deactivate_use_case: AsyncMock,
) -> None:
    """Invalid auth returns 401 from AuthGuard."""
    guard = MagicMock()
    guard.validate.return_value = {
        "statusCode": 401,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": "Missing or invalid authorization header"}),
    }
    ctrl = MemberController(
        invite_user_use_case=mock_invite_use_case,
        list_members_use_case=mock_list_use_case,
        update_member_use_case=mock_update_use_case,
        deactivate_member_use_case=mock_deactivate_use_case,
        auth_guard=guard,
    )
    event = {"headers": {}, "body": None}

    response = await ctrl.handle_create(event)

    assert response["statusCode"] == 401


# ──── handle_list Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_list_success(
    controller: MemberController,
    mock_list_use_case: AsyncMock,
    member_output: MemberOutputDTO,
) -> None:
    """List members returns 200 with paginated items."""
    mock_list_use_case.execute.return_value = PaginatedMembersDTO(
        items=[member_output],
        next_key="cursor-abc",
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "queryStringParameters": {"limit": "10"},
    }

    response = await controller.handle_list(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["items"]) == 1
    assert body["items"][0]["member_id"] == "member-001"
    assert body["next_key"] == "cursor-abc"


@pytest.mark.asyncio
async def test_handle_list_with_filters(
    controller: MemberController,
    mock_list_use_case: AsyncMock,
) -> None:
    """List members passes filter parameters to use case."""
    mock_list_use_case.execute.return_value = PaginatedMembersDTO(items=[], next_key=None)
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "queryStringParameters": {
            "account_type": "socio",
            "status": "active",
            "limit": "50",
            "cursor": "next-page-cursor",
        },
    }

    response = await controller.handle_list(event)

    assert response["statusCode"] == 200
    call_kwargs = mock_list_use_case.execute.call_args[1]
    assert call_kwargs["filters"].account_type == "socio"
    assert call_kwargs["filters"].status == "active"
    assert call_kwargs["pagination"].limit == 50
    assert call_kwargs["pagination"].cursor == "next-page-cursor"


@pytest.mark.asyncio
async def test_handle_list_no_query_params(
    controller: MemberController,
    mock_list_use_case: AsyncMock,
) -> None:
    """List members with no query params uses defaults."""
    mock_list_use_case.execute.return_value = PaginatedMembersDTO(items=[], next_key=None)
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "queryStringParameters": None,
    }

    response = await controller.handle_list(event)

    assert response["statusCode"] == 200
    call_kwargs = mock_list_use_case.execute.call_args[1]
    assert call_kwargs["filters"].account_type is None
    assert call_kwargs["filters"].status is None
    assert call_kwargs["pagination"].limit == 20
    assert call_kwargs["pagination"].cursor is None


@pytest.mark.asyncio
async def test_handle_list_viewer_allowed(
    mock_invite_use_case: AsyncMock,
    mock_list_use_case: AsyncMock,
    mock_update_use_case: AsyncMock,
    mock_deactivate_use_case: AsyncMock,
    viewer_context: AuthContext,
) -> None:
    """Viewer role can list members (PERMISSION_READ)."""
    guard = MagicMock()
    guard.validate.return_value = viewer_context
    ctrl = MemberController(
        invite_user_use_case=mock_invite_use_case,
        list_members_use_case=mock_list_use_case,
        update_member_use_case=mock_update_use_case,
        deactivate_member_use_case=mock_deactivate_use_case,
        auth_guard=guard,
    )
    mock_list_use_case.execute.return_value = PaginatedMembersDTO(items=[], next_key=None)
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "queryStringParameters": None,
    }

    response = await ctrl.handle_list(event)

    assert response["statusCode"] == 200


# ──── handle_update Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_update_success(
    controller: MemberController,
    mock_update_use_case: AsyncMock,
    member_output: MemberOutputDTO,
) -> None:
    """Update member with valid input returns 200 with updated member."""
    mock_update_use_case.execute.return_value = member_output
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "member-001"},
        "body": json.dumps({"full_name": "Jane Updated"}),
    }

    response = await controller.handle_update(event)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["member_id"] == "member-001"


@pytest.mark.asyncio
async def test_handle_update_missing_member_id_returns_400(
    controller: MemberController,
) -> None:
    """Update without member_id in path returns 400."""
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {},
        "body": json.dumps({"full_name": "Jane Updated"}),
    }

    response = await controller.handle_update(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "member_id" in body["message"]


@pytest.mark.asyncio
async def test_handle_update_not_found_returns_404(
    controller: MemberController,
    mock_update_use_case: AsyncMock,
) -> None:
    """NotFoundError (member doesn't exist) maps to 404."""
    mock_update_use_case.execute.side_effect = NotFoundError(
        "Member not found", resource="member"
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "nonexistent"},
        "body": json.dumps({"full_name": "Jane Updated"}),
    }

    response = await controller.handle_update(event)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert "Member not found" in body["message"]


@pytest.mark.asyncio
async def test_handle_update_viewer_gets_403(
    mock_invite_use_case: AsyncMock,
    mock_list_use_case: AsyncMock,
    mock_update_use_case: AsyncMock,
    mock_deactivate_use_case: AsyncMock,
    viewer_context: AuthContext,
) -> None:
    """Viewer role cannot update members — returns 403."""
    guard = MagicMock()
    guard.validate.return_value = viewer_context
    ctrl = MemberController(
        invite_user_use_case=mock_invite_use_case,
        list_members_use_case=mock_list_use_case,
        update_member_use_case=mock_update_use_case,
        deactivate_member_use_case=mock_deactivate_use_case,
        auth_guard=guard,
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "member-001"},
        "body": json.dumps({"full_name": "Jane Updated"}),
    }

    response = await ctrl.handle_update(event)

    assert response["statusCode"] == 403


@pytest.mark.asyncio
async def test_handle_update_uses_tenant_from_context(
    controller: MemberController,
    mock_update_use_case: AsyncMock,
    member_output: MemberOutputDTO,
) -> None:
    """Update uses tenant_id from AuthContext, not from body."""
    mock_update_use_case.execute.return_value = member_output
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "member-001"},
        "body": json.dumps({"account_type": "profesional"}),
    }

    await controller.handle_update(event)

    call_args = mock_update_use_case.execute.call_args[0][0]
    assert call_args.tenant_id == "550e8400-e29b-41d4-a716-446655440000"
    assert call_args.member_id == "member-001"


# ──── handle_deactivate Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_deactivate_success(
    controller: MemberController,
    mock_deactivate_use_case: AsyncMock,
) -> None:
    """Deactivate member returns 204 with empty body."""
    mock_deactivate_use_case.execute.return_value = None
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "member-001"},
    }

    response = await controller.handle_deactivate(event)

    assert response["statusCode"] == 204
    assert response["body"] == ""


@pytest.mark.asyncio
async def test_handle_deactivate_missing_member_id_returns_400(
    controller: MemberController,
) -> None:
    """Deactivate without member_id in path returns 400."""
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {},
    }

    response = await controller.handle_deactivate(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "member_id" in body["message"]


@pytest.mark.asyncio
async def test_handle_deactivate_not_found_returns_404(
    controller: MemberController,
    mock_deactivate_use_case: AsyncMock,
) -> None:
    """NotFoundError (member doesn't exist) maps to 404."""
    mock_deactivate_use_case.execute.side_effect = NotFoundError(
        "Member not found", resource="member"
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "nonexistent"},
    }

    response = await controller.handle_deactivate(event)

    assert response["statusCode"] == 404


@pytest.mark.asyncio
async def test_handle_deactivate_already_inactive_returns_400(
    controller: MemberController,
    mock_deactivate_use_case: AsyncMock,
) -> None:
    """ValidationError (already inactive) maps to 400."""
    mock_deactivate_use_case.execute.side_effect = ValidationError(
        "Member is already inactive", field="status"
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "member-001"},
    }

    response = await controller.handle_deactivate(event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "already inactive" in body["message"]


@pytest.mark.asyncio
async def test_handle_deactivate_viewer_gets_403(
    mock_invite_use_case: AsyncMock,
    mock_list_use_case: AsyncMock,
    mock_update_use_case: AsyncMock,
    mock_deactivate_use_case: AsyncMock,
    viewer_context: AuthContext,
) -> None:
    """Viewer role cannot deactivate members — returns 403."""
    guard = MagicMock()
    guard.validate.return_value = viewer_context
    ctrl = MemberController(
        invite_user_use_case=mock_invite_use_case,
        list_members_use_case=mock_list_use_case,
        update_member_use_case=mock_update_use_case,
        deactivate_member_use_case=mock_deactivate_use_case,
        auth_guard=guard,
    )
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "pathParameters": {"member_id": "member-001"},
    }

    response = await ctrl.handle_deactivate(event)

    assert response["statusCode"] == 403


# ──── Response Format Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_response_has_content_type_header(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
    member_output: MemberOutputDTO,
) -> None:
    """All responses include Content-Type: application/json."""
    mock_invite_use_case.execute.return_value = member_output
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "socio",
            "roles": ["viewer"],
        }),
    }

    response = await controller.handle_create(event)

    assert response["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_datetime_serialized_as_iso_format(
    controller: MemberController,
    mock_invite_use_case: AsyncMock,
    member_output: MemberOutputDTO,
) -> None:
    """Datetime fields are serialized as ISO 8601 strings."""
    mock_invite_use_case.execute.return_value = member_output
    event = {
        "headers": {"Authorization": "Bearer valid-token"},
        "body": json.dumps({
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "account_type": "socio",
            "roles": ["viewer"],
        }),
    }

    response = await controller.handle_create(event)

    body = json.loads(response["body"])
    assert "2024-01-15" in body["created_at"]
    assert "T" in body["created_at"]
    assert "2024-01-15" in body["updated_at"]
