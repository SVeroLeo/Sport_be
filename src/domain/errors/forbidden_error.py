"""Forbidden error for authorization failures."""

from domain.errors.domain_error import DomainError


class ForbiddenError(DomainError):
    """Raised when a user lacks permission to perform an action."""

    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message)
