"""DTO for updating an account type."""

from typing import Any

from pydantic import BaseModel


class UpdateAccountTypeInputDTO(BaseModel):
    """Input data for updating an existing account type.

    All fields are optional to support partial updates.

    Attributes:
        tenant_id: The tenant owning the account type.
        account_type_id: The ID of the account type to update.
        name: New name for the account type.
        description: New description.
        config: New configuration dictionary.
    """

    tenant_id: str
    account_type_id: str
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
