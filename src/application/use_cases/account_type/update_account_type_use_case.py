"""UpdateAccountTypeUseCase — orchestrates updating an existing account type."""

from __future__ import annotations

from typing import TYPE_CHECKING

from application.dtos.account_type.account_type_output_dto import AccountTypeOutputDTO
from application.dtos.account_type.update_account_type_input_dto import (
    UpdateAccountTypeInputDTO,
)
from domain.errors.conflict_error import ConflictError
from domain.errors.not_found_error import NotFoundError
from domain.value_objects.tenant_id import TenantId

if TYPE_CHECKING:
    from application.ports.i_account_type_repository import IAccountTypeRepository


class UpdateAccountTypeUseCase:
    """Application use case for updating an existing account type.

    Orchestrates:
    1. Validate tenant_id format.
    2. Find existing account type by ID (NotFoundError if missing).
    3. If name is provided and different (case-insensitive), check uniqueness.
    4. Apply updates (name, description, config) to the entity.
    5. Persist via repository.update().
    6. Map to AccountTypeOutputDTO and return.

    Requirements satisfied: 5.5
    """

    def __init__(self, account_type_repository: IAccountTypeRepository) -> None:
        self._account_type_repository = account_type_repository

    async def execute(self, input_dto: UpdateAccountTypeInputDTO) -> AccountTypeOutputDTO:
        """Execute the update account type use case.

        Args:
            input_dto: UpdateAccountTypeInputDTO containing tenant_id,
                       account_type_id, and optional name, description, config.

        Returns:
            AccountTypeOutputDTO with the updated account type data.

        Raises:
            ValidationError: If tenant_id is not a valid UUID.
            NotFoundError: If the account type does not exist.
            ConflictError: If the new name already exists in the tenant.
        """
        # 1. Validate tenant_id format
        TenantId.create(input_dto.tenant_id)

        # 2. Find existing account type by ID
        existing = await self._account_type_repository.find_by_id(
            tenant_id=input_dto.tenant_id,
            account_type_id=input_dto.account_type_id,
        )
        if existing is None:
            raise NotFoundError("Account type not found", resource="account_type")

        # 3. If name is provided and different (case-insensitive), check uniqueness
        if input_dto.name is not None and input_dto.name.strip().lower() != existing.name.lower():
            duplicate = await self._account_type_repository.find_by_name_in_tenant(
                tenant_id=input_dto.tenant_id,
                name=input_dto.name,
            )
            if duplicate is not None and duplicate.account_type_id != existing.account_type_id:
                raise ConflictError(
                    "Account type name already exists in this tenant",
                    resource="account_type",
                )

        # 4. Apply updates to the entity
        if input_dto.name is not None:
            existing.update_name(input_dto.name)
        if input_dto.description is not None:
            existing.update_description(input_dto.description)
        if input_dto.config is not None:
            existing.update_config(input_dto.config)

        # 5. Persist via repository
        updated = await self._account_type_repository.update(existing)

        # 6. Map to output DTO and return
        return AccountTypeOutputDTO(
            account_type_id=updated.account_type_id,
            tenant_id=updated.tenant_id,
            name=updated.name,
            description=updated.description,
            config=updated.config,
            status=updated.status,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )
