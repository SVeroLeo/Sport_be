"""API response schemas — generic wrappers for HTTP responses.

Provides standardized response formats for success, error, and paginated responses.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API success response wrapper.

    Attributes:
        data: The response payload.
        message: Optional success message.
    """

    data: Any = Field(description="Response payload")
    message: str | None = Field(default=None, description="Optional success message")


class ApiErrorResponse(BaseModel):
    """Standard API error response format.

    Attributes:
        error: Short error type identifier.
        message: Human-readable error message.
        details: Optional list of field-level validation errors.
    """

    error: str = Field(description="Error type identifier")
    message: str = Field(description="Human-readable error message")
    details: list[dict[str, Any]] | None = Field(
        default=None,
        description="Field-level validation error details",
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response wrapper.

    Attributes:
        items: List of items in the current page.
        next_key: Opaque cursor for the next page, or None if no more pages.
        count: Number of items in the current page.
    """

    items: list[Any] = Field(description="Items in the current page")
    next_key: str | None = Field(
        default=None,
        description="Pagination cursor for the next page",
    )
    count: int = Field(description="Number of items in the current page")
