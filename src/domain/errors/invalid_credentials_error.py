"""Invalid credentials error for authentication failures."""

from domain.errors.domain_error import DomainError


class InvalidCredentialsError(DomainError):
    """Raised when authentication credentials are invalid."""

    def __init__(self, message: str = "Invalid credentials") -> None:
        super().__init__(message)
