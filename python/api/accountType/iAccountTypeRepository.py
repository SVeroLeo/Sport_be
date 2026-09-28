"""IAccountTypeRepository port — defines the contract for account type persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from api.common.ports.sharedTypes import PaginatedResult, PaginationParams
from api.accountType.accountType import AccountType


class IAccountTypeRepository(ABC):
    """Abstract port defining account type repository operations.

    Infrastructure implementations must satisfy this contract.
    All queries are scoped to a single tenant for data isolation.
    """

    @abstractmethod
    async def find_by_id(
        self, tenant_id: str, account_type_id: str
    ) -> AccountType | None:
        """Find an account type by tenant and ID.

        Args:
            tenant_id: The tenant UUID that owns the account type.
            account_type_id: The account type UUID.

        Returns:
            The AccountType entity if found, or None.
        """

    @abstractmethod
    async def find_by_name_in_tenant(
        self, tenant_id: str, name: str
    ) -> AccountType | None:
        """Find an account type by name within a tenant (case-insensitive).

        Used for uniqueness checks when creating or updating account types.

        Args:
            tenant_id: The tenant UUID to search within.
            name: The account type name to look up (case-insensitive).

        Returns:
            The AccountType entity if a matching name exists, or None.
        """

    @abstractmethod
    async def find_all_by_tenant(
        self, tenant_id: str, pagination: PaginationParams
    ) -> PaginatedResult[AccountType]:
        """List all account types for a tenant with pagination.

        Returns both active and inactive account types belonging to
        the specified tenant. Results are paginated with a max of
        100 items per page.

        Args:
            tenant_id: The tenant UUID to list account types for.
            pagination: Pagination parameters (limit, cursor).

        Returns:
            A PaginatedResult containing the account types and an
            optional next_cursor for fetching subsequent pages.
        """

    @abstractmethod
    async def save(self, account_type: AccountType) -> AccountType:
        """Persist a new account type.

        Args:
            account_type: The AccountType entity to persist.

        Returns:
            The persisted AccountType entity.
        """

    @abstractmethod
    async def update(self, account_type: AccountType) -> AccountType:
        """Update an existing account type.

        Args:
            account_type: The AccountType entity with updated fields.

        Returns:
            The updated AccountType entity.
        """
