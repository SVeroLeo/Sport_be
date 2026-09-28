"""Unit tests for domain value objects: MemberId, AccountTypeId, RoleName, FullName, TenantId."""

import uuid

import pytest

from api.common.errors.validationError import ValidationError
from api.accountType.accountTypeId import AccountTypeId
from api.member.fullName import FullName
from api.member.memberId import MemberId
from api.common.valueObjects.roleName import RoleName
from api.common.tenant.tenantId import TenantId

# ─── TenantId ─────────────────────────────────────────────────────────────────


class TestTenantId:
    def test_create_with_valid_uuid(self) -> None:
        uid = str(uuid.uuid4())
        tenant_id = TenantId.create(uid)
        assert tenant_id.value == uid

    def test_create_strips_whitespace(self) -> None:
        uid = str(uuid.uuid4())
        tenant_id = TenantId.create(f"  {uid}  ")
        assert tenant_id.value == uid

    def test_create_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            TenantId.create("")

    def test_create_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            TenantId.create("   ")

    def test_create_rejects_invalid_uuid(self) -> None:
        with pytest.raises(ValidationError, match="Invalid tenant ID"):
            TenantId.create("not-a-uuid")

    def test_generate_produces_valid_uuid(self) -> None:
        tenant_id = TenantId.generate()
        # Should not raise
        uuid.UUID(tenant_id.value)

    def test_equality(self) -> None:
        uid = str(uuid.uuid4())
        assert TenantId.create(uid) == TenantId.create(uid)

    def test_inequality(self) -> None:
        assert TenantId.generate() != TenantId.generate()

    def test_immutability(self) -> None:
        tenant_id = TenantId.generate()
        with pytest.raises(AttributeError):
            tenant_id._value = "changed"  # type: ignore[misc]

    def test_hash_consistency(self) -> None:
        uid = str(uuid.uuid4())
        t1 = TenantId.create(uid)
        t2 = TenantId.create(uid)
        assert hash(t1) == hash(t2)
        assert {t1, t2} == {t1}


# ─── MemberId ─────────────────────────────────────────────────────────────────


class TestMemberId:
    def test_create_with_valid_uuid(self) -> None:
        uid = str(uuid.uuid4())
        member_id = MemberId.create(uid)
        assert member_id.value == uid

    def test_create_strips_whitespace(self) -> None:
        uid = str(uuid.uuid4())
        member_id = MemberId.create(f"  {uid}  ")
        assert member_id.value == uid

    def test_create_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="Invalid member ID"):
            MemberId.create("")

    def test_create_rejects_invalid_uuid(self) -> None:
        with pytest.raises(ValidationError, match="Invalid member ID"):
            MemberId.create("abc-123")

    def test_generate_produces_valid_uuid(self) -> None:
        member_id = MemberId.generate()
        uuid.UUID(member_id.value)

    def test_equality(self) -> None:
        uid = str(uuid.uuid4())
        assert MemberId.create(uid) == MemberId.create(uid)

    def test_immutability(self) -> None:
        member_id = MemberId.generate()
        with pytest.raises(AttributeError):
            member_id._value = "changed"  # type: ignore[misc]


# ─── AccountTypeId ────────────────────────────────────────────────────────────


class TestAccountTypeId:
    def test_create_with_valid_uuid(self) -> None:
        uid = str(uuid.uuid4())
        at_id = AccountTypeId.create(uid)
        assert at_id.value == uid

    def test_create_strips_whitespace(self) -> None:
        uid = str(uuid.uuid4())
        at_id = AccountTypeId.create(f" {uid} ")
        assert at_id.value == uid

    def test_create_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="Invalid account type ID"):
            AccountTypeId.create("")

    def test_create_rejects_invalid_uuid(self) -> None:
        with pytest.raises(ValidationError, match="Invalid account type ID"):
            AccountTypeId.create("12345")

    def test_generate_produces_valid_uuid(self) -> None:
        at_id = AccountTypeId.generate()
        uuid.UUID(at_id.value)

    def test_equality(self) -> None:
        uid = str(uuid.uuid4())
        assert AccountTypeId.create(uid) == AccountTypeId.create(uid)

    def test_immutability(self) -> None:
        at_id = AccountTypeId.generate()
        with pytest.raises(AttributeError):
            at_id._value = "changed"  # type: ignore[misc]


# ─── RoleName ─────────────────────────────────────────────────────────────────


class TestRoleName:
    @pytest.mark.parametrize("role", ["admin", "manager", "viewer"])
    def test_create_with_valid_role(self, role: str) -> None:
        role_name = RoleName.create(role)
        assert role_name.value == role

    @pytest.mark.parametrize("role", ["ADMIN", "Manager", "VIEWER", "Admin"])
    def test_create_is_case_insensitive(self, role: str) -> None:
        role_name = RoleName.create(role)
        assert role_name.value == role.lower()

    def test_create_strips_whitespace(self) -> None:
        role_name = RoleName.create("  admin  ")
        assert role_name.value == "admin"

    def test_create_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="Invalid role name"):
            RoleName.create("")

    def test_create_rejects_invalid_role(self) -> None:
        with pytest.raises(ValidationError, match="Invalid role name"):
            RoleName.create("superuser")

    def test_class_constants(self) -> None:
        assert RoleName.ADMIN.value == "admin"
        assert RoleName.MANAGER.value == "manager"
        assert RoleName.VIEWER.value == "viewer"

    def test_equality_with_constant(self) -> None:
        assert RoleName.create("admin") == RoleName.ADMIN

    def test_immutability(self) -> None:
        role = RoleName.create("admin")
        with pytest.raises(AttributeError):
            role._value = "changed"  # type: ignore[misc]


# ─── FullName ─────────────────────────────────────────────────────────────────


class TestFullName:
    def test_create_with_valid_name(self) -> None:
        name = FullName.create("John Doe")
        assert name.value == "John Doe"

    def test_create_trims_whitespace(self) -> None:
        name = FullName.create("  Jane Smith  ")
        assert name.value == "Jane Smith"

    def test_create_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="Full name cannot be empty"):
            FullName.create("")

    def test_create_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError, match="Full name cannot be empty"):
            FullName.create("   ")

    def test_create_rejects_exceeding_200_chars(self) -> None:
        long_name = "A" * 201
        with pytest.raises(ValidationError, match="cannot exceed 200 characters"):
            FullName.create(long_name)

    def test_create_accepts_exactly_200_chars(self) -> None:
        name_200 = "A" * 200
        full_name = FullName.create(name_200)
        assert full_name.value == name_200
        assert len(full_name.value) == 200

    def test_equality(self) -> None:
        assert FullName.create("John Doe") == FullName.create("John Doe")

    def test_inequality(self) -> None:
        assert FullName.create("John") != FullName.create("Jane")

    def test_immutability(self) -> None:
        name = FullName.create("Test Name")
        with pytest.raises(AttributeError):
            name._value = "changed"  # type: ignore[misc]
