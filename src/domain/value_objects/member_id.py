"""MemberId value object — UUID-based identifier for members."""

from __future__ import annotations

import uuid

from domain.errors.validation_error import ValidationError


class MemberId:
    """Immutable value object representing a member identifier (UUID)."""

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
    def create(value: str) -> MemberId:
        """Create a MemberId from a string, validating UUID format."""
        if not value or not value.strip():
            raise ValidationError("Invalid member ID", field="member_id")
        try:
            parsed = uuid.UUID(value.strip())
        except (ValueError, AttributeError):
            raise ValidationError("Invalid member ID", field="member_id") from None
        return MemberId(str(parsed))

    @staticmethod
    def generate() -> MemberId:
        """Generate a new random MemberId."""
        return MemberId(str(uuid.uuid4()))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MemberId):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"MemberId({self._value!r})"

    def __str__(self) -> str:
        return self._value
