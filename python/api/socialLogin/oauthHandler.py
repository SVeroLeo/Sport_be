"""Lambda handler for social (federated) login endpoints.

Mirrors the ``auth_handler.py`` pattern: it parses the API Gateway Lambda
proxy event, applies a best-effort rate-limiting check, and routes the request
to the appropriate :class:`OAuthController` method.

Routes:
- GET  /auth/social/authorize     -> OAuthController.handle_authorize      (sync)
- GET  /auth/social/callback      -> OAuthController.handle_callback       (async)
- POST /auth/social/select-tenant -> OAuthController.handle_select_tenant  (async)

Rate limiting (Requirement 8.6):
    The ``/authorize`` and ``/callback`` endpoints are rate limited to a maximum
    of 20 requests per source IP within a rolling 5-minute window; exceeding the
    limit yields HTTP 429 ``{"error": "rate_limit_exceeded"}``. The counter is an
    in-memory, module-level structure and is therefore *best-effort*: it is scoped
    to a single warm Lambda instance and resets on cold start. The authoritative
    rate limiter is the AWS WAF associated with the ``/auth/social/*`` resource
    (design 8.3/8.6); this handler-level check is a lightweight second line of
    defence. ``/select-tenant`` is intentionally not rate limited here.

The composition root (task 15.2, ``social_login_composition_root.py``) builds the
wired :class:`OAuthController`; this handler only routes to it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ──── Rate limiting configuration (Requirement 8.6) ───────────────────────────

# Maximum number of requests allowed per source IP within the window.
_RATE_LIMIT_MAX_REQUESTS = 20
# Rolling window length, in seconds (5 minutes).
_RATE_LIMIT_WINDOW_SECONDS = 5 * 60

# Module-level (per warm Lambda instance) sliding-window store: source IP -> deque
# of request timestamps (monotonic seconds). Best-effort only — see module docstring.
_request_log: dict[str, deque[float]] = defaultdict(deque)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine in a Lambda-safe way.

    Uses ``asyncio.run()`` which creates a new event loop — the standard
    approach for AWS Lambda Python runtimes.

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
        message: Machine-readable error code (the ``error`` field).

    Returns:
        API Gateway Lambda proxy response dict.
    """
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


def _extract_source_ip(event: dict[str, Any]) -> str:
    """Extract the client source IP from the event.

    Prefers ``requestContext.identity.sourceIp`` (API Gateway-provided); falls
    back to the first entry of the ``X-Forwarded-For`` header.

    Args:
        event: API Gateway Lambda proxy event dict.

    Returns:
        The source IP string, or an empty string when unavailable.
    """
    request_context = event.get("requestContext") or {}
    identity = request_context.get("identity") or {}
    source_ip = identity.get("sourceIp")
    if source_ip:
        return str(source_ip)

    headers = event.get("headers") or {}
    forwarded_for = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if forwarded_for:
        return str(forwarded_for).split(",")[0].strip()

    return ""


def _is_rate_limited(source_ip: str, *, now: float | None = None) -> bool:
    """Record a request for ``source_ip`` and report whether it exceeds the limit.

    Implements a sliding-window counter: timestamps older than the window are
    evicted, the current request is appended, and the request is limited when the
    window holds more than ``_RATE_LIMIT_MAX_REQUESTS`` entries. When the source
    IP is unknown (empty), the check is skipped (returns ``False``) so requests
    are never blocked on missing identity.

    Args:
        source_ip: The client source IP; empty means "unknown".
        now: Optional current time in seconds (monotonic-like); defaults to
            ``time.monotonic()``. Injectable for testing.

    Returns:
        ``True`` when the request should be rejected with HTTP 429, else ``False``.
    """
    if not source_ip:
        return False

    current = time.monotonic() if now is None else now
    cutoff = current - _RATE_LIMIT_WINDOW_SECONDS

    timestamps = _request_log[source_ip]
    # Evict timestamps that fall outside the rolling window.
    while timestamps and timestamps[0] <= cutoff:
        timestamps.popleft()

    timestamps.append(current)

    return len(timestamps) > _RATE_LIMIT_MAX_REQUESTS


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for social-login routes.

    Parses the API Gateway proxy event, applies the best-effort rate-limiting
    check to ``/authorize`` and ``/callback``, and routes to the matching
    :class:`OAuthController` method by HTTP method + path.

    Routing table:
        GET  .../auth/social/authorize     -> handle_authorize      (sync)
        GET  .../auth/social/callback      -> handle_callback       (async)
        POST .../auth/social/select-tenant -> handle_select_tenant  (async)

    Unknown paths return 404; mismatched methods return 405.

    Args:
        event: API Gateway Lambda proxy event.
        context: Lambda context object (unused).

    Returns:
        API Gateway Lambda proxy response dict.
    """
    from api.socialLogin.socialLoginCompositionRoot import (
        get_social_login_container,
    )

    try:
        controller = get_social_login_container().oauth_controller

        http_method = (event.get("httpMethod") or "").upper()
        # Prefer the API Gateway resource template; fall back to the concrete path.
        resource = event.get("resource") or event.get("path") or ""

        # Rate limiting applies only to authorize + callback (Requirement 8.6).
        if resource.endswith("/authorize") or resource.endswith("/callback"):
            source_ip = _extract_source_ip(event)
            if _is_rate_limited(source_ip):
                logger.warning(
                    "Rate limit exceeded for social-login endpoint resource=%s", resource
                )
                return _error_response(429, "rate_limit_exceeded")

        if resource.endswith("/authorize"):
            if http_method != "GET":
                return _error_response(405, "method_not_allowed")
            # handle_authorize is synchronous.
            return controller.handle_authorize(event)

        if resource.endswith("/callback"):
            if http_method != "GET":
                return _error_response(405, "method_not_allowed")
            return _run_async(controller.handle_callback(event))

        if resource.endswith("/select-tenant"):
            if http_method != "POST":
                return _error_response(405, "method_not_allowed")
            return _run_async(controller.handle_select_tenant(event))

        return _error_response(404, "route_not_found")

    except Exception:
        logger.exception("Unexpected error in oauth_handler")
        return _error_response(500, "internal_error")
