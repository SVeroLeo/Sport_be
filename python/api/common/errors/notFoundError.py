"""Not found error for missing resources."""

from api.common.errors.domainError import DomainError


class NotFoundError(DomainError):
    """Raised when a requested resource does not exist."""

    def __init__(self, message: str, resource: str | None = None) -> None:
        self.resource = resource
        super().__init__(message)
