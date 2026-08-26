"""Unit tests for TenantMembership entity."""

from datetime import UTC, datetime

import pytest

from domain.entities.tenant_membership import TenantMembership
from domain.errors.validation_error import ValidationError


class TestTenantMembershipCreate:
    """Tests for TenantMembership.create() factory method."""

    def test_create_with_valid_data(self) -> None:
        """Valid inputs produce an active TenantMembership."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        assert membership.user_id == "user-id-123"
        assert membership.tenant_id == "tenant-id-456"
        assert membership.status == "active"
        assert membership.joined_at is not None

    def test_create_sets_joined_at(self) -> None:
        """create() sets joined_at to the current time."""
        before = datetime.now(UTC)
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        after = datetime.now(UTC)
        assert before <= membership.joined_at <= after

    def test_create_trims_ids(self) -> None:
        """IDs are trimmed of whitespace."""
        membership = TenantMembership.create(
            user_id="  user-id-123  ",
            tenant_id="  tenant-id-456  ",
        )
        assert membership.user_id == "user-id-123"
        assert membership.tenant_id == "tenant-id-456"

    def test_create_with_empty_user_id_raises(self) -> None:
        """Empty user_id raises ValidationError."""
        with pytest.raises(ValidationError, match="User ID cannot be empty"):
            TenantMembership.create(
                user_id="",
                tenant_id="tenant-id-456",
            )

    def test_create_with_whitespace_user_id_raises(self) -> None:
        """Whitespace-only user_id raises ValidationError."""
        with pytest.raises(ValidationError, match="User ID cannot be empty"):
            TenantMembership.create(
                user_id="   ",
                tenant_id="tenant-id-456",
            )

    def test_create_with_empty_tenant_id_raises(self) -> None:
        """Empty tenant_id raises ValidationError."""
        with pytest.raises(ValidationError, match="Tenant ID cannot be empty"):
            TenantMembership.create(
                user_id="user-id-123",
                tenant_id="",
            )

    def test_create_with_whitespace_tenant_id_raises(self) -> None:
        """Whitespace-only tenant_id raises ValidationError."""
        with pytest.raises(ValidationError, match="Tenant ID cannot be empty"):
            TenantMembership.create(
                user_id="user-id-123",
                tenant_id="   ",
            )


class TestTenantMembershipReconstitute:
    """Tests for TenantMembership.reconstitute() method."""

    def test_reconstitute_valid(self) -> None:
        """Reconstitute builds a TenantMembership from persisted data."""
        now = datetime.now(UTC)
        membership = TenantMembership.reconstitute(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
            status="active",
            joined_at=now,
        )
        assert membership.user_id == "user-id-123"
        assert membership.tenant_id == "tenant-id-456"
        assert membership.status == "active"
        assert membership.joined_at == now

    def test_reconstitute_inactive(self) -> None:
        """Reconstitute supports inactive status."""
        now = datetime.now(UTC)
        membership = TenantMembership.reconstitute(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
            status="inactive",
            joined_at=now,
        )
        assert membership.status == "inactive"

    def test_reconstitute_invalid_status_raises(self) -> None:
        """Reconstitute rejects invalid status values."""
        with pytest.raises(ValidationError, match="Invalid membership status"):
            TenantMembership.reconstitute(
                user_id="user-id-123",
                tenant_id="tenant-id-456",
                status="deleted",
                joined_at=datetime.now(UTC),
            )


class TestTenantMembershipStatusTransitions:
    """Tests for TenantMembership status transitions."""

    def test_deactivate_active(self) -> None:
        """Active membership can be deactivated."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        deactivated = membership.deactivate()
        assert deactivated.status == "inactive"
        assert deactivated.user_id == membership.user_id
        assert deactivated.tenant_id == membership.tenant_id
        assert deactivated.joined_at == membership.joined_at

    def test_deactivate_already_inactive_raises(self) -> None:
        """Deactivating an already inactive membership raises ValidationError."""
        now = datetime.now(UTC)
        membership = TenantMembership.reconstitute(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
            status="inactive",
            joined_at=now,
        )
        with pytest.raises(ValidationError, match="Membership is already inactive"):
            membership.deactivate()

    def test_activate_inactive(self) -> None:
        """Inactive membership can be activated."""
        now = datetime.now(UTC)
        membership = TenantMembership.reconstitute(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
            status="inactive",
            joined_at=now,
        )
        activated = membership.activate()
        assert activated.status == "active"
        assert activated.user_id == membership.user_id
        assert activated.tenant_id == membership.tenant_id

    def test_activate_already_active_raises(self) -> None:
        """Activating an already active membership raises ValidationError."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        with pytest.raises(ValidationError, match="Membership is already active"):
            membership.activate()


class TestTenantMembershipIsActive:
    """Tests for TenantMembership.is_active property."""

    def test_is_active_when_active(self) -> None:
        """is_active returns True for active memberships."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        assert membership.is_active is True

    def test_is_not_active_when_inactive(self) -> None:
        """is_active returns False for inactive memberships."""
        now = datetime.now(UTC)
        membership = TenantMembership.reconstitute(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
            status="inactive",
            joined_at=now,
        )
        assert membership.is_active is False


class TestTenantMembershipImmutability:
    """Tests for TenantMembership immutability."""

    def test_cannot_set_attribute(self) -> None:
        """TenantMembership attributes cannot be set directly."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        with pytest.raises(AttributeError, match="Cannot modify immutable"):
            membership.status = "inactive"  # type: ignore[misc]

    def test_cannot_delete_attribute(self) -> None:
        """TenantMembership attributes cannot be deleted."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        with pytest.raises(AttributeError, match="Cannot modify immutable"):
            del membership.status  # type: ignore[misc]

    def test_transitions_return_new_instance(self) -> None:
        """Status transitions produce a new instance; original is unchanged."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        deactivated = membership.deactivate()
        assert membership.status == "active"
        assert deactivated.status == "inactive"
        assert membership is not deactivated


class TestTenantMembershipEquality:
    """Tests for TenantMembership equality and hashing."""

    def test_same_composite_key_are_equal(self) -> None:
        """TenantMemberships with same user_id and tenant_id are equal."""
        now = datetime.now(UTC)
        m1 = TenantMembership.reconstitute("uid-1", "tid-1", "active", now)
        m2 = TenantMembership.reconstitute("uid-1", "tid-1", "inactive", now)
        assert m1 == m2

    def test_different_keys_not_equal(self) -> None:
        """TenantMemberships with different composite keys are not equal."""
        now = datetime.now(UTC)
        m1 = TenantMembership.reconstitute("uid-1", "tid-1", "active", now)
        m2 = TenantMembership.reconstitute("uid-1", "tid-2", "active", now)
        assert m1 != m2

    def test_hash_consistent(self) -> None:
        """Equal TenantMemberships have the same hash."""
        now = datetime.now(UTC)
        m1 = TenantMembership.reconstitute("uid-1", "tid-1", "active", now)
        m2 = TenantMembership.reconstitute("uid-1", "tid-1", "inactive", now)
        assert hash(m1) == hash(m2)

    def test_not_equal_to_non_membership(self) -> None:
        """TenantMembership is not equal to a non-TenantMembership object."""
        membership = TenantMembership.create(
            user_id="user-id-123",
            tenant_id="tenant-id-456",
        )
        assert membership != "not-a-membership"
