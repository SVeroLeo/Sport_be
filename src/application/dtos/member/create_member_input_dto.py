"""DTO for creating (inviting) a member."""

from pydantic import BaseModel, Field


class CreateMemberInputDTO(BaseModel):
    """Input data required to invite/create a new member in a tenant.

    Attributes:
        tenant_id: The tenant in which to create the member.
        email: Email address of the user to invite.
        full_name: Full name of the new member.
        account_type: Account type name to assign.
        roles: List of role names to assign (e.g. ["admin", "viewer"]).
    """

    tenant_id: str
    email: str
    full_name: str
    account_type: str
    roles: list[str] = Field(min_length=1)
