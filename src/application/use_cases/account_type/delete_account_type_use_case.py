"""DeleteAccountTypeUseCase — soft-deletes an account type after verifying no active members use it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.errors.domain_error import DomainError
from domain.errors.not_found_error import NotFoundError
from domain.value_objects.tenant_id import TenantId

if TYPE_CHECKING:
    from application.ports.i_account_type_repository import IAccountTypeRepository
    from application.ports.i_member_repository import IMemberRepository


class DeleteAccountTypeUseCase:
    """Application use case for soft-deleting an account type.

    Orchestrates:
    1. Validate tenant_id format via TenantId value object.
    2. Find the account type by id (NotFoundError if missing).
    3. Count active members using this account type name.
    4. If active members exist, reject deletion with a DomainError.
    5. Call account_type.deactivate() to set status to "inactive".
    6. Persist the updated entity via the repository.

    Requirements satisfied: 5.6, 5.7
    """

    def __init__(
        self,
        account_type_repository: IAccountTypeRepository,
        member_repository: IMemberRepository,
    ) -> None:
        self._account_type_repository = account_type_repository
        self._member_repository = member_repository

    async def execute(self, tenant_id: str, account_type_id: str) -> None:
        """Execute the soft-delete use case.

        Args:
            tenant_id: UUID of the tenant that owns the account type.
            account_type_id: UUID of the account type to delete.

        Returns:
            None (void operation).

        Raises:
            ValidationError: If tenant_id is not a valid UUID.
            NotFoundError: If the account type does not exist in the tenant.
            DomainError: If active members are currently using this account type.
        """
        # 1. Validate tenant_id format
        TenantId.create(tenant_id)

        # 2. Find existing account type (Req 5.6)
        existing = await self._account_type_repository.find_by_id(tenant_id, account_type_id)
        if existing is None:
            raise NotFoundError("Account type not found", resource="account_type")

        # 3. Check active members using this account type (Req 5.7)
        active_count = self._member_repository.count_active_by_account_type(
            tenant_id, existing.name.lower()
        )
        if active_count > 0:
            raise DomainError("Cannot delete account type: active members are using it")

        # 4. Soft delete — set status to "inactive" and refresh updated_at
        existing.deactivate()

        # 5. Persist the updated entity
        await self._account_type_repository.update(existing)
