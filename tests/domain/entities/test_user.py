"""Unit tests for User entity."""

from datetime import datetime, timezone

import pytest

from domain.entities.user import User
from domain.errors.validation_error import ValidationError


class TestUserCreate:
    """Tests for User.create() factory method."""

    def test_create_with_valid_data(self) -> None:
        """Valid inputs produce a User entity with active status."""
        user = User.create(
            email="test@example.com",
            cognito_sub="cognito-sub-123",
            full_name="John Doe",
        )
        assert user.email.value == "test@example.com"
        assert user.cognito_sub == "cognito-sub-123"
        assert user.full_name.value == "John Doe"
        assert user.status == "active"
        assert user.user_id is not None
        assert len(user.user_id) == 36  # UUID format

    def test_create_generates_unique_user_ids(self) -> None:
        """Each call to create() generates a unique user_id."""
        user1 = User.create(
            email="a@example.com",
            cognito_sub="sub-1",
            full_name="User One",
        )
        user2 = User.create(
            email="b@example.com",
            cognito_sub="sub-2",
            full_name="User Two",
        )
        assert user1.user_id != user2.user_id

    def test_create_sets_timestamps(self) -> None:
        """create() sets created_at and updated_at to the current time."""
        before = datetime.now(timezone.utc)
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="Jane Doe",
        )
        after = datetime.now(timezone.utc)
        assert before <= user.created_at <= after
        assert user.created_at == user.updated_at

    def test_create_with_pending_confirmation_status(self) -> None:
        """Can create a user with pending_confirmation status (admin invite)."""
        user = User.create(
            email="invited@example.com",
            cognito_sub="sub-456",
            full_name="Invited User",
            status="pending_confirmation",
        )
        assert user.status == "pending_confirmation"

    def test_create_with_invalid_email_raises_validation_error(self) -> None:
        """Invalid email raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid email format"):
            User.create(
                email="not-an-email",
                cognito_sub="sub-123",
                full_name="John Doe",
            )

    def test_create_with_empty_full_name_raises_validation_error(self) -> None:
        """Empty full name raises ValidationError."""
        with pytest.raises(ValidationError, match="Full name cannot be empty"):
            User.create(
                email="test@example.com",
                cognito_sub="sub-123",
                full_name="",
            )

    def test_create_with_invalid_status_raises_validation_error(self) -> None:
        """Invalid status raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid user status"):
            User.create(
                email="test@example.com",
                cognito_sub="sub-123",
                full_name="John Doe",
                status="invalid_status",
            )

    def test_create_normalizes_email(self) -> None:
        """Email is trimmed and lowercased."""
        user = User.create(
            email="  Test@Example.COM  ",
            cognito_sub="sub-123",
            full_name="John Doe",
        )
        assert user.email.value == "test@example.com"

    def test_create_trims_full_name(self) -> None:
        """Full name is trimmed."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="  John Doe  ",
        )
        assert user.full_name.value == "John Doe"


class TestUserReconstitute:
    """Tests for User.reconstitute() method."""

    def test_reconstitute_with_valid_data(self) -> None:
        """Reconstitute builds a User from persisted data."""
        now = datetime.now(timezone.utc)
        user = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="test@example.com",
            cognito_sub="cognito-sub-abc",
            full_name="Stored User",
            status="active",
            created_at=now,
            updated_at=now,
        )
        assert user.user_id == "550e8400-e29b-41d4-a716-446655440000"
        assert user.email.value == "test@example.com"
        assert user.cognito_sub == "cognito-sub-abc"
        assert user.full_name.value == "Stored User"
        assert user.status == "active"
        assert user.created_at == now
        assert user.updated_at == now

    def test_reconstitute_with_invalid_status_raises(self) -> None:
        """Reconstitute rejects invalid status values."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError, match="Invalid user status"):
            User.reconstitute(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                email="test@example.com",
                cognito_sub="sub-123",
                full_name="User",
                status="deleted",
                created_at=now,
                updated_at=now,
            )


