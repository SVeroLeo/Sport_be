"""Rate limit error for throttled operations."""

from domain.errors.domain_error import DomainError


class RateLimitError(DomainError):
    """Raised when an operation is throttled due to too many requests."""

    def __init__(self, message: str = "Too many requests, please try again later") -> None:
        super().__init__(message)
