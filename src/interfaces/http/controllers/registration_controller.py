"""RegistrationController — handles user self-registration HTTP requests.

Implements Requirements:
- 3.1: Register user in Cognito and return confirmation-pending status
- 3.2: Post-confirmation trigger creates records (handled downstream)
- 3.3: Return 409 if email already registered
- 3.4: Return 404 if tenant not found
- 3.5: Return 403 if tenant is not active or self-registration not allowed
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError

from application.dtos.auth.register_input_dto import RegisterInputDTO
from domain.errors.conflict_error import ConflictError
from domain.errors.domain_error import DomainError
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError

if TYPE_CHECKING:
    from application.use_cases.registration.register_use_case import RegisterUseCase

logger = logging.getLogger(__name__)


class RegistrationController:
    """Controller for user self-registration endpoint.

    Parses the Lambda event body, validates input via Pydantic,
    delegates to RegisterUseCase, and maps the result or domain
    errors to appropriate HTTP responses.

    This is a public endpoint — no TenantGuard middleware required.
    """

    def __init__(self, register_use_case: RegisterUseCase) -> None:
        """Initialize the controller with its use case dependency.

        Args:
            register_use_case: The application use case for self-registration.
        """
        self._register_use_case = register_use_case

    async def handle_register(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle POST /auth/register requests.

        Parses the request body into a RegisterInputDTO, executes
        the registration use case, and returns the appropriate
        HTTP response with status code mapping:
        - 201: Registration successful (confirmation pending)
        - 400: Validation error (invalid input data)
        - 403: Tenant not active or self-registration not allowed
        - 404: Tenant not found
        - 409: Email already registered

        Args:
            event: API Gateway Lambda proxy event dict with 'body' key.

        Returns:
            API Gateway Lambda proxy response dict with statusCode,
            headers, and JSON body.
        """
        # 1. Parse request body
        body = event.get("body")
        if not body:
            return self._error_response(400, "Request body is required")

        try:
            parsed_body = json.loads(body) if isinstance(body, str) else body
        except (json.JSONDecodeError, TypeError):
            return self._error_response(400, "Invalid JSON in request body")

        # 2. Validate input via Pydantic DTO
        try:
            input_dto = RegisterInputDTO(**parsed_body)
        except PydanticValidationError as e:
            first_error = e.errors()[0] if e.errors() else {}
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            message = first_error.get("msg", "Validation error")
            return self._error_response(400, f"Invalid input: {field} - {message}")

        # 3. Execute use case and map result/errors
        try:
            output = await self._register_use_case.execute(input_dto)
        except ValidationError as e:
            return self._error_response(400, e.message)
        except ConflictError as e:
            return self._error_response(409, e.message)
        except NotFoundError as e:
            return self._error_response(404, e.message)
        except DomainError as e:
            return self._error_response(403, e.message)

        # 4. Return success response (201 Created)
        return self._success_response(201, {
            "user_id": output.user_id,
            "email": output.email,
            "full_name": output.full_name,
            "status": output.status,
            "message": output.message,
        })

    @staticmethod
    def _success_response(status_code: int, data: dict[str, Any]) -> dict[str, Any]:
        """Build a successful HTTP response.

        Args:
            status_code: HTTP status code (e.g. 201).
            data: Response payload to serialize as JSON body.

        Returns:
            API Gateway Lambda proxy response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data),
        }

    @staticmethod
    def _error_response(status_code: int, message: str) -> dict[str, Any]:
        """Build an error HTTP response.

        Args:
            status_code: HTTP status code (e.g. 400, 403, 409).
            message: Human-readable error message.

        Returns:
            API Gateway Lambda proxy response dict.
        """
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": message}),
        }
