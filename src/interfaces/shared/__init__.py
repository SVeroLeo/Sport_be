"""Shared interface utilities — error handling and response building."""

from interfaces.shared.error_handler import handle_error
from interfaces.shared.response_builder import (
    error_response,
    no_content_response,
    success_response,
)

__all__ = [
    "error_response",
    "handle_error",
    "no_content_response",
    "success_response",
]
