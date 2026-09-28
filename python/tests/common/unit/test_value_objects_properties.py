"""Property-based tests for domain Value Objects.

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 13.5**

Property 17: Value Object Validation Gate
- For any input that fails Value Object validation, the system returns a ValidationError.
- For any valid input, the system always produces a valid value object.
"""

from __future__ import annotations

import string
import uuid

import hypothesis.strategies as st
from hypothesis import given, assume, settings

from api.common.errors.validationError import ValidationError
from api.accountType.accountTypeId import AccountTypeId
from api.common.valueObjects.email import Email
from api.member.fullName import FullName
from api.member.memberId import MemberId
from api.common.valueObjects.password import Password
from api.common.valueObjects.roleName import RoleName
from api.common.tenant.tenantId import TenantId


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid email strategy using hypothesis built-in
valid_emails = st.emails()

# Invalid email strategies: strings that should never pass email validation
invalid_emails = st.one_of(
    # Empty or whitespace-only
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=10),
    # Missing @ symbol
    st.text(
        alphabet=string.ascii_letters + string.digits,
        min_size=1,
        max_size=50,
    ).filter(lambda s: "@" not in s),
    # Over 254 characters
    st.text(min_size=255, max_size=300).map(lambda s: s[:250] + "@x.co"),
    # Missing domain part
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=20).map(lambda s: s + "@"),
    # Missing local part
    st.text(alphabet=string.ascii_letters + ".", min_size=2, max_size=20).map(lambda s: "@" + s),
)

# Valid password strategy: any string between 8 and 72 chars
valid_passwords = st.text(min_size=8, max_size=72)

# Invalid passwords: too short (0-7 chars) or too long (73+ chars)
invalid_passwords_too_short = st.text(max_size=7)
invalid_passwords_too_long = st.text(min_size=73, max_size=200)

# Valid UUID strings
valid_uuids = st.uuids().map(str)

# Invalid UUID strategies: strings that are not valid UUIDs
invalid_uuids = st.one_of(
    # Empty or whitespace
    st.just(""),
    st.text(alphabet=" \t", min_size=1, max_size=5),
    # Random non-UUID strings
    st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=50).filter(
        lambda s: not _is_valid_uuid(s.strip())
    ),
    # Partial UUIDs (wrong length or format)
    st.text(alphabet=string.hexdigits + "-", min_size=1, max_size=35).filter(
        lambda s: not _is_valid_uuid(s.strip())
    ),
)

# Valid role names (case-insensitive variants)
valid_role_names = st.one_of(
    st.sampled_from(["admin", "manager", "viewer"]),
    # Case variations
    st.sampled_from(["Admin", "ADMIN", "Manager", "MANAGER", "Viewer", "VIEWER"]),
    # With whitespace padding
    st.sampled_from(["admin", "manager", "viewer"]).map(lambda r: f"  {r}  "),
)

# Invalid role names: anything that is not admin/manager/viewer
invalid_role_names = st.one_of(
    # Empty or whitespace
    st.just(""),
    st.text(alphabet=" \t", min_size=1, max_size=5),
    # Invalid role strings
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=30).filter(
        lambda s: s.strip().lower() not in {"admin", "manager", "viewer"}
    ),
)

# Valid full name: non-empty after trim, max 200 chars
valid_full_names = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) > 0 and len(s.strip()) <= 200)

# Invalid full names: empty, whitespace-only, or exceeding 200 chars
invalid_full_names = st.one_of(
    # Empty
    st.just(""),
    # Whitespace-only
    st.text(alphabet=" \t\n\r", min_size=1, max_size=20),
    # Over 200 characters (after trim)
    st.text(
        alphabet=string.ascii_letters,
        min_size=201,
        max_size=300,
    ),
)


def _is_valid_uuid(s: str) -> bool:
    """Helper to check if a string is a valid UUID."""
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False


# ─── Property Tests: Invalid inputs NEVER pass validation ─────────────────────


