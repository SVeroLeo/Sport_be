"""AccountTypeController — handles HTTP requests for account type CRUD operations.

Each handler:
1. Validates authentication via TenantGuard middleware.
2. Checks role-based permissions via RoleGuard.
3. Parses the request and maps to application-layer DTOs.
4. Executes the appropriate use case.
5. Maps the result to an API Gateway Lambda proxy response.

Requirements satisfied: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from application.dtos.account_type.create_account_type_input_dto import (
    CreateAccountTypeInputDTO,
)
from application.dtos.account_type.update_account_type_input_dto import (
    UpdateAccountTypeInputDTO,
)
from application.ports.shared_types import PaginationParams
from domain.entities.user_role import (
    PERMISSION_CREATE,
    PERMISSION_DELETE,
    PERMISSION_READ,
    PERMISSION_UPDATE,
)
from domain.errors.conflict_error import ConflictError
from domain.errors.domain_error import DomainError
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError
from interfaces.http.middleware.role_guard_middleware import check_permission
from interfaces.http.middleware.tenant_guard_middleware import TenantContext

if TYPE_CHECKING:
    from application.use_cases.account_type.create_account_type_use_case import (
        CreateAccountTypeUseCase,
    )
    from application.use_cases.account_type.delete_account_type_use_case import (
        DeleteAccountTypeUseCase,
    )
    from application.use_cases.account_type.list_account_types_use_case import (
        ListAccountTypesUseCase,
    )
    from application.use_cases.account_type.update_account_type_use_case import (
        UpdateAccountTypeUseCase,
    )
    from interfaces.http.middleware.tenant_guard_middleware import (
        TenantGuardMiddleware,
    )

logger = logging.getLogger(__name__)


class AccountTypeController:
    """Controller for account type CRUD operations.

    Receives all use cases and TenantGuardMiddleware via constructor injection.
    """

    def __init__(
        self,
        tenant_guard: TenantGuardMiddleware,
        create_use_case: CreateAccountTypeUseCase,
        list_use_case: ListAccountTypesUseCase,
        update_use_case: UpdateAccountTypeUseCase,
        delete_use_case: DeleteAccountTypeUseCase,
    ) -> None:
        self._tenant_guard = tenant_guard
        self._create_use_case = create_use_case
        self._list_use_case = list_use_case
        self._update_use_case = update_use_case
        self._delete_use_case = delete_use_case

    # ──── Create ──────────────────────────────────────────────────────────────

    async def handle_create(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /account-types — create a new account type.

        Requires PERMISSION_CREATE.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            API Gateway response dict with statusCode 201 on success.
        """
        # 1. Authenticate
        auth_result = self._tenant_guard.validate(event)
        if not isinstance(auth_result, TenantContext):
            return auth_result

        # 2. Authorize
        permission_result = check_permission(auth_result, PERMISSION_CREATE)
        if permission_result is not None:
            return permission_result

        # 3. Parse request body
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        name = body.get("name")
        if not name or not isinstance(name, str):
            return self._error_response(400, "Field 'name' is required")

        # 4. Build DTO and execute use case
        input_dto = CreateAccountTypeInputDTO(
            tenant_id=auth_result.tenant_id,
            name=name,
            description=body.get("description"),
            config=body.get("config"),
        )

        try:
            result = await self._create_use_case.execute(input_dto)
        except ValidationError as e:
            return self._error_response(400, e.message)
        except ConflictError as e:
            return self._error_response(409, e.message)
        except NotFoundError as e:
            return self._error_response(404, e.message)
        except DomainError as e:
            return self._error_response(400, e.message)

        # 5. Map to response
        return self._success_response(201, self._serialize_account_type(result))

    # ──── List ────────────────────────────────────────────────────────────────

    async def handle_list(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle GET /account-types — list account types for the tenant.

        Requires PERMISSION_READ.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            API Gateway response dict with statusCode 200 on success.
        """
        # 1. Authenticate
        auth_result = self._tenant_guard.validate(event)
        if not isinstance(auth_result, TenantContext):
            return auth_result

        # 2. Authorize
        permission_result = check_permission(auth_result, PERMISSION_READ)
        if permission_result is not None:
            return permission_result

        # 3. Parse pagination params from query string
        query_params = event.get("queryStringParameters") or {}
        limit = self._parse_int(query_params.get("limit"), default=20, min_val=1, max_val=100)
        cursor = query_params.get("cursor") or None

        pagination = PaginationParams(limit=limit, cursor=cursor)

        # 4. Execute use case
        try:
            result = await self._list_use_case.execute(auth_result.tenant_id, pagination)
        except ValidationError as e:
            return self._error_response(400, e.message)

        # 5. Map to response
        response_body: dict[str, Any] = {
            "items": [self._serialize_account_type(item) for item in result.items],
            "next_key": result.next_key,
        }

        return self._success_response(200, response_body)

    # ──── Update ──────────────────────────────────────────────────────────────

    async def handle_update(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle PUT /account-types/{id} — update an existing account type.

        Requires PERMISSION_UPDATE.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            API Gateway response dict with statusCode 200 on success.
        """
        # 1. Authenticate
        auth_result = self._tenant_guard.validate(event)
        if not isinstance(auth_result, TenantContext):
            return auth_result

        # 2. Authorize
        permission_result = check_permission(auth_result, PERMISSION_UPDATE)
        if permission_result is not None:
            return permission_result

        # 3. Extract path parameter
        path_params = event.get("pathParameters") or {}
        account_type_id = path_params.get("id")
        if not account_type_id:
            return self._error_response(400, "Missing path parameter 'id'")

        # 4. Parse request body
        body = self._parse_body(event)
        if body is None:
            return self._error_response(400, "Invalid or missing request body")

        # 5. Build DTO and execute use case
        input_dto = UpdateAccountTypeInputDTO(
            tenant_id=auth_result.tenant_id,
            account_type_id=account_type_id,
            name=body.get("name"),
            description=body.get("description"),
            config=body.get("config"),
        )

        try:
            result = await self._update_use_case.execute(input_dto)
        except ValidationError as e:
            return self._error_response(400, e.message)
        except NotFoundError as e:
            return self._error_response(404, e.message)
        except ConflictError as e:
            return self._error_response(409, e.message)
        except DomainError as e:
            return self._error_response(400, e.message)

        # 6. Map to response
        return self._success_response(200, self._serialize_account_type(result))

    # ──── Delete ──────────────────────────────────────────────────────────────

    async def handle_delete(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle DELETE /account-types/{id} — soft-delete an account type.

        Requires PERMISSION_DELETE.

        Args:
            event: API Gateway Lambda proxy event.

        Returns:
            API Gateway response dict with statusCode 204 on success.
        """
        # 1. Authenticate
        auth_result = self._tenant_guard.validate(event)
        if not isinstance(auth_result, TenantContext):
            return auth_result

        # 2. Authorize
        permission_result = check_permission(auth_result, PERMISSION_DELETE)
        if permission_result is not None:
            return permission_result

        # 3. Extract path parameter
        path_params = event.get("pathParameters") or {}
        account_type_id = path_params.get("id")
        if not account_type_id:
            return self._error_response(400, "Missing path parameter 'id'")

        # 4. Execute use case
        try:
            await self._delete_use_case.execute(auth_result.tenant_id, account_type_id)
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
    def _parse_body(event: dict[str, Any]) -> dict[str, Any] | None:
        """Parse JSON body from the API Gateway event.

        Args:
            event: API Gateway event dict.

        Returns:
            Parsed dict or None if the body is missing/invalid.
        """
        body_str = event.get("body")
        if not body_str:
            return None
        try:
            parsed = json.loads(body_str)
            if not isinstance(parsed, dict):
                return None
            return parsed
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _parse_int(value: str | None, *, default: int, min_val: int, max_val: int) -> int:
        """Parse an integer from a string with bounds clamping.

        Args:
            value: The string to parse (may be None).
            default: Default value if parsing fails.
            min_val: Minimum allowed value.
            max_val: Maximum allowed value.

        Returns:
            Parsed and clamped integer value.
        """
        if value is None:
            return default
        try:
            parsed = int(value)
            return max(min_val, min(max_val, parsed))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _serialize_account_type(dto: Any) -> dict[str, Any]:
        """Serialize an AccountTypeOutputDTO to a JSON-safe dict.

        Converts datetime fields to ISO format strings.

        Args:
            dto: An AccountTypeOutputDTO instance.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        data = dto.model_dump()
        if data.get("created_at"):
            data["created_at"] = data["created_at"].isoformat()
        if data.get("updated_at"):
            data["updated_at"] = data["updated_at"].isoformat()
        return data

    @staticmethod
    def _success_response(status_code: int, body: Any) -> dict[str, Any]:
        """Build a successful API Gateway response.

        Args:
            status_code: HTTP status code.
            body: Response body (will be JSON-serialized).

        Returns:
            API Gateway Lambda proxy response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body),
        }

    @staticmethod
    def _error_response(status_code: int, message: str) -> dict[str, Any]:
        """Build an error API Gateway response.

        Args:
            status_code: HTTP status code.
            message: Error message.

        Returns:
            API Gateway Lambda proxy response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"message": message}),
        }
