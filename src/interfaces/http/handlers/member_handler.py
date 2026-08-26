"""Lambda handler for member management endpoints.

Routes:
- POST   /members             -> MemberController.handle_create (invite)
- GET    /members             -> MemberController.handle_list
- PUT    /members/{member_id} -> MemberController.handle_update
- DELETE /members/{member_id} -> MemberController.handle_deactivate

All routes require authenticated access (TenantGuard is applied
within the controller).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine in a Lambda-safe way.

    Args:
        coro: The coroutine to execute.

    Returns:
        The result of the coroutine.
    """
    return asyncio.run(coro)


def _error_response(status_code: int, message: str) -> dict[str, Any]:
    """Build a standardized error response.

    Args:
        status_code: HTTP status code.
        message: Error message.

    Returns:
        API Gateway Lambda proxy response dict.
    """
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for member management operations.

    Routes requests to the appropriate MemberController method
    based on the HTTP method.

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object (unused).

    Returns:
        API Gateway Lambda proxy response dict.
    """
    from interfaces.http.composition_root import get_container

    try:
        container = get_container()

        http_method = (event.get("httpMethod") or "").upper()

        if http_method == "POST":
            return _run_async(container.member_controller.handle_create(event))
        elif http_method == "GET":
            return _run_async(container.member_controller.handle_list(event))
        elif http_method == "PUT":
            return _run_async(container.member_controller.handle_update(event))
        elif http_method == "DELETE":
            return _run_async(container.member_controller.handle_deactivate(event))
        else:
            return _error_response(405, "Method not allowed")

    except Exception:
        logger.exception("Unexpected error in member_handler")
        return _error_response(500, "Internal server error")