class TestInvalidInputsNeverPassValidation:
    """Property 17 (Part 1): Invalid inputs always raise ValidationError."""

    @given(email=invalid_emails)
    @settings(max_examples=200)
    def test_invalid_email_always_rejected(self, email: str) -> None:
        """Invalid emails never produce a valid Email value object.

        **Validates: Requirements 11.1**
        """
        try:
            Email.create(email)
            # If we get here, the input somehow passed — that's a failure
            assert False, f"Expected ValidationError for email: {email!r}"
        except ValidationError:
            pass  # Expected behavior

    @given(password=invalid_passwords_too_short)
    @settings(max_examples=200)
    def test_short_password_always_rejected(self, password: str) -> None:
        """Passwords under 8 characters never pass validation.

        **Validates: Requirements 11.2, 13.5**
        """
        assume(len(password) < 8)
        try:
            Password.create(password)
            assert False, f"Expected ValidationError for short password of length {len(password)}"
        except ValidationError:
            pass

    @given(password=invalid_passwords_too_long)
    @settings(max_examples=200)
    def test_long_password_always_rejected(self, password: str) -> None:
        """Passwords over 72 characters never pass validation.

        **Validates: Requirements 13.5**
        """
        assume(len(password) > 72)
        try:
            Password.create(password)
            assert False, f"Expected ValidationError for long password of length {len(password)}"
        except ValidationError:
            pass

    @given(value=invalid_uuids)
    @settings(max_examples=200)
    def test_invalid_tenant_id_always_rejected(self, value: str) -> None:
        """Invalid UUIDs never produce a valid TenantId.

        **Validates: Requirements 11.3**
        """
        try:
            TenantId.create(value)
            assert False, f"Expected ValidationError for tenant_id: {value!r}"
        except ValidationError:
            pass

    @given(value=invalid_uuids)
    @settings(max_examples=200)
    def test_invalid_member_id_always_rejected(self, value: str) -> None:
        """Invalid UUIDs never produce a valid MemberId.

        **Validates: Requirements 11.4**
        """
        try:
            MemberId.create(value)
            assert False, f"Expected ValidationError for member_id: {value!r}"
        except ValidationError:
            pass

    @given(value=invalid_uuids)
    @settings(max_examples=200)
    def test_invalid_account_type_id_always_rejected(self, value: str) -> None:
        """Invalid UUIDs never produce a valid AccountTypeId.

        **Validates: Requirements 11.4**
        """
        try:
            AccountTypeId.create(value)
            assert False, f"Expected ValidationError for account_type_id: {value!r}"
        except ValidationError:
            pass

    @given(value=invalid_role_names)
    @settings(max_examples=200)
    def test_invalid_role_name_always_rejected(self, value: str) -> None:
        """Non-allowed role names never pass validation.

        **Validates: Requirements 11.5**
        """
        try:
            RoleName.create(value)
            assert False, f"Expected ValidationError for role_name: {value!r}"
        except ValidationError:
            pass

    @given(value=invalid_full_names)
    @settings(max_examples=200)
    def test_invalid_full_name_always_rejected(self, value: str) -> None:
        """Empty or oversized full names never pass validation.

        **Validates: Requirements 11.2**
        """
        try:
            FullName.create(value)
            assert False, f"Expected ValidationError for full_name: {value!r}"
        except ValidationError:
            pass


# ─── Property Tests: Valid inputs ALWAYS produce valid value objects ───────────


class TestValidInputsAlwaysProduceValidObjects:
    """Property 17 (Part 2): Valid inputs always produce valid value objects."""

    @given(email=valid_emails)
    @settings(max_examples=200)
    def test_valid_email_always_accepted(self, email: str) -> None:
        """Any properly formatted email produces a valid Email value object.

        **Validates: Requirements 11.1**
        """
        # hypothesis emails() may produce emails > 254 chars; filter those out
        assume(len(email.strip()) <= 254)
        result = Email.create(email)
        assert result.value == email.strip().lower()
        assert len(result.value) > 0
        assert "@" in result.value

    @given(password=valid_passwords)
    @settings(max_examples=200)
    def test_valid_password_always_accepted(self, password: str) -> None:
        """Any string between 8-72 chars produces a valid Password value object.

        **Validates: Requirements 11.2, 13.5**
        """
        result = Password.create(password)
        assert result.value == password

    @given(uid=valid_uuids)
    @settings(max_examples=200)
    def test_valid_uuid_always_produces_tenant_id(self, uid: str) -> None:
        """Any valid UUID string produces a valid TenantId value object.

        **Validates: Requirements 11.3**
        """
        result = TenantId.create(uid)
        # The stored value should be a valid UUID
        uuid.UUID(result.value)
        assert result.value == uid

    @given(uid=valid_uuids)
    @settings(max_examples=200)
    def test_valid_uuid_always_produces_member_id(self, uid: str) -> None:
        """Any valid UUID string produces a valid MemberId value object.

        **Validates: Requirements 11.4**
        """
        result = MemberId.create(uid)
        uuid.UUID(result.value)
        assert result.value == uid

    @given(uid=valid_uuids)
    @settings(max_examples=200)
    def test_valid_uuid_always_produces_account_type_id(self, uid: str) -> None:
        """Any valid UUID string produces a valid AccountTypeId value object.

        **Validates: Requirements 11.4**
        """
        result = AccountTypeId.create(uid)
        uuid.UUID(result.value)
        assert result.value == uid

    @given(role=valid_role_names)
    @settings(max_examples=100)
    def test_valid_role_name_always_accepted(self, role: str) -> None:
        """Any of admin/manager/viewer (case-insensitive) produces a valid RoleName.

        **Validates: Requirements 11.5**
        """
        result = RoleName.create(role)
        assert result.value in {"admin", "manager", "viewer"}
        assert result.value == role.strip().lower()

    @given(name=valid_full_names)
    @settings(max_examples=200)
    def test_valid_full_name_always_accepted(self, name: str) -> None:
        """Any non-empty string up to 200 chars produces a valid FullName.

        **Validates: Requirements 11.2**
        """
        result = FullName.create(name)
        assert result.value == name.strip()
        assert 0 < len(result.value) <= 200


