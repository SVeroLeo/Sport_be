"""CreateMemberRequest — HTTP request schema for admin-invited member creation.

Validates the incoming payload at the HTTP interface boundary
before mapping to the application-layer CreateMemberInputDTO.

Requirements: 11.1, 11.2
"""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class CreateMemberRequest(BaseModel):
    """HTTP request body for POST /members.

    Attributes:
        email: Member email, must be valid format and at most 254 chars.
        full_name: Member's full name, non-empty and at most 200 chars.
        account_type: Account type name to assign (non-empty).
        roles: List of role names to assign (at least 1, each must be admin|manager|viewer).
    """

    email: EmailStr = Field(max_length=254, description="Member email address")
    full_name: str = Field(
        min_length=1,
        max_length=200,
        description="Member's full name (1-200 characters)",
    )
    account_type: str = Field(
        min_length=1,
        description="Account type name to assign",
    )
    roles: list[Literal["admin", "manager", "viewer"]] = Field(
        min_length=1,
        description="Roles to assign (at least one of: admin, manager, viewer)",
    )

    @field_validator("full_name")
    @classmethod
    def validate_full_name_not_blank(cls, v: str) -> str:
        """Validate full_name is not just whitespace.

        Raises:
            ValueError: If full_name is effectively empty after stripping.
        """
        if not v.strip():
            raise ValueError("Full name must not be empty")
        return v.strip()

    @field_validator("account_type")
    @classmethod
    def validate_account_type_not_blank(cls, v: str) -> str:
        """Validate account_type is not just whitespace.

        Raises:
            ValueError: If account_type is effectively empty after stripping.
        """
        if not v.strip():
            raise ValueError("Account type must not be empty")
        return v.strip()
