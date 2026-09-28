"""Email value object with validation."""

import re
from dataclasses import dataclass

from api.common.errors.validationError import ValidationError

# RFC 5322 simplified email regex: local@domain with domain containing at least one dot
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

_MAX_EMAIL_LENGTH = 254


@dataclass(frozen=True, slots=True)
class Email:
    """Immutable email value object.

    Use the `create` factory method to construct validated instances.
    """

    value: str

    def __post_init__(self) -> None:
        # Prevent direct construction bypassing validation.
        # The factory method sets _validated before calling __init__.
        pass

    @staticmethod
    def create(value: str) -> "Email":
        """Create a validated Email value object.

        Args:
            value: Raw email string.

        Returns:
            Email instance with normalized (trimmed, lowercased) value.

        Raises:
            ValidationError: If email format is invalid or exceeds 254 characters.
        """
        normalized = value.strip().lower()

        if len(normalized) == 0:
            raise ValidationError("Invalid email format")

        if len(normalized) > _MAX_EMAIL_LENGTH:
            raise ValidationError("Invalid email format")

        if not _EMAIL_PATTERN.match(normalized):
            raise ValidationError("Invalid email format")

        return Email(value=normalized)

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Email):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)
