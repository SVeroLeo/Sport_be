"""Conflict error for duplicate or conflicting operations."""

from domain.errors.domain_error import DomainError


class ConflictError(DomainError):
    """Raised when an operation conflicts with existing state."""

    def __init__(self, message: str, resource: str | None = None) -> None:
        self.resource = resource
        super().__init__(message)