class TestUserStatusTransitions:
    """Tests for User status transition methods."""

    def test_activate_from_inactive(self) -> None:
        """Inactive user can be activated."""
        now = datetime.now(timezone.utc)
        user = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="inactive",
            created_at=now,
            updated_at=now,
        )
        activated = user.activate()
        assert activated.status == "active"
        assert activated.user_id == user.user_id
        assert activated.created_at == user.created_at
        assert activated.updated_at >= user.updated_at

    def test_activate_already_active_raises(self) -> None:
        """Activating an already active user raises ValidationError."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="active",
        )
        with pytest.raises(ValidationError, match="User is already active"):
            user.activate()

    def test_deactivate_from_active(self) -> None:
        """Active user can be deactivated."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="active",
        )
        deactivated = user.deactivate()
        assert deactivated.status == "inactive"
        assert deactivated.user_id == user.user_id
        assert deactivated.created_at == user.created_at

    def test_deactivate_already_inactive_raises(self) -> None:
        """Deactivating an already inactive user raises ValidationError."""
        now = datetime.now(timezone.utc)
        user = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="inactive",
            created_at=now,
            updated_at=now,
        )
        with pytest.raises(ValidationError, match="User is already inactive"):
            user.deactivate()

    def test_suspend_from_active(self) -> None:
        """Active user can be suspended."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="active",
        )
        suspended = user.suspend()
        assert suspended.status == "suspended"

    def test_suspend_already_suspended_raises(self) -> None:
        """Suspending an already suspended user raises ValidationError."""
        now = datetime.now(timezone.utc)
        user = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="suspended",
            created_at=now,
            updated_at=now,
        )
        with pytest.raises(ValidationError, match="User is already suspended"):
            user.suspend()

    def test_confirm_from_pending(self) -> None:
        """User in pending_confirmation can be confirmed to active."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="pending_confirmation",
        )
        confirmed = user.confirm()
        assert confirmed.status == "active"

    def test_confirm_from_non_pending_raises(self) -> None:
        """Confirming a user not in pending_confirmation raises ValidationError."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="active",
        )
        with pytest.raises(ValidationError, match="pending_confirmation"):
            user.confirm()


class TestUserImmutability:
    """Tests for User immutability."""

    def test_cannot_set_attribute(self) -> None:
        """User attributes cannot be set directly."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
        )
        with pytest.raises(AttributeError, match="Cannot modify immutable"):
            user.status = "inactive"  # type: ignore[misc]

    def test_cannot_delete_attribute(self) -> None:
        """User attributes cannot be deleted."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
        )
        with pytest.raises(AttributeError, match="Cannot modify immutable"):
            del user.status  # type: ignore[misc]

    def test_status_transitions_return_new_instance(self) -> None:
        """Status transitions produce a new User; original is unchanged."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="pending_confirmation",
        )
        confirmed = user.confirm()
        assert user.status == "pending_confirmation"
        assert confirmed.status == "active"
        assert user is not confirmed


class TestUserEquality:
    """Tests for User equality and hashing."""

    def test_users_with_same_id_are_equal(self) -> None:
        """Two User instances with the same user_id are equal."""
        now = datetime.now(timezone.utc)
        user1 = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="active",
            created_at=now,
            updated_at=now,
        )
        user2 = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="different@example.com",
            cognito_sub="sub-456",
            full_name="Different",
            status="inactive",
            created_at=now,
            updated_at=now,
        )
        assert user1 == user2

    def test_users_with_different_ids_are_not_equal(self) -> None:
        """Users with different user_ids are not equal."""
        user1 = User.create(
            email="test@example.com",
            cognito_sub="sub-1",
            full_name="User",
        )
        user2 = User.create(
            email="test@example.com",
            cognito_sub="sub-2",
            full_name="User",
        )
        assert user1 != user2

    def test_user_not_equal_to_non_user(self) -> None:
        """User is not equal to a non-User object."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
        )
        assert user != "not-a-user"

    def test_hash_consistent_for_same_id(self) -> None:
        """Users with the same user_id have the same hash."""
        now = datetime.now(timezone.utc)
        user1 = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="a@example.com",
            cognito_sub="sub-1",
            full_name="User A",
            status="active",
            created_at=now,
            updated_at=now,
        )
        user2 = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="b@example.com",
            cognito_sub="sub-2",
            full_name="User B",
            status="inactive",
            created_at=now,
            updated_at=now,
        )
        assert hash(user1) == hash(user2)


class TestUserIsActive:
    """Tests for User.is_active property."""

    def test_is_active_when_active(self) -> None:
        """is_active returns True for active users."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="active",
        )
        assert user.is_active is True

    def test_is_not_active_when_pending(self) -> None:
        """is_active returns False for pending_confirmation users."""
        user = User.create(
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="pending_confirmation",
        )
        assert user.is_active is False

    def test_is_not_active_when_inactive(self) -> None:
        """is_active returns False for inactive users."""
        now = datetime.now(timezone.utc)
        user = User.reconstitute(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="test@example.com",
            cognito_sub="sub-123",
            full_name="User",
            status="inactive",
            created_at=now,
            updated_at=now,
        )
        assert user.is_active is False
