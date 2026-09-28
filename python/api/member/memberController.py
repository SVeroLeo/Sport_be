"""MemberController — handles HTTP requests for member management operations.

Provides handlers for:
- handle_create: Invite/create a new member (POST /members)
- handle_list: List members with filters (GET /members)
- handle_update: Update an existing member (PUT /members/{member_id})
- handle_deactivate: Deactivate a member (DELETE /members/{member_id})

Each handler follows the pattern:
1. Validate auth via AuthGuard
2. Check permissions via RoleGuard
3. Parse request
4. Call use case
5. Return response

Requirements satisfied: 4.1, 6.1, 7.1, 8.1
"""

from __future__ import annotations

import json
import logging
from typing import Any

from api.member.createMemberInputDto import CreateMemberInputDTO
from api.member.updateMemberInputDto import UpdateMemberInputDTO
from api.common.ports.sharedTypes import MemberFilters, PaginationParams
from api.member.deactivateMemberUseCase import DeactivateMemberUseCase
from api.member.listMembersUseCase import ListMembersUseCase
from api.member.updateMemberUseCase import UpdateMemberUseCase
from api.registration.inviteUserUseCase import InviteUserUseCase
from api.common.user.userRole import PERMISSION_MANAGE_MEMBERS, PERMISSION_READ
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.common.http.roleGuardMiddleware import check_permission
from api.common.http.authGuardMiddleware import AuthContext, AuthGuardMiddleware

logger = logging.getLogger(__name__)


