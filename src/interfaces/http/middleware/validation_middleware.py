"""Validation middleware — schema validation for HTTP request bodies.

Provides a reusable function to validate API Gateway Lambda event bodies
against Pydantic model schemas. Returns either a validated model instance
or a standardized 400 error response with field-level validation details.

Requirements: 11.1, 11.2, 11.3, 11.4
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def validate_request(
    event: dict[str, Any], model_class: type[T]
) -> tuple[T | None, dict[str, Any] | None]:
    """Validate the request body from an API Gateway event against a Pydantic model.

    Parses the event body (handles both JSON string and dict) and validates
    it against the provided Pydantic model class. On success, returns the
    validated model instance. On failure, returns a formatted 400 error response.

    Args:
        event: API Gateway Lambda proxy event dict containing 'body'.
        model_class: The Pydantic model class to validate against.

    Returns:
        Tuple of (validated_model, None) on success,
        or (None, error_response_dict) on validation failure.
    """
    # Parse the event body
    body = _parse_event_body(event)
    if body is None:
        return None, _error_response("Invalid or missing request body", details=None)

    # Validate against the Pydantic model
    try:
        validated = model_class.model_validate(body)
        return validated, None
    except ValidationError as e:
        details = _format_validation_errors(e)
        # Use the first error message as the top-level message
        first_message = details[0]["message"] if details else "Validation failed"
        return None, _error_response(first_message, details=details)


def _parse_event_body(event: dict[str, Any]) -> dict[str, Any] | None:
    """Parse the body from an API Gateway Lambda proxy event.

    Handles both pre-parsed dicts (from tests or internal calls)
    and JSON strings (from API Gateway).

    Args:
        event: API Gateway event dict.

    Returns:
        Parsed body dict, or None if missing/invalid.
    """
    body = event.get("body")

    if body is None:
        return None

    # Already parsed (e.g., in tests or internal routing)
    if isinstance(body, dict):
        return body

    # Parse JSON string
    if isinstance(body, str):
        if not body.strip():
            return None
        try:
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                return None
            return parsed
        except (json.JSONDecodeError, TypeError):
            return None

    return None


def _format_validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    """Format Pydantic ValidationError into a user-friendly list of field errors.

    Maps Pydantic error types to clear, human-readable messages appropriate
    for API consumers.

    Args:
        error: The Pydantic ValidationError to format.

    Returns:
        List of dicts with 'field', 'message', and 'type' keys.
    """
    details: list[dict[str, Any]] = []

    for err in error.errors():
        # Build field path (e.g., "roles.0" for nested field errors)
        field_parts = [str(part) for part in err.get("loc", [])]
        # Skip "body" if it appears as the first location element
        if field_parts and field_parts[0] == "body":
            field_parts = field_parts[1:]
        field = ".".join(field_parts) if field_parts else "unknown"

        # Map Pydantic error messages to user-friendly messages
        message = _humanize_error_message(err, field)

        details.append({
            "field": field,
            "message": message,
            "type": err.get("type", "validation_error"),
        })

    return details


def _humanize_error_message(err: dict[str, Any], field: str) -> str:
    """Convert a Pydantic error dict into a human-readable message.

    Handles common Pydantic error types and falls back to the raw
    message for unrecognized types.

    Args:
        err: A single error dict from Pydantic's ValidationError.errors().
        field: The field name for context in the message.

    Returns:
        Human-readable error message string.
    """
    error_type = err.get("type", "")
    raw_msg = err.get("msg", "Validation error")

    # Custom validator messages are already human-readable
    if error_type == "value_error":
        return raw_msg.removeprefix("Value error, ")

    # Email validation
    if error_type == "value_error.email" or "email" in error_type:
        return "Invalid email format"

    # String length constraints
    if error_type == "string_too_short":
        ctx = err.get("ctx", {})
        min_length = ctx.get("min_length", "")
        return f"{field} must be at least {min_length} characters"

    if error_type == "string_too_long":
        ctx = err.get("ctx", {})
        max_length = ctx.get("max_length", "")
        return f"{field} must not exceed {max_length} characters"

    # Missing required field
    if error_type == "missing":
        return f"{field} is required"

    # Type errors
    if error_type.startswith("type_error") or error_type == "string_type":
        return f"{field} must be a valid string"

    if error_type == "list_type":
        return f"{field} must be a list"

    # Literal type (enum-like constraints)
    if error_type == "literal_error":
        ctx = err.get("ctx", {})
        expected = ctx.get("expected", "")
        return f"{field} must be one of: {expected}"

    # List length constraints
    if error_type == "too_short":
        ctx = err.get("ctx", {})
        min_length = ctx.get("min_length", "")
        return f"{field} must have at least {min_length} item(s)"

    # Fall back to Pydantic's message
    return raw_msg.removeprefix("Value error, ")


def _error_response(
    message: str, *, details: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Build a standardized 400 validation error response for API Gateway.

    Args:
        message: Top-level error message.
        details: Optional list of field-level error details.

    Returns:
        API Gateway Lambda proxy response dict with statusCode 400.
    """
    body: dict[str, Any] = {
        "error": "Validation Error",
        "message": message,
    }
    if details:
        body["details"] = details

    return {
        "statusCode": 400,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
