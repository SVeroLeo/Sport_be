"""UpdateMemberUseCase — orchestrates updating an existing member."""

from __future__ import annotations

from typing import TYPE_CHECKING

from application.dtos.member.member_output_dto import MemberOutputDTO
from application.dtos.member.update_member_input_dto import UpdateMemberInputDTO
from domain.errors.domain_error import DomainError
from domain.errors.not_found_error import NotFoundError
from domain.value_objects.tenant_id import TenantId

if TYPE_CHECKING:
    from application.ports.i_account_type_repository import IAccountTypeRepository
    from application.ports.i_member_repository import IMemberRepository


class UpdateMemberUseCase:
    """Application use case for updating an existing member.

    Orchestrates:
    1. Validate tenant_id format.
    2. Find existing member by tenant_id + member_id (NotFoundError if missing).
    3. If account_type is being changed, validate the new type exists and is active.
    4. Apply updates via Member.update() (preserves immutable fields, refreshes updated_at).
    5. Persist via repository.update().
    6. Map to MemberOutputDTO and return.

    Requirements satisfied: 7.1, 7.2, 7.3, 7.4, 7.5
    """

    def __init__(
        self,
        member_repository: IMemberRepository,
        account_type_repository: IAccountTypeRepository,
    ) -> None:
        self._member_repository = member_repository
        self._account_type_repository = account_type_repository

    async def execute(self, input_dto: UpdateMemberInputDTO) -> MemberOutputDTO:
        """Execute the update member use case.

        Args:
            input_dto: UpdateMemberInputDTO containing tenant_id, member_id,
                       and optional account_type, full_name, email, status, metadata.

        Returns:
            MemberOutputDTO with the updated member data.

        Raises:
            ValidationError: If tenant_id is not a valid UUID.
            NotFoundError: If the member does not exist in the tenant.
            NotFoundError: If the new account type does not exist in the tenant.
            DomainError: If the new account type is inactive.
        """
        # 1. Validate tenant_id format
        TenantId.create(input_dto.tenant_id)

        # 2. Find existing member by tenant_id + member_id
        existing = self._member_repository.find_by_id(
            tenant_id=input_dto.tenant_id,
            member_id=input_dto.member_id,
        )
        if existing is None:
            raise NotFoundError("Member not found", resource="member")

        # 3. If account_type is being changed, validate it exists and is active
        new_account_type_id: str | None = None
        if input_dto.account_type is not None:
            account_type = await self._account_type_repository.find_by_name_in_tenant(
                tenant_id=input_dto.tenant_id,
                name=input_dto.account_type,
            )
            if account_type is None:
                raise NotFoundError(
                    "Account type does not exist in this tenant",
                    resource="account_type",
                )
            if account_type.status != "active":
                raise DomainError("Account type is not active")
            new_account_type_id = account_type.account_type_id

        # 4. Apply updates via Member.update() — preserves immutable fields, refreshes updated_at
        updated_member = existing.update(
            account_type=input_dto.account_type,
            account_type_id=new_account_type_id,
            full_name=input_dto.full_name,
            email=input_dto.email,
            status=input_dto.status,
            metadata=input_dto.metadata,
        )

        # 5. Persist via repository.update()
        persisted = self._member_repository.update(updated_member)

        # 6. Map to MemberOutputDTO and return
        return MemberOutputDTO(
            member_id=persisted.member_id,
            tenant_id=persisted.tenant_id,
            user_id=persisted.user_id,
            account_type=persisted.account_type,
            account_type_id=persisted.account_type_id,
            full_name=persisted.full_name,
            email=persisted.email,
            status=persisted.status,
            registration_type=persisted.registration_type,
            invited_by=persisted.invited_by,
            metadata=persisted.metadata,
            created_at=persisted.created_at,
            updated_at=persisted.updated_at,
        )
