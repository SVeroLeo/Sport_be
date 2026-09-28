"""TenantMembership entity — links a User to a Tenant."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from api.common.errors.validationError import ValidationError

MembershipStatus = Literal["active", "inactive"]

_VALID_STATUSES: frozenset[str] = frozenset({"active", "inactive"})


class TenantMembership:
    """Domain entity representing the relationship between a User and a Tenant.

    This is the many-to-many join entity that tracks which tenants a user
    belongs to and the status of that membership.
    """

    __slots__ = (
        "_joined_at",
        "_status",
        "_tenant_id",
        "_user_id",
    )

    _user_id: str
    _tenant_id: str
    _status: MembershipStatus
    _joined_at: datetime

    def __init__(
        self,
        user_id: str,
        tenant_id: str,
        status: MembershipStatus,
        joined_at: datetime,
    ) -> None:
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_tenant_id", tenant_id)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_joined_at", joined_at)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    # ──── Properties ──────────────────────────────────────────────────────────

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def status(self) -> MembershipStatus:
        return self._status

    @property
    def joined_at(self) -> datetime:
        return self._joined_at

    @property
    def is_active(self) -> bool:
        """Check if the membership is currently active."""
        return self._status == "active"

    # ──── Factory Methods ─────────────────────────────────────────────────────

    @staticmethod
    def create(user_id: str, tenant_id: str) -> TenantMembership:
        """Create a new TenantMembership with status 'active' and joined_at = now.

        Args:
            user_id: UUID of the user.
            tenant_id: UUID of the tenant.

        Returns:
            A new active TenantMembership entity.

        Raises:
            ValidationError: If user_id or tenant_id is empty.
        """
        if not user_id or not user_id.strip():
            raise ValidationError("User ID cannot be empty", field="user_id")
        if not tenant_id or not tenant_id.strip():
            raise ValidationError("Tenant ID cannot be empty", field="tenant_id")

        return TenantMembership(
            user_id=user_id.strip(),
            tenant_id=tenant_id.strip(),
            status="active",
            joined_at=datetime.now(UTC),
        )

    @staticmethod
    def reconstitute(
        user_id: str,
        tenant_id: str,
        status: str,
        joined_at: datetime,
    ) -> TenantMembership:
        """Reconstitute a TenantMembership from persisted data.

        Used by repository mappers to rebuild entities from the data store.

        Args:
            user_id: Stored user UUID.
            tenant_id: Stored tenant UUID.
            status: Stored status string.
            joined_at: Original join timestamp.

        Returns:
            A TenantMembership entity reconstituted from stored data.

        Raises:
            ValidationError: If status is not a recognized value.
        """
        if status not in _VALID_STATUSES:
            raise ValidationError(
                f"Invalid membership status: '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
                field="status",
            )

        return TenantMembership(
            user_id=user_id,
            tenant_id=tenant_id,
            status=status,  # type: ignore[arg-type]
            joined_at=joined_at,
        )

    # ──── Status Transitions ──────────────────────────────────────────────────

    def deactivate(self) -> TenantMembership:
        """Deactivate this membership.

        Returns:
            A new TenantMembership with status set to "inactive".

        Raises:
            ValidationError: If already inactive.
        """
        if self._status == "inactive":
            raise ValidationError("Membership is already inactive", field="status")
        return TenantMembership(
            user_id=self._user_id,
            tenant_id=self._tenant_id,
            status="inactive",
            joined_at=self._joined_at,
        )

    def activate(self) -> TenantMembership:
        """Activate this membership.

        Returns:
            A new TenantMembership with status set to "active".

        Raises:
            ValidationError: If already active.
        """
        if self._status == "active":
            raise ValidationError("Membership is already active", field="status")
        return TenantMembership(
            user_id=self._user_id,
            tenant_id=self._tenant_id,
            status="active",
            joined_at=self._joined_at,
        )

    # ──── Equality & Representation ───────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TenantMembership):
            return NotImplemented
        return self._user_id == other._user_id and self._tenant_id == other._tenant_id

    def __hash__(self) -> int:
        return hash((self._user_id, self._tenant_id))

    def __repr__(self) -> str:
        return (
            f"TenantMembership(user_id={self._user_id!r}, "
            f"tenant_id={self._tenant_id!r}, "
            f"status={self._status!r})"
        )
