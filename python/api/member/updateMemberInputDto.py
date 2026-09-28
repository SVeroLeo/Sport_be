"""DTO for updating a member."""

from typing import Any

from pydantic import BaseModel


class UpdateMemberInputDTO(BaseModel):
    """Input data for updating an existing member.

    All mutable fields are optional to support partial updates.
    Immutable fields (created_at, registration_type, invited_by) are not included.

    Attributes:
        tenant_id: The tenant owning the member.
        member_id: The ID of the member to update.
        account_type: New account type name.
        full_name: Updated full name.
        email: Updated email address.
        status: Updated status.
        metadata: Updated metadata dictionary.
    """

    tenant_id: str
    member_id: str
    account_type: str | None = None
    full_name: str | None = None
    email: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None
