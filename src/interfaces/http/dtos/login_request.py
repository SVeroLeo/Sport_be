"""LoginRequest — HTTP request schema for user login.

Validates the incoming login payload at the HTTP interface boundary
before mapping to the application-layer LoginInputDTO.

Requirements: 11.1, 11.3
"""

from pydantic import BaseModel, EmailStr, Field, field_validator

from domain.errors.validation_error import ValidationError as DomainValidationError
from domain.value_objects.tenant_id import TenantId


class LoginRequest(BaseModel):
    """HTTP request body for POST /auth/login.

    Attributes:
        email: User email, must be valid format and at most 254 chars.
        password: User password, between 8 and 72 characters.
        tenant_id: UUID of the tenant the user is logging into.
    """

    email: EmailStr = Field(max_length=254, description="User email address")
    password: str = Field(
        min_length=8,
        max_length=72,
        description="User password (8-72 characters)",
    )
    tenant_id: str = Field(description="Tenant UUID")

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
