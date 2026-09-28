"""Member entity — represents a person registered within a tenant."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from api.common.errors.validationError import ValidationError
from api.accountType.accountTypeId import AccountTypeId
from api.common.valueObjects.email import Email
from api.member.fullName import FullName
from api.member.memberId import MemberId
from api.common.tenant.tenantId import TenantId

_VALID_STATUSES = frozenset({"active", "inactive", "pending_confirmation"})
_VALID_REGISTRATION_TYPES = frozenset({"self", "invited", "social"})


class Member:
    """Domain entity representing a member within a tenant.

    A member is a person registered in a specific tenant with an assigned
    account type. Members can be created via self-registration or admin
    invitation.

    Immutable fields (preserved on update): created_at, registration_type, invited_by.
    """

    __slots__ = (
        "_account_type",
        "_account_type_id",
        "_created_at",
        "_email",
        "_full_name",
        "_invited_by",
        "_member_id",
        "_metadata",
        "_registration_type",
        "_status",
        "_tenant_id",
        "_updated_at",
        "_user_id",
    )

    def __init__(
        self,
        member_id: str,
        tenant_id: str,
        user_id: str,
        account_type: str,
        account_type_id: str,
        full_name: str,
        email: str,
        status: str,
        registration_type: str,
        invited_by: str | None,
        metadata: dict[str, Any] | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        object.__setattr__(self, "_member_id", member_id)
        object.__setattr__(self, "_tenant_id", tenant_id)
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_account_type", account_type)
        object.__setattr__(self, "_account_type_id", account_type_id)
        object.__setattr__(self, "_full_name", full_name)
        object.__setattr__(self, "_email", email)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_registration_type", registration_type)
        object.__setattr__(self, "_invited_by", invited_by)
        object.__setattr__(self, "_metadata", metadata)
        object.__setattr__(self, "_created_at", created_at)
        object.__setattr__(self, "_updated_at", updated_at)

    # ─── Properties ───────────────────────────────────────────────────────────

    @property
    def member_id(self) -> str:
        return self._member_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def account_type(self) -> str:
        return self._account_type

    @property
    def account_type_id(self) -> str:
        return self._account_type_id

    @property
    def full_name(self) -> str:
        return self._full_name

    @property
    def email(self) -> str:
        return self._email

    @property
    def status(self) -> str:
        return self._status

    @property
    def registration_type(self) -> str:
        return self._registration_type

    @property
    def invited_by(self) -> str | None:
        return self._invited_by

    @property
    def metadata(self) -> dict[str, Any] | None:
        return self._metadata

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ─── Factory Method ───────────────────────────────────────────────────────

    @staticmethod
    def create(
        tenant_id: str,
        user_id: str,
        account_type: str,
        account_type_id: str,
        full_name: str,
        email: str,
        registration_type: str,
        invited_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "active",
    ) -> Member:
        """Create a new Member entity with validation.

        Generates a new member_id and sets created_at/updated_at to now.

        Args:
            tenant_id: UUID of the tenant this member belongs to.
            user_id: UUID of the associated user.
            account_type: Name of the account type (e.g., "socio", "usuario").
            account_type_id: UUID of the account type record.
            full_name: Member's full name.
            email: Member's email address.
            registration_type: Either "self" or "invited".
            invited_by: User ID of the admin who invited (required if registration_type is "invited").
            metadata: Optional additional metadata dictionary.
            status: Initial status (defaults to "active").

        Returns:
            A validated Member entity.

        Raises:
            ValidationError: If any field fails validation.
        """
        # Validate value objects (these raise ValidationError on failure)
        validated_tenant_id = TenantId.create(tenant_id)
        validated_member_id = MemberId.generate()
        validated_account_type_id = AccountTypeId.create(account_type_id)
        validated_full_name = FullName.create(full_name)
        validated_email = Email.create(email)

        # Validate user_id as non-empty
        if not user_id or not user_id.strip():
            raise ValidationError("User ID cannot be empty", field="user_id")

        # Validate account_type name
        if not account_type or not account_type.strip():
            raise ValidationError("Account type cannot be empty", field="account_type")

        # Validate status
        if status not in _VALID_STATUSES:
            raise ValidationError(
                f"Invalid member status: must be one of {sorted(_VALID_STATUSES)}",
                field="status",
            )

        # Validate registration_type
        if registration_type not in _VALID_REGISTRATION_TYPES:
            raise ValidationError(
                f"Invalid registration type: must be one of {sorted(_VALID_REGISTRATION_TYPES)}",
                field="registration_type",
            )

        # Validate invited_by is provided when registration_type is "invited"
        if registration_type == "invited" and (not invited_by or not invited_by.strip()):
            raise ValidationError(
                "invited_by is required when registration type is 'invited'",
                field="invited_by",
            )

        now = datetime.now(UTC)

        return Member(
            member_id=validated_member_id.value,
            tenant_id=validated_tenant_id.value,
            user_id=user_id.strip(),
            account_type=account_type.strip(),
            account_type_id=validated_account_type_id.value,
            full_name=validated_full_name.value,
            email=validated_email.value,
            status=status,
            registration_type=registration_type,
            invited_by=invited_by.strip() if invited_by else None,
            metadata=metadata,
            created_at=now,
            updated_at=now,
        )

    # ─── Reconstitution ──────────────────────────────────────────────────────

    @staticmethod
    def reconstitute(
        member_id: str,
        tenant_id: str,
        user_id: str,
        account_type: str,
        account_type_id: str,
        full_name: str,
        email: str,
        status: str,
        registration_type: str,
        invited_by: str | None,
        metadata: dict[str, Any] | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> Member:
        """Reconstitute a Member entity from persisted data (no validation).

        Use this method when loading from the database where data is already
        known to be valid.
        """
        return Member(
            member_id=member_id,
            tenant_id=tenant_id,
            user_id=user_id,
            account_type=account_type,
            account_type_id=account_type_id,
            full_name=full_name,
            email=email,
            status=status,
            registration_type=registration_type,
            invited_by=invited_by,
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
        )

    # ─── Update Method ────────────────────────────────────────────────────────

    def update(
        self,
        account_type: str | None = None,
        account_type_id: str | None = None,
        full_name: str | None = None,
        email: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Member:
        """Create a new Member with updated fields, preserving immutable fields.

        Immutable fields preserved: member_id, tenant_id, user_id,
        created_at, registration_type, invited_by.

        Args:
            account_type: New account type name (optional).
            account_type_id: New account type ID (optional).
            full_name: New full name (optional).
            email: New email (optional).
            status: New status (optional).
            metadata: New metadata (optional, pass explicitly to change).

        Returns:
            A new Member entity with the updates applied.

        Raises:
            ValidationError: If any updated field fails validation.
        """
        new_account_type = self._account_type
        new_account_type_id = self._account_type_id
        new_full_name = self._full_name
        new_email = self._email
        new_status = self._status
        new_metadata = self._metadata

        if account_type is not None:
            if not account_type.strip():
                raise ValidationError("Account type cannot be empty", field="account_type")
            new_account_type = account_type.strip()

        if account_type_id is not None:
            validated_id = AccountTypeId.create(account_type_id)
            new_account_type_id = validated_id.value

        if full_name is not None:
            validated_name = FullName.create(full_name)
            new_full_name = validated_name.value

        if email is not None:
            validated_email = Email.create(email)
            new_email = validated_email.value

        if status is not None:
            if status not in _VALID_STATUSES:
                raise ValidationError(
                    f"Invalid member status: must be one of {sorted(_VALID_STATUSES)}",
                    field="status",
                )
            new_status = status

        if metadata is not None:
            new_metadata = metadata

        now = datetime.now(UTC)

        return Member(
            member_id=self._member_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            account_type=new_account_type,
            account_type_id=new_account_type_id,
            full_name=new_full_name,
            email=new_email,
            status=new_status,
            registration_type=self._registration_type,
            invited_by=self._invited_by,
            metadata=new_metadata,
            created_at=self._created_at,
            updated_at=now,
        )

    # ─── Deactivation ────────────────────────────────────────────────────────

    def deactivate(self) -> Member:
        """Deactivate this member, setting status to 'inactive'.

        Returns:
            A new Member entity with status set to "inactive".

        Raises:
            ValidationError: If the member is already inactive.
        """
        if self._status == "inactive":
            raise ValidationError("Member is already inactive", field="status")
        return self.update(status="inactive")

    # ─── Equality ─────────────────────────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Member):
            return NotImplemented
        return self._member_id == other._member_id

    def __hash__(self) -> int:
        return hash(self._member_id)

    def __repr__(self) -> str:
        return (
            f"Member(member_id={self._member_id!r}, "
            f"tenant_id={self._tenant_id!r}, "
            f"email={self._email!r}, "
            f"status={self._status!r})"
        )
