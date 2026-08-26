"""DTO for creating an account type."""

from typing import Any

from pydantic import BaseModel


class CreateAccountTypeInputDTO(BaseModel):
    """Input data required to create a new account type.

    Attributes:
        tenant_id: The tenant in which to create the account type.
        name: Display name for the account type (max 100 chars).
        description: Optional description of the account type.
        config: Optional configuration dictionary.
    """

    tenant_id: str
    name: str
    description: str | None = None
    config: dict[str, Any] | None = None
