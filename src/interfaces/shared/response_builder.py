"""Standardized API Gateway Lambda response builder.

Provides helper functions for building consistent API Gateway Lambda proxy
responses with CORS headers and JSON serialization.
"""

from __future__ import annotations

import json
from typing import Any

_CORS_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "*",
}


def success_response(status_code: int, data: Any) -> dict[str, Any]:
    """Build a success response for API Gateway.

    Args:
        status_code: HTTP status code (200, 201, etc.).
        data: Response payload to serialize as JSON body.

    Returns:
        API Gateway Lambda proxy response dict.
    """
    return {
        "statusCode": status_code,
        "headers": {**_CORS_HEADERS},
        "body": json.dumps(data, default=str),
    }


def error_response(status_code: int, message: str) -> dict[str, Any]:
    """Build an error response for API Gateway.

    Args:
        status_code: HTTP error status code (400, 401, 403, 404, 409, 500).
        message: Human-readable error message.

    Returns:
        API Gateway Lambda proxy response dict.
    """
    return {
        "statusCode": status_code,
        "headers": {**_CORS_HEADERS},
        "body": json.dumps({"error": message}),
    }


def no_content_response() -> dict[str, Any]:
    """Build a 204 No Content response for API Gateway.

    Returns:
        API Gateway Lambda proxy response dict with empty body.
    """
    return {
        "statusCode": 204,
        "headers": {**_CORS_HEADERS},
        "body": "",
    }
