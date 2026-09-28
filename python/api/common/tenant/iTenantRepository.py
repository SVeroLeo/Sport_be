"""ITenantRepository port — defines the contract for tenant persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from api.common.tenant.tenant import Tenant


class ITenantRepository(ABC):
    """Abstract port defining tenant repository operations.

    Infrastructure implementations must satisfy this contract.
    Tenants are read-only from the application perspective — they
    are managed externally, and this system only validates their state.
    """

    @abstractmethod
    async def find_by_id(self, tenant_id: str) -> Tenant | None:
        """Find a tenant by its ID.

        Args:
            tenant_id: The tenant UUID to look up.

        Returns:
            The Tenant entity if found, or None.
        """
