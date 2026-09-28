"""Validation error for domain value objects."""

from api.common.errors.domainError import DomainError


class ValidationError(DomainError):
    """Raised when a value object receives invalid input."""

    def __init__(self, message: str, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)
