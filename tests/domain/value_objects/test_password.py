"""Unit tests for the Password value object."""

import pytest

from domain.errors.validation_error import ValidationError
from domain.value_objects.password import Password


class TestPasswordCreate:
    """Tests for Password.create() factory method."""

    def test_valid_password_minimum_length(self) -> None:
        password = Password.create("a" * 8)
        assert password.value == "a" * 8

    def test_valid_password_maximum_length(self) -> None:
        password = Password.create("b" * 72)
        assert password.value == "b" * 72

    def test_valid_password_normal(self) -> None:
        password = Password.create("MyP@ssw0rd!")
        assert password.value == "MyP@ssw0rd!"

    def test_too_short_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="at least 8 characters") as exc_info:
            Password.create("short")
        assert exc_info.value.field == "password"

    def test_empty_string_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="at least 8 characters"):
            Password.create("")

    def test_seven_chars_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="at least 8 characters"):
            Password.create("a" * 7)

    def test_too_long_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="must not exceed 72 characters") as exc_info:
            Password.create("x" * 73)
        assert exc_info.value.field == "password"

    def test_73_chars_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            Password.create("a" * 73)

    def test_preserves_original_value_no_modification(self) -> None:
        raw = "  Spaces Around  "
        password = Password.create(raw)
        assert password.value == raw


class TestPasswordCreateUnsafe:
    """Tests for Password.create_unsafe() — skips validation."""

    def test_allows_short_password(self) -> None:
        password = Password.create_unsafe("abc")
        assert password.value == "abc"

    def test_allows_empty_string(self) -> None:
        password = Password.create_unsafe("")
        assert password.value == ""

    def test_allows_very_long_password(self) -> None:
        password = Password.create_unsafe("z" * 200)
        assert password.value == "z" * 200


class TestPasswordImmutability:
    """Tests for immutability guarantees."""

    def test_cannot_set_attribute(self) -> None:
        password = Password.create("validpass")
        with pytest.raises(AttributeError, match="immutable"):
            password.value = "hacked"  # type: ignore[misc]

    def test_cannot_set_private_attribute(self) -> None:
        password = Password.create("validpass")
        with pytest.raises(AttributeError, match="immutable"):
            password._value = "hacked"  # type: ignore[misc]

    def test_cannot_delete_attribute(self) -> None:
        password = Password.create("validpass")
        with pytest.raises(AttributeError, match="immutable"):
            del password._value  # type: ignore[misc]


class TestPasswordEquality:
    """Tests for equality and hashing."""

    def test_equal_passwords(self) -> None:
        p1 = Password.create("samepassword")
        p2 = Password.create("samepassword")
        assert p1 == p2

    def test_different_passwords(self) -> None:
        p1 = Password.create("password1!")
        p2 = Password.create("password2!")
        assert p1 != p2

    def test_not_equal_to_string(self) -> None:
        password = Password.create("validpass")
        assert password != "validpass"

    def test_hashable_same_value(self) -> None:
        p1 = Password.create("samepassword")
        p2 = Password.create("samepassword")
        assert hash(p1) == hash(p2)

    def test_can_be_used_in_set(self) -> None:
        p1 = Password.create("password1!")
        p2 = Password.create("password1!")
        assert len({p1, p2}) == 1


class TestPasswordRepresentation:
    """Tests for repr/str — should never expose password value."""

    def test_repr_does_not_expose_value(self) -> None:
        password = Password.create("secretpass")
        assert "secretpass" not in repr(password)
        assert repr(password) == "Password(***)"

    def test_str_does_not_expose_value(self) -> None:
        password = Password.create("secretpass")
        assert "secretpass" not in str(password)
        assert str(password) == "***"
