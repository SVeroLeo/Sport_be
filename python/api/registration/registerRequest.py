"""RegisterRequest — HTTP request schema for user self-registration.

Validates the incoming registration payload at the HTTP interface boundary
before mapping to the application-layer RegisterInputDTO.

Requirements: 11.1, 11.2, 11.3
"""

from pydantic import BaseModel, EmailStr, Field, field_validator

from api.common.errors.validationError import ValidationError as DomainValidationError
from api.common.tenant.tenantId import TenantId


class RegisterRequest(BaseModel):
    """HTTP request body for POST /auth/register.

    Attributes:
        email: User email, must be valid format and at most 254 chars.
        password: User password, between 8 and 72 characters.
        full_name: User's full name, non-empty and at most 200 chars.
        tenant_id: UUID of the tenant to register in.
        account_type: Optional account type name to assign.
    """

    email: EmailStr = Field(max_length=254, description="User email address")
    password: str = Field(
        min_length=8,
        max_length=72,
        description="User password (8-72 characters)",
    )
    full_name: str = Field(
        min_length=1,
        max_length=200,
        description="User's full name (1-200 characters)",
    )
    tenant_id: str = Field(description="Tenant UUID")
    account_type: str | None = Field(
        default=None,
        description="Optional account type to assign",
    )

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        """Validate tenant_id is a valid UUID format.

        Raises:
            ValueError: If tenant_id is empty or not a valid UUID.
        """
        try:
            result = TenantId.create(v)
        except DomainValidationError:
            raise ValueError("Invalid tenant ID") from None
        return str(result.value)

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
