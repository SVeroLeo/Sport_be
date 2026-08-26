"""Shared pagination DTOs for paginated queries."""

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Input parameters for paginated queries.

    Attributes:
        limit: Maximum number of items per page (1-100, default 20).
        next_key: Opaque cursor for fetching the next page of results.
    """

    limit: int = Field(default=20, ge=1, le=100)
    next_key: str | None = None