# ─── Property Tests: Value Objects are immutable ──────────────────────────────


class TestValueObjectImmutability:
    """Property 17 (Supplemental): Value objects are always immutable after creation."""

    @given(uid=valid_uuids)
    @settings(max_examples=50)
    def test_tenant_id_immutable(self, uid: str) -> None:
        """TenantId cannot be mutated after creation.

        **Validates: Requirements 11.4**
        """
        tenant_id = TenantId.create(uid)
        try:
            tenant_id._value = "hacked"  # type: ignore[misc]
            assert False, "Should have raised AttributeError"
        except AttributeError:
            pass

    @given(uid=valid_uuids)
    @settings(max_examples=50)
    def test_member_id_immutable(self, uid: str) -> None:
        """MemberId cannot be mutated after creation.

        **Validates: Requirements 11.4**
        """
        member_id = MemberId.create(uid)
        try:
            member_id._value = "hacked"  # type: ignore[misc]
            assert False, "Should have raised AttributeError"
        except AttributeError:
            pass

    @given(password=valid_passwords)
    @settings(max_examples=50)
    def test_password_immutable(self, password: str) -> None:
        """Password cannot be mutated after creation.

        **Validates: Requirements 13.5**
        """
        pw = Password.create(password)
        try:
            pw._value = "hacked"  # type: ignore[misc]
            assert False, "Should have raised AttributeError"
        except AttributeError:
            pass

    @given(name=valid_full_names)
    @settings(max_examples=50)
    def test_full_name_immutable(self, name: str) -> None:
        """FullName cannot be mutated after creation.

        **Validates: Requirements 11.2**
        """
        full_name = FullName.create(name)
        try:
            full_name._value = "hacked"  # type: ignore[misc]
            assert False, "Should have raised AttributeError"
        except AttributeError:
            pass


# ─── Property Tests: Equality consistency ─────────────────────────────────────


class TestValueObjectEqualityConsistency:
    """Property 17 (Supplemental): Equal inputs always produce equal value objects."""

    @given(uid=valid_uuids)
    @settings(max_examples=100)
    def test_tenant_id_equality_consistent(self, uid: str) -> None:
        """Creating TenantId twice from same input yields equal objects.

        **Validates: Requirements 11.3**
        """
        t1 = TenantId.create(uid)
        t2 = TenantId.create(uid)
        assert t1 == t2
        assert hash(t1) == hash(t2)

    @given(password=valid_passwords)
    @settings(max_examples=100)
    def test_password_equality_consistent(self, password: str) -> None:
        """Creating Password twice from same input yields equal objects.

        **Validates: Requirements 13.5**
        """
        p1 = Password.create(password)
        p2 = Password.create(password)
        assert p1 == p2
        assert hash(p1) == hash(p2)

    @given(email=valid_emails)
    @settings(max_examples=100)
    def test_email_equality_consistent(self, email: str) -> None:
        """Creating Email twice from same input yields equal objects.

        **Validates: Requirements 11.1**
        """
        assume(len(email.strip()) <= 254)
        e1 = Email.create(email)
        e2 = Email.create(email)
        assert e1 == e2
        assert hash(e1) == hash(e2)
