"""Tenant not found error."""

from api.common.errors.domainError import DomainError


class TenantNotFoundError(DomainError):
    """Raised when a tenant does not exist."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        super().__init__(f"Tenant not found: {tenant_id}")
