"""DTO for paginated member list responses."""

from pydantic import BaseModel

from application.dtos.member.member_output_dto import MemberOutputDTO


class PaginatedMembersDTO(BaseModel):
    """Paginated response containing a list of members.

    Attributes:
        items: List of member records for the current page.
        next_key: Opaque cursor for the next page, or None if no more results.
        total_count: Optional total count of matching records.
    """

    items: list[MemberOutputDTO]
    next_key: str | None = None
    total_count: int | None = None
