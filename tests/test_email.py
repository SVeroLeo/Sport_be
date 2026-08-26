"""Unit tests for Email value object."""

import pytest

from domain.errors.validation_error import ValidationError
from domain.value_objects.email import Email


class TestEmailCreate:
    """Tests for Email.create() factory method."""

    def test_valid_email(self) -> None:
        email = Email.create("user@example.com")
        assert email.value == "user@example.com"

    def test_normalizes_to_lowercase(self) -> None:
        email = Email.create("User@Example.COM")
        assert email.value == "user@example.com"

    def test_trims_whitespace(self) -> None:
        email = Email.create("  user@example.com  ")
        assert email.value == "user@example.com"

    def test_trims_and_lowercases(self) -> None:
        email = Email.create("  User@Example.COM  ")
        assert email.value == "user@example.com"

    def test_valid_email_with_dots_in_local(self) -> None:
        email = Email.create("first.last@example.com")
        assert email.value == "first.last@example.com"

    def test_valid_email_with_plus(self) -> None:
        email = Email.create("user+tag@example.com")
        assert email.value == "user+tag@example.com"

    def test_valid_email_with_subdomain(self) -> None:
        email = Email.create("user@sub.domain.example.com")
        assert email.value == "user@sub.domain.example.com"

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("   ")

    def test_rejects_no_at_sign(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("userexample.com")

    def test_rejects_no_domain(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("user@")

    def test_rejects_no_local_part(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("@example.com")

    def test_rejects_no_dot_in_domain(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("user@example")

    def test_rejects_exceeds_254_characters(self) -> None:
        # Create an email that exceeds 254 chars
        # local@domain.com => local needs to be 255 - len("@example.com") = 243
        local_part = "a" * 243
        long_email = f"{local_part}@example.com"
        assert len(long_email) == 255
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create(long_email)

    def test_accepts_email_at_254_characters(self) -> None:
        # Create an email that is exactly 254 chars
        # "a" * 241 + "@example.com" = 241 + 12 = 253 — need 242 for 254
        local_part = "a" * 242
        email_str = f"{local_part}@example.com"
        assert len(email_str) == 254
        email = Email.create(email_str)
        assert email.value == email_str

    def test_rejects_double_at(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("user@@example.com")

    def test_rejects_spaces_in_email(self) -> None:
        with pytest.raises(ValidationError, match="Invalid email format"):
            Email.create("user @example.com")


class TestEmailEquality:
    """Tests for Email equality and hashing."""

    def test_same_emails_are_equal(self) -> None:
        email1 = Email.create("user@example.com")
        email2 = Email.create("user@example.com")
        assert email1 == email2

    def test_different_case_emails_are_equal(self) -> None:
        email1 = Email.create("User@Example.com")
        email2 = Email.create("user@example.com")
        assert email1 == email2

    def test_different_emails_are_not_equal(self) -> None:
        email1 = Email.create("user1@example.com")
        email2 = Email.create("user2@example.com")
        assert email1 != email2

    def test_same_emails_have_same_hash(self) -> None:
        email1 = Email.create("user@example.com")
        email2 = Email.create("USER@example.com")
        assert hash(email1) == hash(email2)

    def test_can_be_used_in_set(self) -> None:
        email1 = Email.create("user@example.com")
        email2 = Email.create("USER@example.com")
        email_set = {email1, email2}
        assert len(email_set) == 1


class TestEmailStr:
    """Tests for Email string representation."""

    def test_str_returns_value(self) -> None:
        email = Email.create("user@example.com")
        assert str(email) == "user@example.com"
