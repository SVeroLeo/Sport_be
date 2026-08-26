"""Lambda handler for authentication endpoints.

Routes:
- POST /auth/login   -> AuthController.handle_login
- POST /auth/refresh -> AuthController.handle_refresh
- POST /auth/logout  -> AuthController.handle_logout

Each route requires POST method. Unknown paths or methods return
405 Method Not Allowed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine in a Lambda-safe way.

    Uses asyncio.run() which creates a new event loop. This is the
    standard approach for AWS Lambda Python runtimes.

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
    """Lambda entry point for authentication routes.

    Routes incoming requests to the appropriate AuthController method
    based on the resource path. Only POST method is accepted.

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
        if http_method != "POST":
            return _error_response(405, "Method not allowed")

        # Determine sub-route from resource or path
        resource = event.get("resource") or event.get("path") or ""

        if resource.endswith("/login"):
            return _run_async(container.auth_controller.handle_login(event))
        elif resource.endswith("/refresh"):
            return _run_async(container.auth_controller.handle_refresh(event))
        elif resource.endswith("/logout"):
            return _run_async(container.auth_controller.handle_logout(event))
        else:
            return _error_response(404, "Route not found")

    except Exception:
        logger.exception("Unexpected error in auth_handler")
        return _error_response(500, "Internal server error")