class MemberController:
    """Controller for member management endpoints.

    Receives all use cases and middleware via constructor injection.
    """

    def __init__(
        self,
        invite_user_use_case: InviteUserUseCase,
        list_members_use_case: ListMembersUseCase,
        update_member_use_case: UpdateMemberUseCase,
        deactivate_member_use_case: DeactivateMemberUseCase,
        auth_guard: AuthGuardMiddleware,
    ) -> None:
        self._invite_user_use_case = invite_user_use_case
        self._list_members_use_case = list_members_use_case
        self._update_member_use_case = update_member_use_case
        self._deactivate_member_use_case = deactivate_member_use_case
        self._auth_guard = auth_guard

    # ──── Handlers ────────────────────────────────────────────────────────────

    async def handle_create(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /members — invite/create a new member.

        Requires PERMISSION_MANAGE_MEMBERS.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            201 with created member data, or error response.
        """
        # 1. Validate auth via AuthGuard
        auth_result = self._auth_guard.validate(event)
        if not isinstance(auth_result, AuthContext):
            return auth_result

        # 2. Check permissions
        permission_error = check_permission(auth_result, PERMISSION_MANAGE_MEMBERS)
        if permission_error is not None:
            return permission_error

        # 3. Parse request body
        try:
            body = self._parse_body(event)
        except (json.JSONDecodeError, TypeError):
            return self._error_response(400, "Invalid request body")

        if not body:
            return self._error_response(400, "Request body is required")

        # 4. Build input DTO
        try:
            input_dto = CreateMemberInputDTO(
                tenant_id=auth_result.tenant_id,
                email=body.get("email", ""),
                full_name=body.get("full_name", ""),
                account_type=body.get("account_type", ""),
                roles=body.get("roles", []),
            )
        except Exception as e:
            return self._error_response(400, str(e))

        # 5. Execute use case
        try:
            result = await self._invite_user_use_case.execute(
                input_dto=input_dto,
                created_by_user_id=auth_result.user_id,
            )
        except ValidationError as e:
            return self._error_response(400, e.message)
        except ConflictError as e:
            return self._error_response(409, e.message)
        except NotFoundError as e:
            return self._error_response(404, e.message)
        except DomainError as e:
            return self._error_response(400, e.message)

        # 6. Return success response
        return self._success_response(201, self._serialize_member(result))

    async def handle_list(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle GET /members — list members with optional filters.

        Requires PERMISSION_READ.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            200 with paginated member list, or error response.
        """
        # 1. Validate auth via AuthGuard
        auth_result = self._auth_guard.validate(event)
        if not isinstance(auth_result, AuthContext):
            return auth_result

        # 2. Check permissions
        permission_error = check_permission(auth_result, PERMISSION_READ)
        if permission_error is not None:
            return permission_error

        # 3. Parse query parameters
        query_params = event.get("queryStringParameters") or {}

        filters = MemberFilters(
            account_type=query_params.get("account_type"),
            status=query_params.get("status"),
        )

        limit = self._parse_limit(query_params.get("limit"))
        cursor = query_params.get("cursor")

        pagination = PaginationParams(limit=limit, cursor=cursor)

        # 4. Execute use case
        try:
            result = await self._list_members_use_case.execute(
                tenant_id=auth_result.tenant_id,
                filters=filters,
                pagination=pagination,
            )
        except ValidationError as e:
            return self._error_response(400, e.message)
        except DomainError as e:
            return self._error_response(400, e.message)

        # 5. Return paginated response
        response_body = {
            "items": [self._serialize_member(item) for item in result.items],
            "next_key": result.next_key,
        }
        return self._success_response(200, response_body)

    async def handle_update(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle PUT /members/{member_id} — update an existing member.

        Requires PERMISSION_MANAGE_MEMBERS.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            200 with updated member data, or error response.
        """
        # 1. Validate auth via AuthGuard
        auth_result = self._auth_guard.validate(event)
        if not isinstance(auth_result, AuthContext):
            return auth_result

        # 2. Check permissions
        permission_error = check_permission(auth_result, PERMISSION_MANAGE_MEMBERS)
        if permission_error is not None:
            return permission_error

        # 3. Extract member_id from path parameters
        path_params = event.get("pathParameters") or {}
        member_id = path_params.get("member_id")
        if not member_id:
            return self._error_response(400, "member_id path parameter is required")

        # 4. Parse request body
        try:
            body = self._parse_body(event)
        except (json.JSONDecodeError, TypeError):
            return self._error_response(400, "Invalid request body")

        if not body:
            return self._error_response(400, "Request body is required")

        # 5. Build input DTO
        try:
            input_dto = UpdateMemberInputDTO(
                tenant_id=auth_result.tenant_id,
                member_id=member_id,
                account_type=body.get("account_type"),
                full_name=body.get("full_name"),
                email=body.get("email"),
                status=body.get("status"),
                metadata=body.get("metadata"),
            )
        except Exception as e:
            return self._error_response(400, str(e))

        # 6. Execute use case
        try:
            result = await self._update_member_use_case.execute(input_dto)
        except ValidationError as e:
            return self._error_response(400, e.message)
        except NotFoundError as e:
            return self._error_response(404, e.message)
        except DomainError as e:
            return self._error_response(400, e.message)

        # 7. Return success response
        return self._success_response(200, self._serialize_member(result))

    async def handle_deactivate(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle DELETE /members/{member_id} — deactivate a member.

        Requires PERMISSION_MANAGE_MEMBERS.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            204 with no content on success, or error response.
        """
        # 1. Validate auth via AuthGuard
        auth_result = self._auth_guard.validate(event)
        if not isinstance(auth_result, AuthContext):
            return auth_result

        # 2. Check permissions
        permission_error = check_permission(auth_result, PERMISSION_MANAGE_MEMBERS)
        if permission_error is not None:
            return permission_error

        # 3. Extract member_id from path parameters
        path_params = event.get("pathParameters") or {}
        member_id = path_params.get("member_id")
        if not member_id:
            return self._error_response(400, "member_id path parameter is required")

        # 4. Execute use case
        try:
            await self._deactivate_member_use_case.execute(
                tenant_id=auth_result.tenant_id,
                member_id=member_id,
            )
        except ValidationError as e:
            return self._error_response(400, e.message)
        except NotFoundError as e:
            return self._error_response(404, e.message)
        except DomainError as e:
            return self._error_response(400, e.message)

        # 5. Return 204 No Content
        return {
            "statusCode": 204,
            "headers": {"Content-Type": "application/json"},
            "body": "",
        }

    # ──── Private Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
        """Parse the JSON body from an API Gateway event.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            Parsed body as a dictionary.

        Raises:
            json.JSONDecodeError: If body is not valid JSON.
            TypeError: If body is None.
        """
        body = event.get("body")
        if body is None:
            return {}
        if isinstance(body, dict):
            return body
        return json.loads(body)

    @staticmethod
    def _parse_limit(limit_str: str | None) -> int:
        """Parse and validate the limit query parameter.

        Args:
            limit_str: The raw limit string from query parameters.

        Returns:
            Integer limit value clamped between 1 and 100, defaulting to 20.
        """
        if not limit_str:
            return 20
        try:
            limit = int(limit_str)
            return max(1, min(100, limit))
        except (ValueError, TypeError):
            return 20

    @staticmethod
    def _serialize_member(member: Any) -> dict[str, Any]:
        """Serialize a MemberOutputDTO to a JSON-compatible dictionary.

        Converts datetime fields to ISO 8601 format strings.

        Args:
            member: MemberOutputDTO instance.

        Returns:
            Dictionary with all member fields, datetimes as ISO strings.
        """
        return {
            "member_id": member.member_id,
            "tenant_id": member.tenant_id,
            "user_id": member.user_id,
            "account_type": member.account_type,
            "account_type_id": member.account_type_id,
            "full_name": member.full_name,
            "email": member.email,
            "status": member.status,
            "registration_type": member.registration_type,
            "invited_by": member.invited_by,
            "metadata": member.metadata,
            "created_at": member.created_at.isoformat(),
            "updated_at": member.updated_at.isoformat(),
        }

    @staticmethod
    def _success_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
        """Build a successful API Gateway response.

        Args:
            status_code: HTTP status code.
            body: Response body to serialize.

        Returns:
            API Gateway Lambda proxy response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, default=str),
        }

    @staticmethod
    def _error_response(status_code: int, message: str) -> dict[str, Any]:
        """Build an error API Gateway response.

        Args:
            status_code: HTTP status code (400, 404, 409, etc.).
            message: Human-readable error message.

        Returns:
            API Gateway Lambda proxy response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"message": message}),
        }
