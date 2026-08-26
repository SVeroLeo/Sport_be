"""AccountTypeId value object — UUID-based identifier for account types."""

from __future__ import annotations

import uuid

from domain.errors.validation_error import ValidationError


class AccountTypeId:
    """Immutable value object representing an account type identifier (UUID)."""

    __slots__ = ("_value",)
    _value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", value)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    @property
    def value(self) -> str:
        return self._value

    @staticmethod
    def create(value: str) -> AccountTypeId:
        """Create an AccountTypeId from a string, validating UUID format."""
        if not value or not value.strip():
            raise ValidationError("Invalid account type ID", field="account_type_id")
        try:
            parsed = uuid.UUID(value.strip())
        except (ValueError, AttributeError):
            raise ValidationError("Invalid account type ID", field="account_type_id") from None
        return AccountTypeId(str(parsed))

    @staticmethod
    def generate() -> AccountTypeId:
        """Generate a new random AccountTypeId."""
        return AccountTypeId(str(uuid.uuid4()))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AccountTypeId):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"AccountTypeId({self._value!r})"

    def __str__(self) -> str:
        return self._value
