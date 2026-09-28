"""ListAccountTypesUseCase — retrieves paginated account types for a tenant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.accountType.accountTypeOutputDto import AccountTypeOutputDTO
from api.accountType.paginatedAccountTypesDto import (
    PaginatedAccountTypesDTO,
)
from api.common.ports.sharedTypes import PaginationParams
from api.common.tenant.tenantId import TenantId

if TYPE_CHECKING:
    from api.accountType.iAccountTypeRepository import IAccountTypeRepository


class ListAccountTypesUseCase:
    """Application use case for listing account types within a tenant.

    Returns all account types (active and inactive) belonging to the
    requesting user's tenant with cursor-based pagination (max 100 per page).

    Requirements satisfied: 5.4
    """

    def __init__(self, account_type_repository: IAccountTypeRepository) -> None:
        self._account_type_repository = account_type_repository

    async def execute(
        self, tenant_id: str, pagination: PaginationParams
    ) -> PaginatedAccountTypesDTO:
        """Execute the list account types use case.

        Args:
            tenant_id: The tenant UUID to list account types for.
            pagination: Pagination parameters (limit, cursor).

        Returns:
            PaginatedAccountTypesDTO with account type items and pagination cursor.

        Raises:
            ValidationError: If the tenant_id is not a valid UUID.
        """
        # Validate tenant_id format via value object
        validated_tenant_id = TenantId.create(tenant_id)

        # Query repository with tenant isolation and pagination
        result = await self._account_type_repository.find_all_by_tenant(
            tenant_id=validated_tenant_id.value,
            pagination=pagination,
        )

        # Map domain entities to output DTOs
        items = [
            AccountTypeOutputDTO(
                account_type_id=account_type.account_type_id,
                tenant_id=account_type.tenant_id,
                name=account_type.name,
                description=account_type.description,
                config=account_type.config,
                status=account_type.status,
                created_at=account_type.created_at,
                updated_at=account_type.updated_at,
            )
            for account_type in result.items
        ]

        return PaginatedAccountTypesDTO(
            items=items,
            next_key=result.next_cursor,
        )
