"""Centralized error handler for mapping domain errors to HTTP responses.

Accepts any exception and produces a standardized API Gateway Lambda proxy
response with the appropriate HTTP status code.
"""

from __future__ import annotations

import logging
from typing import Any

from domain.errors.conflict_error import ConflictError
from domain.errors.domain_error import DomainError
from domain.errors.forbidden_error import ForbiddenError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.errors.not_found_error import NotFoundError
from domain.errors.tenant_not_found_error import TenantNotFoundError
from domain.errors.validation_error import ValidationError
from interfaces.shared.response_builder import error_response

logger = logging.getLogger(__name__)


def handle_error(error: Exception) -> dict[str, Any]:
    """Map an exception to an API Gateway error response.

    Maps domain error subclasses to their corresponding HTTP status codes:
    - ValidationError -> 400
    - InvalidCredentialsError -> 401
    - ForbiddenError -> 403
    - NotFoundError -> 404
    - TenantNotFoundError -> 404
    - ConflictError -> 409
    - DomainError (generic) -> 400
    - Unknown exceptions -> 500

    Args:
        error: The exception to handle.

    Returns:
        API Gateway Lambda proxy response dict with appropriate status code.
    """
    if isinstance(error, ValidationError):
        return error_response(400, error.message)

    if isinstance(error, InvalidCredentialsError):
        return error_response(401, error.message)

    if isinstance(error, ForbiddenError):
        return error_response(403, error.message)

    if isinstance(error, TenantNotFoundError):
        return error_response(404, error.message)

    if isinstance(error, NotFoundError):
        return error_response(404, error.message)

    if isinstance(error, ConflictError):
        return error_response(409, error.message)

    if isinstance(error, DomainError):
        return error_response(400, error.message)

    # Unknown/unexpected errors — log and return generic 500
    logger.exception("Unexpected error: %s", error)
    return error_response(500, "Internal server error")
