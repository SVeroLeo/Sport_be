"""Unit tests for AccountType entity."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from domain.entities.account_type import AccountType
from domain.errors.validation_error import ValidationError


class TestAccountTypeCreate:
    """Tests for AccountType.create() factory method."""

    def test_create_with_valid_data(self) -> None:
        tenant_id = str(uuid.uuid4())
        account_type = AccountType.create(
            tenant_id=tenant_id,
            name="Socio",
            description="Miembro asociado",
        )

        assert account_type.tenant_id == tenant_id
        assert account_type.name == "Socio"
        assert account_type.description == "Miembro asociado"
        assert account_type.config is None
        assert account_type.status == "active"
        assert account_type.is_active is True
        # Verify UUID was generated
        uuid.UUID(account_type.account_type_id)  # raises if invalid
        assert account_type.created_at is not None
        assert account_type.updated_at is not None

    def test_create_with_config(self) -> None:
        tenant_id = str(uuid.uuid4())
        config = {"max_members": 100, "features": ["booking"]}
        account_type = AccountType.create(
            tenant_id=tenant_id,
            name="Profesional",
            config=config,
        )

        assert account_type.config == config

    def test_create_strips_whitespace_from_name(self) -> None:
        tenant_id = str(uuid.uuid4())
        account_type = AccountType.create(
            tenant_id=tenant_id,
            name="  Socio  ",
        )

        assert account_type.name == "Socio"

    def test_create_with_empty_name_raises_validation_error(self) -> None:
        tenant_id = str(uuid.uuid4())
        with pytest.raises(ValidationError, match="cannot be empty"):
            AccountType.create(tenant_id=tenant_id, name="")

    def test_create_with_whitespace_only_name_raises_validation_error(self) -> None:
        tenant_id = str(uuid.uuid4())
        with pytest.raises(ValidationError, match="cannot be empty"):
            AccountType.create(tenant_id=tenant_id, name="   ")

    def test_create_with_name_exceeding_100_chars_raises_validation_error(self) -> None:
        tenant_id = str(uuid.uuid4())
        long_name = "a" * 101
        with pytest.raises(ValidationError, match="cannot exceed 100 characters"):
            AccountType.create(tenant_id=tenant_id, name=long_name)

    def test_create_with_name_exactly_100_chars_succeeds(self) -> None:
        tenant_id = str(uuid.uuid4())
        name = "a" * 100
        account_type = AccountType.create(tenant_id=tenant_id, name=name)
        assert account_type.name == name

    def test_create_with_invalid_tenant_id_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            AccountType.create(tenant_id="not-a-uuid", name="Socio")

    def test_create_sets_status_active(self) -> None:
        tenant_id = str(uuid.uuid4())
        account_type = AccountType.create(tenant_id=tenant_id, name="Socio")
        assert account_type.status == "active"

    def test_create_sets_timestamps(self) -> None:
        tenant_id = str(uuid.uuid4())
        before = datetime.now(timezone.utc)
        account_type = AccountType.create(tenant_id=tenant_id, name="Socio")
        after = datetime.now(timezone.utc)

        assert before <= account_type.created_at <= after
        assert account_type.created_at == account_type.updated_at


class TestAccountTypeUpdate:
    """Tests for AccountType update methods."""

    def _make_account_type(self) -> AccountType:
        return AccountType.create(
            tenant_id=str(uuid.uuid4()),
            name="Original",
            description="Original desc",
        )

    def test_update_name_with_valid_value(self) -> None:
        account_type = self._make_account_type()
        original_updated = account_type.updated_at
        account_type.update_name("New Name")

        assert account_type.name == "New Name"
        assert account_type.updated_at >= original_updated

    def test_update_name_strips_whitespace(self) -> None:
        account_type = self._make_account_type()
        account_type.update_name("  Trimmed  ")
        assert account_type.name == "Trimmed"

    def test_update_name_with_empty_raises_validation_error(self) -> None:
        account_type = self._make_account_type()
        with pytest.raises(ValidationError, match="cannot be empty"):
            account_type.update_name("")

    def test_update_name_exceeding_100_chars_raises_validation_error(self) -> None:
        account_type = self._make_account_type()
        with pytest.raises(ValidationError, match="cannot exceed 100 characters"):
            account_type.update_name("x" * 101)

    def test_update_description(self) -> None:
        account_type = self._make_account_type()
        account_type.update_description("Updated description")
        assert account_type.description == "Updated description"

    def test_update_description_to_none(self) -> None:
        account_type = self._make_account_type()
        account_type.update_description(None)
        assert account_type.description is None

    def test_update_config(self) -> None:
        account_type = self._make_account_type()
        new_config = {"feature": "enabled"}
        account_type.update_config(new_config)
        assert account_type.config == new_config


class TestAccountTypeStatus:
    """Tests for AccountType status transitions."""

    def test_deactivate(self) -> None:
        account_type = AccountType.create(
            tenant_id=str(uuid.uuid4()), name="Test"
        )
        assert account_type.is_active is True

        account_type.deactivate()
        assert account_type.status == "inactive"
        assert account_type.is_active is False

    def test_activate(self) -> None:
        account_type = AccountType.create(
            tenant_id=str(uuid.uuid4()), name="Test"
        )
        account_type.deactivate()
        account_type.activate()

        assert account_type.status == "active"
        assert account_type.is_active is True


class TestAccountTypeReconstitute:
    """Tests for AccountType.reconstitute() method."""

    def test_reconstitute_creates_entity_without_validation(self) -> None:
        now = datetime.now(timezone.utc)
        account_type = AccountType.reconstitute(
            account_type_id=str(uuid.uuid4()),
            tenant_id=str(uuid.uuid4()),
            name="Reconstituted",
            description="From DB",
            config={"key": "value"},
            status="inactive",
            created_at=now,
            updated_at=now,
        )

        assert account_type.name == "Reconstituted"
        assert account_type.status == "inactive"
        assert account_type.config == {"key": "value"}


class TestAccountTypeEquality:
    """Tests for AccountType equality and hashing."""

    def test_same_id_are_equal(self) -> None:
        shared_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        a = AccountType.reconstitute(
            shared_id, str(uuid.uuid4()), "A", None, None, "active", now, now
        )
        b = AccountType.reconstitute(
            shared_id, str(uuid.uuid4()), "B", None, None, "inactive", now, now
        )
        assert a == b

    def test_different_id_are_not_equal(self) -> None:
        now = datetime.now(timezone.utc)
        a = AccountType.reconstitute(
            str(uuid.uuid4()), str(uuid.uuid4()), "A", None, None, "active", now, now
        )
        b = AccountType.reconstitute(
            str(uuid.uuid4()), str(uuid.uuid4()), "A", None, None, "active", now, now
        )
        assert a != b

    def test_hash_by_id(self) -> None:
        shared_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        a = AccountType.reconstitute(
            shared_id, str(uuid.uuid4()), "A", None, None, "active", now, now
        )
        b = AccountType.reconstitute(
            shared_id, str(uuid.uuid4()), "B", None, None, "inactive", now, now
        )
        assert hash(a) == hash(b)
