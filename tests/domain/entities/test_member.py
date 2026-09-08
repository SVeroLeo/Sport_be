"""Unit tests for Member entity."""

from datetime import UTC, datetime

import pytest

from domain.entities.member import Member
from domain.errors.validation_error import ValidationError


# ─── Valid test data ──────────────────────────────────────────────────────────

VALID_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
VALID_USER_ID = "660e8400-e29b-41d4-a716-446655440000"
VALID_ACCOUNT_TYPE_ID = "770e8400-e29b-41d4-a716-446655440000"


class TestMemberCreate:
    """Tests for Member.create() factory method."""

    def test_create_with_valid_data(self) -> None:
        """Valid inputs produce a Member entity with active status."""
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="John Doe",
            email="john@example.com",
            registration_type="self",
        )
        assert member.tenant_id == VALID_TENANT_ID
        assert member.user_id == VALID_USER_ID
        assert member.account_type == "socio"
        assert member.full_name == "John Doe"
        assert member.email == "john@example.com"
        assert member.status == "active"
        assert member.registration_type == "self"
        assert member.invited_by is None
        assert member.metadata is None
        assert member.member_id is not None
        assert len(member.member_id) == 36  # UUID format

    def test_create_generates_unique_member_ids(self) -> None:
        """Each call to create() generates a unique member_id."""
        member1 = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="User One",
            email="one@example.com",
            registration_type="self",
        )
        member2 = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id="880e8400-e29b-41d4-a716-446655440000",
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="User Two",
            email="two@example.com",
            registration_type="self",
        )
        assert member1.member_id != member2.member_id

    def test_create_sets_timestamps(self) -> None:
        """create() sets created_at and updated_at to the current time."""
        before = datetime.now(UTC)
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Jane Doe",
            email="jane@example.com",
            registration_type="self",
        )
        after = datetime.now(UTC)
        assert before <= member.created_at <= after
        assert member.created_at == member.updated_at

    def test_create_invited_with_invited_by(self) -> None:
        """Invited member creation includes invited_by field."""
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="profesional",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Invited User",
            email="invited@example.com",
            registration_type="invited",
            invited_by="admin-user-id-123",
        )
        assert member.registration_type == "invited"
        assert member.invited_by == "admin-user-id-123"

    def test_create_with_metadata(self) -> None:
        """Member can be created with custom metadata."""
        meta = {"sport": "tennis", "level": "advanced"}
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Meta User",
            email="meta@example.com",
            registration_type="self",
            metadata=meta,
        )
        assert member.metadata == {"sport": "tennis", "level": "advanced"}

    def test_create_with_pending_confirmation_status(self) -> None:
        """Member can be created with pending_confirmation status."""
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Pending User",
            email="pending@example.com",
            registration_type="invited",
            invited_by="admin-id",
            status="pending_confirmation",
        )
        assert member.status == "pending_confirmation"

    def test_create_with_empty_tenant_id_raises(self) -> None:
        """Empty tenant_id raises ValidationError."""
        with pytest.raises(ValidationError):
            Member.create(
                tenant_id="",
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="self",
            )

    def test_create_with_invalid_tenant_id_raises(self) -> None:
        """Non-UUID tenant_id raises ValidationError."""
        with pytest.raises(ValidationError):
            Member.create(
                tenant_id="not-a-uuid",
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="self",
            )

    def test_create_with_empty_user_id_raises(self) -> None:
        """Empty user_id raises ValidationError."""
        with pytest.raises(ValidationError, match="User ID cannot be empty"):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id="",
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="self",
            )

    def test_create_with_empty_account_type_raises(self) -> None:
        """Empty account_type name raises ValidationError."""
        with pytest.raises(ValidationError, match="Account type cannot be empty"):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="self",
            )

    def test_create_with_invalid_account_type_id_raises(self) -> None:
        """Non-UUID account_type_id raises ValidationError."""
        with pytest.raises(ValidationError):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id="not-a-uuid",
                full_name="Test User",
                email="test@example.com",
                registration_type="self",
            )

    def test_create_with_empty_full_name_raises(self) -> None:
        """Empty full_name raises ValidationError."""
        with pytest.raises(ValidationError):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="",
                email="test@example.com",
                registration_type="self",
            )

    def test_create_with_invalid_email_raises(self) -> None:
        """Invalid email raises ValidationError."""
        with pytest.raises(ValidationError):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="not-an-email",
                registration_type="self",
            )

    def test_create_with_invalid_status_raises(self) -> None:
        """Invalid status raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid member status"):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="self",
                status="deleted",
            )

    def test_create_with_invalid_registration_type_raises(self) -> None:
        """Invalid registration_type raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid registration type"):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="unknown",
            )

    def test_create_invited_without_invited_by_raises(self) -> None:
        """Invited registration without invited_by raises ValidationError."""
        with pytest.raises(ValidationError, match="invited_by is required"):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="invited",
                invited_by=None,
            )

    def test_create_with_social_registration_type(self) -> None:
        """Social registration type produces a Member exposing registration_type == 'social'."""
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Social User",
            email="social@example.com",
            registration_type="social",
        )
        assert member.registration_type == "social"
        assert member.status == "active"
        assert member.invited_by is None

    def test_create_with_unknown_registration_type_raises(self) -> None:
        """Unknown registration_type raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid registration type"):
            Member.create(
                tenant_id=VALID_TENANT_ID,
                user_id=VALID_USER_ID,
                account_type="socio",
                account_type_id=VALID_ACCOUNT_TYPE_ID,
                full_name="Test User",
                email="test@example.com",
                registration_type="totally-unknown",
            )


class TestMemberReconstitute:
    """Tests for Member.reconstitute() method."""

    def test_reconstitute_valid(self) -> None:
        """Reconstitute builds a Member from persisted data."""
        now = datetime.now(UTC)
        member = Member.reconstitute(
            member_id="mid-1",
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Stored User",
            email="stored@example.com",
            status="active",
            registration_type="self",
            invited_by=None,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        assert member.member_id == "mid-1"
        assert member.status == "active"
        assert member.created_at == now


class TestMemberUpdate:
    """Tests for Member.update() method."""

    def _create_member(self) -> Member:
        """Helper to create a base member for update tests."""
        return Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Original Name",
            email="original@example.com",
            registration_type="self",
        )

    def test_update_full_name(self) -> None:
        """Updating full_name produces a new member with new name."""
        member = self._create_member()
        updated = member.update(full_name="New Name")
        assert updated.full_name == "New Name"
        assert member.full_name == "Original Name"  # original unchanged

    def test_update_preserves_immutable_fields(self) -> None:
        """Update preserves member_id, tenant_id, user_id, created_at, registration_type, invited_by."""
        member = self._create_member()
        updated = member.update(full_name="New Name")
        assert updated.member_id == member.member_id
        assert updated.tenant_id == member.tenant_id
        assert updated.user_id == member.user_id
        assert updated.created_at == member.created_at
        assert updated.registration_type == member.registration_type
        assert updated.invited_by == member.invited_by

    def test_update_refreshes_updated_at(self) -> None:
        """Update sets a new updated_at timestamp."""
        member = self._create_member()
        updated = member.update(full_name="New Name")
        assert updated.updated_at >= member.updated_at

    def test_update_status(self) -> None:
        """Status can be updated to a valid value."""
        member = self._create_member()
        updated = member.update(status="inactive")
        assert updated.status == "inactive"

    def test_update_with_invalid_status_raises(self) -> None:
        """Invalid status on update raises ValidationError."""
        member = self._create_member()
        with pytest.raises(ValidationError, match="Invalid member status"):
            member.update(status="deleted")

    def test_update_email(self) -> None:
        """Email can be updated with a valid value."""
        member = self._create_member()
        updated = member.update(email="newemail@example.com")
        assert updated.email == "newemail@example.com"

    def test_update_with_invalid_email_raises(self) -> None:
        """Invalid email on update raises ValidationError."""
        member = self._create_member()
        with pytest.raises(ValidationError):
            member.update(email="not-valid")

    def test_update_account_type(self) -> None:
        """Account type name can be updated."""
        member = self._create_member()
        updated = member.update(account_type="profesional")
        assert updated.account_type == "profesional"

    def test_update_with_empty_account_type_raises(self) -> None:
        """Empty account type on update raises ValidationError."""
        member = self._create_member()
        with pytest.raises(ValidationError, match="Account type cannot be empty"):
            member.update(account_type="  ")


class TestMemberDeactivate:
    """Tests for Member.deactivate() method."""

    def test_deactivate_active_member(self) -> None:
        """Active member can be deactivated."""
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Active User",
            email="active@example.com",
            registration_type="self",
        )
        deactivated = member.deactivate()
        assert deactivated.status == "inactive"
        assert deactivated.member_id == member.member_id

    def test_deactivate_already_inactive_raises(self) -> None:
        """Deactivating an already inactive member raises ValidationError."""
        now = datetime.now(UTC)
        member = Member.reconstitute(
            member_id="mid-1",
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Inactive User",
            email="inactive@example.com",
            status="inactive",
            registration_type="self",
            invited_by=None,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        with pytest.raises(ValidationError, match="Member is already inactive"):
            member.deactivate()


class TestMemberEquality:
    """Tests for Member equality and hashing."""

    def test_members_with_same_id_are_equal(self) -> None:
        """Two Members with the same member_id are equal."""
        now = datetime.now(UTC)
        member1 = Member.reconstitute(
            member_id="mid-1",
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="User A",
            email="a@example.com",
            status="active",
            registration_type="self",
            invited_by=None,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        member2 = Member.reconstitute(
            member_id="mid-1",
            tenant_id=VALID_TENANT_ID,
            user_id="different-user-id",
            account_type="profesional",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="User B",
            email="b@example.com",
            status="inactive",
            registration_type="invited",
            invited_by="admin-id",
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        assert member1 == member2

    def test_members_with_different_ids_not_equal(self) -> None:
        """Members with different member_ids are not equal."""
        member1 = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="User One",
            email="one@example.com",
            registration_type="self",
        )
        member2 = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="User Two",
            email="two@example.com",
            registration_type="self",
        )
        assert member1 != member2

    def test_hash_consistent_for_same_id(self) -> None:
        """Members with the same member_id have the same hash."""
        now = datetime.now(UTC)
        member1 = Member.reconstitute(
            member_id="mid-1",
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="A",
            email="a@example.com",
            status="active",
            registration_type="self",
            invited_by=None,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        member2 = Member.reconstitute(
            member_id="mid-1",
            tenant_id=VALID_TENANT_ID,
            user_id="other-uid",
            account_type="profesional",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="B",
            email="b@example.com",
            status="inactive",
            registration_type="self",
            invited_by=None,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        assert hash(member1) == hash(member2)

    def test_not_equal_to_non_member(self) -> None:
        """Member is not equal to a non-Member object."""
        member = Member.create(
            tenant_id=VALID_TENANT_ID,
            user_id=VALID_USER_ID,
            account_type="socio",
            account_type_id=VALID_ACCOUNT_TYPE_ID,
            full_name="Test",
            email="test@example.com",
            registration_type="self",
        )
        assert member != "not-a-member"
