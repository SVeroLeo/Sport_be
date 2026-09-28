"""DTO for account type output returned by use cases."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AccountTypeOutputDTO(BaseModel):
    """Output representation of an account type returned by use cases.

    Attributes:
        account_type_id: Unique identifier (UUID).
        tenant_id: Owning tenant identifier.
        name: Display name.
        description: Optional description text.
        config: Optional configuration dictionary.
        status: Current status (active/inactive).
        created_at: Timestamp of creation.
        updated_at: Timestamp of last update.
    """

    account_type_id: str
    tenant_id: str
    name: str
    description: str | None = None
    config: dict[str, Any] | None = None
    status: str
    created_at: datetime
    updated_at: datetime
