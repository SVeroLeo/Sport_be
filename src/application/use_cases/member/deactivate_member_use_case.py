"""DeactivateMemberUseCase — deactivates a member and disables their Cognito access."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.errors.not_found_error import NotFoundError
from domain.value_objects.tenant_id import TenantId

if TYPE_CHECKING:
    from application.ports.i_cognito_service import ICognitoService
    from application.ports.i_member_repository import IMemberRepository
    from application.ports.i_user_repository import IUserRepository


class DeactivateMemberUseCase:
    """Application use case for deactivating a member.

    Orchestrates:
    1. Validate tenant_id format via TenantId value object.
    2. Find the member by tenant_id + member_id (NotFoundError if missing).
    3. Call member.deactivate() — raises ValidationError if already inactive,
       otherwise returns new Member with status "inactive" and refreshed updated_at.
    4. Persist the deactivated member via repository.update().
    5. Look up the User by member.user_id to get cognito_sub.
    6. Disable user in Cognito via admin_disable_user to invalidate all tokens.

    The User record is NOT modified or deleted, allowing the user to remain
    active in other tenants.

    Requirements satisfied: 8.1, 8.2, 8.3, 8.4, 8.5
    """

    def __init__(
        self,
        member_repository: IMemberRepository,
        user_repository: IUserRepository,
        cognito_service: ICognitoService,
    ) -> None:
        self._member_repository = member_repository
        self._user_repository = user_repository
        self._cognito_service = cognito_service

    async def execute(self, tenant_id: str, member_id: str) -> None:
        """Execute the member deactivation use case.

        Args:
            tenant_id: UUID of the tenant the member belongs to.
            member_id: UUID of the member to deactivate.

        Returns:
            None (void operation).

        Raises:
            ValidationError: If tenant_id is not a valid UUID, or if the
                member is already inactive.
            NotFoundError: If the member does not exist in the tenant, or
                if the associated user record is not found.
        """
        # 1. Validate tenant_id format
        TenantId.create(tenant_id)

        # 2. Find member (Req 8.3)
        existing = self._member_repository.find_by_id(tenant_id, member_id)
        if existing is None:
            raise NotFoundError("Member not found", resource="member")

        # 3. Deactivate — raises ValidationError if already inactive (Req 8.2)
        deactivated = existing.deactivate()

        # 4. Persist the deactivated member (Req 8.4 — record preserved with all fields)
        self._member_repository.update(deactivated)

        # 5. Look up user to get cognito_sub
        user = self._user_repository.find_by_id(existing.user_id)
        if user is None:
            raise NotFoundError("User not found", resource="user")

        # 6. Disable user in Cognito to revoke all tokens (Req 8.1)
        await self._cognito_service.admin_disable_user(user.cognito_sub)
