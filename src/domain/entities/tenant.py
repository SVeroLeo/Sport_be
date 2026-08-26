"""Tenant entity — represents an institution/organization in the multi-tenant system."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.value_objects.tenant_id import TenantId


class Tenant:
    """Domain entity representing a tenant (institution).

    Tenants are typically read from the database — this system does not
    create tenants, but validates their state during registration and
    other operations.
    """

    __slots__ = (
        "_allow_self_registration",
        "_created_at",
        "_default_account_type",
        "_name",
        "_plan",
        "_status",
        "_tenant_id",
    )
    _tenant_id: TenantId
    _name: str
    _plan: str | None
    _status: str
    _allow_self_registration: bool
    _default_account_type: str | None
    _created_at: datetime

    def __init__(
        self,
        *,
        tenant_id: TenantId,
        name: str,
        plan: str | None,
        status: str,
        allow_self_registration: bool,
        default_account_type: str | None,
        created_at: datetime,
    ) -> None:
        object.__setattr__(self, "_tenant_id", tenant_id)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_allow_self_registration", allow_self_registration)
        object.__setattr__(self, "_default_account_type", default_account_type)
        object.__setattr__(self, "_created_at", created_at)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def tenant_id(self) -> TenantId:
        return self._tenant_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def plan(self) -> str | None:
        return self._plan

    @property
    def status(self) -> str:
        return self._status

    @property
    def allow_self_registration(self) -> bool:
        return self._allow_self_registration

    @property
    def default_account_type(self) -> str | None:
        return self._default_account_type

    @property
    def created_at(self) -> datetime:
        return self._created_at

    # ── Domain Query Methods ────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """Check if the tenant status is active."""
        return self._status == "active"

    # ── Factory ─────────────────────────────────────────────────────────────

    @staticmethod
    def create(
        *,
        tenant_id: TenantId,
        name: str,
        plan: str | None = None,
        status: str = "active",
        allow_self_registration: bool = False,
        default_account_type: str | None = None,
        created_at: datetime | None = None,
    ) -> Tenant:
        """Create a Tenant entity from persisted data.

        This factory is primarily used when reconstructing a Tenant from
        the database. Validation is minimal since tenants are managed
        externally.
        """
        return Tenant(
            tenant_id=tenant_id,
            name=name,
            plan=plan,
            status=status,
            allow_self_registration=allow_self_registration,
            default_account_type=default_account_type,
            created_at=created_at or datetime.utcnow(),
        )

    # ── Equality ────────────────────────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tenant):
            return NotImplemented
        return self._tenant_id == other._tenant_id

    def __hash__(self) -> int:
        return hash(self._tenant_id)

    def __repr__(self) -> str:
        return (
            f"Tenant(tenant_id={self._tenant_id!r}, name={self._name!r}, "
            f"status={self._status!r}, allow_self_registration={self._allow_self_registration!r})"
        )
