"""DTO for paginated account type list responses."""

from pydantic import BaseModel

from api.accountType.accountTypeOutputDto import AccountTypeOutputDTO


class PaginatedAccountTypesDTO(BaseModel):
    """Paginated response containing a list of account types.

    Attributes:
        items: List of account type records for the current page.
        next_key: Opaque cursor for the next page, or None if no more results.
        total_count: Optional total count of matching records.
    """

    items: list[AccountTypeOutputDTO]
    next_key: str | None = None
    total_count: int | None = None
