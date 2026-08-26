"""DTO for member output returned by use cases."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MemberOutputDTO(BaseModel):
    """Output representation of a member returned by use cases.

    Attributes:
        member_id: Unique identifier.
        tenant_id: Owning tenant identifier.
        user_id: Associated user identifier.
        account_type: Account type name.
        account_type_id: Account type identifier.
        full_name: Full name of the member.
        email: Email address.
        status: Current status (active/inactive/pending_confirmation).
        registration_type: How the member was created (self/invited).
        invited_by: User ID of the inviter, if applicable.
        metadata: Optional additional metadata.
        created_at: Timestamp of creation.
        updated_at: Timestamp of last update.
    """

    member_id: str
    tenant_id: str
    user_id: str
    account_type: str
    account_type_id: str
    full_name: str
    email: str
    status: str
    registration_type: str
    invited_by: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
