"""Lambda handler for authentication endpoints.

Routes:
- POST /auth/login                   -> AuthController.handle_login
- POST /auth/refresh                 -> AuthController.handle_refresh
- POST /auth/logout                  -> AuthController.handle_logout
- POST /auth/forgot-password         -> AuthController.handle_forgot_password
- POST /auth/confirm-forgot-password -> AuthController.handle_confirm_forgot_password
- POST /auth/respond-to-challenge    -> AuthController.handle_respond_to_challenge

Each route requires POST method. A non-POST method returns 405 with an
``Allow: POST`` header; unknown paths return 404.
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


def _method_not_allowed() -> dict[str, Any]:
    """Build a 405 Method Not Allowed response with an ``Allow: POST`` header.

    Returns:
        API Gateway Lambda proxy response dict advertising POST as the only
        allowed method for the auth routes.
    """
    return {
        "statusCode": 405,
        "headers": {"Content-Type": "application/json", "Allow": "POST"},
        "body": json.dumps({"error": "Method not allowed"}),
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
    from api.common.compositionRoot import get_container

    try:
        container = get_container()

        http_method = (event.get("httpMethod") or "").upper()
        if http_method != "POST":
            return _method_not_allowed()

        # Determine sub-route from resource or path
        resource = event.get("resource") or event.get("path") or ""

        # Order matters: check "/confirm-forgot-password" before
        # "/forgot-password" to avoid any mis-routing on shared suffixes.
        if resource.endswith("/login"):
            return _run_async(container.auth_controller.handle_login(event))
        elif resource.endswith("/refresh"):
            return _run_async(container.auth_controller.handle_refresh(event))
        elif resource.endswith("/logout"):
            return _run_async(container.auth_controller.handle_logout(event))
        elif resource.endswith("/confirm-forgot-password"):
            return _run_async(
                container.auth_controller.handle_confirm_forgot_password(event)
            )
        elif resource.endswith("/forgot-password"):
            return _run_async(
                container.auth_controller.handle_forgot_password(event)
            )
        elif resource.endswith("/respond-to-challenge"):
            return _run_async(
                container.auth_controller.handle_respond_to_challenge(event)
            )
        else:
            return _error_response(404, "Route not found")

    except Exception:
        logger.exception("Unexpected error in auth_handler")
        return _error_response(500, "Internal server error")
