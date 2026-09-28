"""CreateAccountTypeUseCase — orchestrates creation of a new account type within a tenant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.accountType.accountTypeOutputDto import AccountTypeOutputDTO
from api.accountType.createAccountTypeInputDto import (
    CreateAccountTypeInputDTO,
)
from api.accountType.accountType import AccountType
from api.common.errors.conflictError import ConflictError
from api.common.errors.notFoundError import NotFoundError
from api.common.tenant.tenantId import TenantId

if TYPE_CHECKING:
    from api.accountType.iAccountTypeRepository import IAccountTypeRepository
    from api.common.tenant.iTenantRepository import ITenantRepository


class CreateAccountTypeUseCase:
    """Application use case for creating a new account type.

    Orchestrates:
    1. Validate tenant_id format via TenantId value object.
    2. Verify tenant exists.
    3. Check name uniqueness within tenant (case-insensitive).
    4. Create AccountType entity with status "active".
    5. Persist the new account type.

    Requirements satisfied: 5.1, 5.2, 5.3
    """

    def __init__(
        self,
        account_type_repository: IAccountTypeRepository,
        tenant_repository: ITenantRepository,
    ) -> None:
        self._account_type_repository = account_type_repository
        self._tenant_repository = tenant_repository

    async def execute(self, input_dto: CreateAccountTypeInputDTO) -> AccountTypeOutputDTO:
        """Execute the create account type use case.

        Args:
            input_dto: CreateAccountTypeInputDTO containing tenant_id, name,
                       description, and config.

        Returns:
            AccountTypeOutputDTO with the created account type data.

        Raises:
            ValidationError: If tenant_id format is invalid or name fails
                             domain validation (empty, exceeds 100 chars).
            NotFoundError: If the tenant does not exist.
            ConflictError: If an account type with the same name already exists
                           in the tenant (case-insensitive).
        """
        # 1. Validate tenant_id format (Req 11.4)
        validated_tenant_id = TenantId.create(input_dto.tenant_id)

        # 2. Verify tenant exists
        tenant = await self._tenant_repository.find_by_id(validated_tenant_id.value)
        if tenant is None:
            raise NotFoundError("Tenant not found", resource="tenant")

        # 3. Check name uniqueness within tenant — case-insensitive (Req 5.2)
        existing = await self._account_type_repository.find_by_name_in_tenant(
            tenant_id=validated_tenant_id.value,
            name=input_dto.name,
        )
        if existing is not None:
            raise ConflictError(
                "Account type name already exists in this tenant",
                resource="account_type",
            )

        # 4. Create domain entity with status "active" (Req 5.1, 5.3)
        # AccountType.create validates name constraints (non-empty, max 100 chars)
        account_type = AccountType.create(
            tenant_id=validated_tenant_id.value,
            name=input_dto.name,
            description=input_dto.description,
            config=input_dto.config,
        )

        # 5. Persist the new account type
        persisted = await self._account_type_repository.save(account_type)

        # 6. Map to output DTO
        return AccountTypeOutputDTO(
            account_type_id=persisted.account_type_id,
            tenant_id=persisted.tenant_id,
            name=persisted.name,
            description=persisted.description,
            config=persisted.config,
            status=persisted.status,
            created_at=persisted.created_at,
            updated_at=persisted.updated_at,
        )
