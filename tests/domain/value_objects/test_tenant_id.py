"""Unit tests for TenantId value object."""

import uuid

import pytest

from domain.errors.validation_error import ValidationError
from domain.value_objects.tenant_id import TenantId


class TestTenantIdCreate:
    """Tests for TenantId.create() factory method."""

    def test_create_with_valid_uuid(self) -> None:
        """Valid UUID string produces a TenantId."""
        valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        tenant_id = TenantId.create(valid_uuid)
        assert tenant_id.value == valid_uuid

    def test_create_normalizes_to_lowercase(self) -> None:
        """UUID with uppercase letters is normalized to lowercase."""
        upper_uuid = "550E8400-E29B-41D4-A716-446655440000"
        tenant_id = TenantId.create(upper_uuid)
        assert tenant_id.value == "550e8400-e29b-41d4-a716-446655440000"

    def test_create_trims_whitespace(self) -> None:
        """Leading/trailing whitespace is trimmed before validation."""
        valid_uuid = "  550e8400-e29b-41d4-a716-446655440000  "
        tenant_id = TenantId.create(valid_uuid)
        assert tenant_id.value == "550e8400-e29b-41d4-a716-446655440000"

    def test_create_with_empty_string_raises_validation_error(self) -> None:
        """Empty string raises ValidationError with 'Invalid tenant ID'."""
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            TenantId.create("")

    def test_create_with_whitespace_only_raises_validation_error(self) -> None:
        """Whitespace-only string raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            TenantId.create("   ")

    def test_create_with_invalid_format_raises_validation_error(self) -> None:
        """Non-UUID string raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            TenantId.create("not-a-uuid")

    def test_create_with_partial_uuid_raises_validation_error(self) -> None:
        """Partial UUID raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            TenantId.create("550e8400-e29b-41d4")

    def test_create_accepts_uuid_without_hyphens(self) -> None:
        """UUID without hyphens is still valid (Python uuid.UUID accepts this)."""
        no_hyphens = "550e8400e29b41d4a716446655440000"
        tenant_id = TenantId.create(no_hyphens)
        assert tenant_id.value == "550e8400-e29b-41d4-a716-446655440000"


class TestTenantIdGenerate:
    """Tests for TenantId.generate() factory method."""

    def test_generate_produces_valid_uuid(self) -> None:
        """Generated TenantId contains a valid UUID."""
        tenant_id = TenantId.generate()
        # Should not raise
        uuid.UUID(tenant_id.value)

    def test_generate_produces_unique_values(self) -> None:
        """Two generated TenantIds are different."""
        id1 = TenantId.generate()
        id2 = TenantId.generate()
        assert id1 != id2


class TestTenantIdEquality:
    """Tests for TenantId equality and hashing."""

    def test_equal_values_are_equal(self) -> None:
        """Two TenantIds with the same UUID are equal."""
        val = "550e8400-e29b-41d4-a716-446655440000"
        id1 = TenantId.create(val)
        id2 = TenantId.create(val)
        assert id1 == id2

    def test_different_values_are_not_equal(self) -> None:
        """Two TenantIds with different UUIDs are not equal."""
        id1 = TenantId.generate()
        id2 = TenantId.generate()
        assert id1 != id2

    def test_hash_is_consistent_for_equal_values(self) -> None:
        """Equal TenantIds produce the same hash."""
        val = "550e8400-e29b-41d4-a716-446655440000"
        id1 = TenantId.create(val)
        id2 = TenantId.create(val)
        assert hash(id1) == hash(id2)

    def test_can_be_used_in_sets(self) -> None:
        """TenantId can be stored in a set."""
        val = "550e8400-e29b-41d4-a716-446655440000"
        id1 = TenantId.create(val)
        id2 = TenantId.create(val)
        s = {id1, id2}
        assert len(s) == 1

    def test_not_equal_to_non_tenant_id(self) -> None:
        """TenantId is not equal to a non-TenantId object."""
        tenant_id = TenantId.create("550e8400-e29b-41d4-a716-446655440000")
        assert tenant_id != "550e8400-e29b-41d4-a716-446655440000"


class TestTenantIdImmutability:
    """Tests for TenantId immutability via __slots__."""

    def test_cannot_add_new_attribute(self) -> None:
        """TenantId does not allow adding new attributes (__slots__)."""
        tenant_id = TenantId.create("550e8400-e29b-41d4-a716-446655440000")
        with pytest.raises(AttributeError):
            tenant_id.new_attr = "something"  # type: ignore[attr-defined]


class TestTenantIdStringRepresentation:
    """Tests for TenantId string representations."""

    def test_str_returns_uuid_value(self) -> None:
        """str() returns the UUID string."""
        val = "550e8400-e29b-41d4-a716-446655440000"
        tenant_id = TenantId.create(val)
        assert str(tenant_id) == val

    def test_repr_returns_debug_representation(self) -> None:
        """repr() returns a debug-friendly string."""
        val = "550e8400-e29b-41d4-a716-446655440000"
        tenant_id = TenantId.create(val)
        assert repr(tenant_id) == f"TenantId('{val}')"
