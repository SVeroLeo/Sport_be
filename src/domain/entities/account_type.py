"""AccountType entity — classification of members within a tenant."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from domain.errors.validation_error import ValidationError
from domain.value_objects.account_type_id import AccountTypeId
from domain.value_objects.tenant_id import TenantId

ACCOUNT_TYPE_NAME_MAX_LENGTH = 100
VALID_STATUSES = ("active", "inactive")


class AccountType:
    """Domain entity representing an account type within a tenant.

    Account types classify members (e.g., socio, usuario, profesional).
    Each tenant manages its own set of account types independently.
    """

    def __init__(
        self,
        account_type_id: str,
        tenant_id: str,
        name: str,
        description: str | None,
        config: dict[str, Any] | None,
        status: str,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.account_type_id = account_type_id
        self.tenant_id = tenant_id
        self.name = name
        self.description = description
        self.config = config
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    @staticmethod
    def create(
        tenant_id: str,
        name: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> AccountType:
        """Create a new AccountType with validation.

        Generates a new UUID, validates the name, sets status to "active",
        and initializes timestamps.

        Args:
            tenant_id: The tenant this account type belongs to (UUID string).
            name: The display name (non-empty, max 100 chars).
            description: Optional description text.
            config: Optional flexible configuration dictionary.

        Returns:
            A new AccountType instance.

        Raises:
            ValidationError: If name is empty or exceeds 100 characters.
        """
        AccountType._validate_name(name)

        # Validate tenant_id format via value object
        TenantId.create(tenant_id)

        now = datetime.now(timezone.utc)
        generated_id = AccountTypeId.generate()

        return AccountType(
            account_type_id=generated_id.value,
            tenant_id=tenant_id,
            name=name.strip(),
            description=description,
            config=config,
            status="active",
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def reconstitute(
        account_type_id: str,
        tenant_id: str,
        name: str,
        description: str | None,
        config: dict[str, Any] | None,
        status: str,
        created_at: datetime,
        updated_at: datetime,
    ) -> AccountType:
        """Reconstitute an AccountType from persisted data (no validation).

        Used by repository mappers to rebuild entities from storage.
        """
        return AccountType(
            account_type_id=account_type_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            config=config,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

    def update_name(self, name: str) -> None:
        """Update the account type name with validation.

        Args:
            name: The new name (non-empty, max 100 chars).

        Raises:
            ValidationError: If name is empty or exceeds 100 characters.
        """
        AccountType._validate_name(name)
        self.name = name.strip()
        self._refresh_updated_at()

    def update_description(self, description: str | None) -> None:
        """Update the account type description."""
        self.description = description
        self._refresh_updated_at()

    def update_config(self, config: dict[str, Any] | None) -> None:
        """Update the account type configuration."""
        self.config = config
        self._refresh_updated_at()

    def deactivate(self) -> None:
        """Set the account type status to inactive (soft delete)."""
        self.status = "inactive"
        self._refresh_updated_at()

    def activate(self) -> None:
        """Set the account type status to active."""
        self.status = "active"
        self._refresh_updated_at()

    @property
    def is_active(self) -> bool:
        """Check if the account type is active."""
        return self.status == "active"

    def _refresh_updated_at(self) -> None:
        """Update the updated_at timestamp to the current time."""
        self.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _validate_name(name: str) -> None:
        """Validate account type name constraints.

        Args:
            name: The name to validate.

        Raises:
            ValidationError: If name is empty or exceeds 100 characters.
        """
        if not name or not name.strip():
            raise ValidationError(
                "Account type name cannot be empty",
                field="name",
            )
        if len(name.strip()) > ACCOUNT_TYPE_NAME_MAX_LENGTH:
            raise ValidationError(
                f"Account type name cannot exceed {ACCOUNT_TYPE_NAME_MAX_LENGTH} characters",
                field="name",
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AccountType):
            return NotImplemented
        return self.account_type_id == other.account_type_id

    def __hash__(self) -> int:
        return hash(self.account_type_id)

    def __repr__(self) -> str:
        return (
            f"AccountType(id={self.account_type_id!r}, "
            f"tenant_id={self.tenant_id!r}, "
            f"name={self.name!r}, "
            f"status={self.status!r})"
        )
