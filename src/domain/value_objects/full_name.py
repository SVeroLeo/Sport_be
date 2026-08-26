"""FullName value object — non-empty, max 200 characters."""

from __future__ import annotations

from domain.errors.validation_error import ValidationError

_MAX_LENGTH = 200


class FullName:
    """Immutable value object representing a person's full name.

    Must be non-empty after trimming and at most 200 characters.
    """

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
    def create(value: str) -> FullName:
        """Create a FullName from a string, validating constraints."""
        if not value or not value.strip():
            raise ValidationError("Full name cannot be empty", field="full_name")
        trimmed = value.strip()
        if len(trimmed) > _MAX_LENGTH:
            raise ValidationError(
                f"Full name cannot exceed {_MAX_LENGTH} characters",
                field="full_name",
            )
        return FullName(trimmed)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FullName):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"FullName({self._value!r})"

    def __str__(self) -> str:
        return self._value
