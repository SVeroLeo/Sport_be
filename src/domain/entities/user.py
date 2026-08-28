"""User entity — represents a registered user in the system."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from domain.errors.validation_error import ValidationError
from domain.value_objects.email import Email
from domain.value_objects.full_name import FullName

UserStatus = Literal["active", "inactive", "suspended", "pending_confirmation"]

_VALID_STATUSES: set[str] = {"active", "inactive", "suspended", "pending_confirmation"}


class User:
    """Domain entity representing a system user.

    Users authenticate via Cognito and can belong to multiple tenants.
    The User record is independent of tenant membership.
    """

    __slots__ = (
        "_user_id",
        "_email",
        "_cognito_sub",
        "_full_name",
        "_default_tenant_id",
        "_status",
        "_created_at",
        "_updated_at",
    )

    _user_id: str
    _email: Email
    _cognito_sub: str
    _full_name: FullName
    _default_tenant_id: str | None
    _status: UserStatus
    _created_at: datetime
    _updated_at: datetime

    def __init__(
        self,
        user_id: str,
        email: Email,
        cognito_sub: str,
        full_name: FullName,
        status: UserStatus,
        created_at: datetime,
        updated_at: datetime,
        default_tenant_id: str | None = None,
    ) -> None:
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_email", email)
        object.__setattr__(self, "_cognito_sub", cognito_sub)
        object.__setattr__(self, "_full_name", full_name)
        object.__setattr__(self, "_default_tenant_id", default_tenant_id)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_created_at", created_at)
        object.__setattr__(self, "_updated_at", updated_at)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    # ──── Properties ──────────────────────────────────────────────────────────

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def email(self) -> Email:
        return self._email

    @property
    def cognito_sub(self) -> str:
        return self._cognito_sub

    @property
    def full_name(self) -> FullName:
        return self._full_name

    @property
    def default_tenant_id(self) -> str | None:
        """The user's default (active) tenant, resolved per-request after login.

        May be None until the user is associated with a tenant. The access token
        is tenant-agnostic; the AuthGuard resolves the active tenant from this value.
        """
        return self._default_tenant_id

    @property
    def status(self) -> UserStatus:
        return self._status

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ──── Factory Methods ─────────────────────────────────────────────────────

    @staticmethod
    def create(
        email: str,
        cognito_sub: str,
        full_name: str,
        status: str = "active",
        default_tenant_id: str | None = None,
    ) -> User:
        """Create a new User with generated user_id and timestamps.

        Args:
            email: Raw email string (will be validated).
            cognito_sub: The Cognito user sub identifier.
            full_name: Raw full name string (will be validated).
            status: Initial status. Defaults to "active".
            default_tenant_id: The user's default (active) tenant, if known at
                creation time (e.g. the tenant they self-register into). Optional.

        Returns:
            A validated User entity.

        Raises:
            ValidationError: If email, full_name, or status is invalid.
        """
        validated_email = Email.create(email)
        validated_full_name = FullName.create(full_name)

        if status not in _VALID_STATUSES:
            raise ValidationError(
                f"Invalid user status: '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
                field="status",
            )

        now = datetime.now(timezone.utc)

        return User(
            user_id=str(uuid.uuid4()),
            email=validated_email,
            cognito_sub=cognito_sub,
            full_name=validated_full_name,
            status=status,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
            default_tenant_id=default_tenant_id,
        )

    @staticmethod
    def reconstitute(
        user_id: str,
        email: str,
        cognito_sub: str,
        full_name: str,
        status: str,
        created_at: datetime,
        updated_at: datetime,
        default_tenant_id: str | None = None,
    ) -> User:
        """Reconstitute a User from persisted data (no validation of format).

        Used by repository mappers to rebuild entities from the data store.

        Args:
            user_id: Existing user UUID.
            email: Stored email value.
            cognito_sub: Stored Cognito sub.
            full_name: Stored full name.
            status: Stored status string.
            created_at: Original creation timestamp.
            updated_at: Last update timestamp.
            default_tenant_id: Stored default tenant id, if any. Optional.

        Returns:
            A User entity reconstituted from stored data.

        Raises:
            ValidationError: If status is not a recognized value.
        """
        if status not in _VALID_STATUSES:
            raise ValidationError(
                f"Invalid user status: '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
                field="status",
            )

        return User(
            user_id=user_id,
            email=Email(value=email),
            cognito_sub=cognito_sub,
            full_name=FullName(full_name),
            status=status,  # type: ignore[arg-type]
            created_at=created_at,
            updated_at=updated_at,
            default_tenant_id=default_tenant_id,
        )

    # ──── Status Transitions ──────────────────────────────────────────────────

    def activate(self) -> User:
        """Transition user to active status.

        Raises:
            ValidationError: If user is already active.
        """
        if self._status == "active":
            raise ValidationError("User is already active", field="status")
        return self._with_status("active")

    def deactivate(self) -> User:
        """Transition user to inactive status.

        Raises:
            ValidationError: If user is already inactive.
        """
        if self._status == "inactive":
            raise ValidationError("User is already inactive", field="status")
        return self._with_status("inactive")

    def suspend(self) -> User:
        """Transition user to suspended status.

        Raises:
            ValidationError: If user is already suspended.
        """
        if self._status == "suspended":
            raise ValidationError("User is already suspended", field="status")
        return self._with_status("suspended")

    def confirm(self) -> User:
        """Transition user from pending_confirmation to active.

        Raises:
            ValidationError: If user is not in pending_confirmation status.
        """
        if self._status != "pending_confirmation":
            raise ValidationError(
                "Only users with 'pending_confirmation' status can be confirmed",
                field="status",
            )
        return self._with_status("active")

    # ──── Internal Helpers ────────────────────────────────────────────────────

    def _with_status(self, new_status: UserStatus) -> User:
        """Return a new User instance with the given status and updated timestamp."""
        return User(
            user_id=self._user_id,
            email=self._email,
            cognito_sub=self._cognito_sub,
            full_name=self._full_name,
            status=new_status,
            created_at=self._created_at,
            updated_at=datetime.now(timezone.utc),
            default_tenant_id=self._default_tenant_id,
        )

    # ──── Domain Queries ──────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """Check if the user is in active status."""
        return self._status == "active"

    # ──── Equality & Representation ───────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, User):
            return NotImplemented
        return self._user_id == other._user_id

    def __hash__(self) -> int:
        return hash(self._user_id)

    def __repr__(self) -> str:
        return (
            f"User(user_id={self._user_id!r}, email={self._email!r}, "
            f"status={self._status!r})"
        )
