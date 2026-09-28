"""Lambda handler for the user self-registration endpoint.

Routes:
- POST /auth/register -> RegistrationController.handle_register

This is a public endpoint — no AuthGuard middleware required.
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
    """Lambda entry point for user self-registration.

    Only accepts POST requests. Delegates to
    RegistrationController.handle_register.

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object (unused).

    Returns:
        API Gateway Lambda proxy response dict.
    """
    from api.common.compositionRoot import get_container

    try:
        container = get_container()

        http_method = (event.get("httpMethod") or "").upper()
        if http_method != "POST":
            return _error_response(405, "Method not allowed")

        return _run_async(container.registration_controller.handle_register(event))

    except Exception:
        logger.exception("Unexpected error in registration_handler")
        return _error_response(500, "Internal server error")
