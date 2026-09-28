"""CreateAccountTypeRequest — HTTP request schema for creating an account type.

Validates the incoming payload at the HTTP interface boundary
before mapping to the application-layer CreateAccountTypeInputDTO.

Requirements: 5.3
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CreateAccountTypeRequest(BaseModel):
    """HTTP request body for POST /account-types.

    Attributes:
        name: Account type name, non-empty and at most 100 chars.
        description: Optional description of the account type.
        config: Optional configuration dictionary.
    """

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Account type name (1-100 characters)",
    )
    description: str | None = Field(
        default=None,
        description="Optional description",
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="Optional configuration dictionary",
    )

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: str) -> str:
        """Validate name is not just whitespace.

        Raises:
            ValueError: If name is effectively empty after stripping.
        """
        if not v.strip():
            raise ValueError("Name must not be empty")
        return v.strip()
