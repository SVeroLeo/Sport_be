"""Shared types for Application layer ports — filtering, pagination, and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class MemberFilters:
    """Filtering criteria for member queries.

    Attributes:
        account_type: Filter by account type name (case-insensitive match).
        status: Filter by member status (exact match).
    """

    account_type: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class PaginationParams:
    """Pagination parameters for paginated queries.

    Attributes:
        limit: Maximum number of items per page (1-100, default 20).
        cursor: Opaque cursor for the next page (None for first page).
    """

    limit: int = 20
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 100:
            object.__setattr__(self, "limit", max(1, min(100, self.limit)))


@dataclass(frozen=True)
class PaginatedResult(Generic[T]):
    """A page of results with optional cursor to the next page.

    Attributes:
        items: List of result items for the current page.
        next_cursor: Opaque cursor for retrieving the next page (None if no more pages).
    """

    items: list[T] = field(default_factory=list)
    next_cursor: str | None = None
