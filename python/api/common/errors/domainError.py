"""Base domain error class."""


class DomainError(Exception):
    """Base class for all domain-level errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
