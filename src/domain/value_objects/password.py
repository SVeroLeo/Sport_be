"""Password value object with length validation."""

from __future__ import annotations

from typing import Final, cast

from domain.errors.validation_error import ValidationError

MIN_LENGTH: Final[int] = 8
MAX_LENGTH: Final[int] = 72


class Password:
    """Immutable value object representing a validated password.

    Enforces length constraints (8-72 characters) at the domain boundary.
    Does NOT enforce complexity rules — that's Cognito's responsibility.
    Stores the plain text value temporarily during the use case flow;
    actual hashing/storage is done by Cognito in the infrastructure layer.
    """

    __slots__ = ("_value",)
    _value: str

    def __init__(self, value: str) -> None:
        # Private constructor — use create() or create_unsafe()
        object.__setattr__(self, "_value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("Password is immutable")

    def __delattr__(self, _name: str) -> None:
        raise AttributeError("Password is immutable")

    @staticmethod
    def create(value: str) -> Password:
        """Create a Password with validation.

        Validates:
        - Minimum 8 characters
        - Maximum 72 characters (Requirement 13.5)

        Raises:
            ValidationError: If password length is outside 8-72 range.
        """
        if len(value) < MIN_LENGTH:
            raise ValidationError(
                f"Password must be at least {MIN_LENGTH} characters",
                field="password",
            )
        if len(value) > MAX_LENGTH:
            raise ValidationError(
                f"Password must not exceed {MAX_LENGTH} characters",
                field="password",
            )
        return Password(value)

    @staticmethod
    def create_unsafe(value: str) -> Password:
        """Create a Password without validation.

        Used for system-generated passwords (e.g., temporary passwords
        created by AdminCreateUser) that skip domain validation.
        """
        return Password(value)

    @property
    def value(self) -> str:
        """Return the raw password value."""
        return cast("str", object.__getattribute__(self, "_value"))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Password):
            return NotImplemented
        return cast("str", object.__getattribute__(self, "_value")) == cast(
            "str", object.__getattribute__(other, "_value")
        )

    def __hash__(self) -> int:
        return hash(cast("str", object.__getattribute__(self, "_value")))

    def __repr__(self) -> str:
        return "Password(***)"

    def __str__(self) -> str:
        return "***"
