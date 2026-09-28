"""ListMembersUseCase — retrieves paginated members for a tenant with optional filters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.member.memberOutputDto import MemberOutputDTO
from api.member.paginatedMembersDto import PaginatedMembersDTO
from api.common.ports.sharedTypes import MemberFilters, PaginationParams
from api.common.tenant.tenantId import TenantId

if TYPE_CHECKING:
    from api.member.iMemberRepository import IMemberRepository


class ListMembersUseCase:
    """Application use case for listing members within a tenant.

    Supports optional filtering by account_type (case-insensitive) and
    status (exact match), with cursor-based pagination (max 100 per page).

    Requirements satisfied: 6.1, 6.2, 6.3, 6.4, 6.5
    """

    def __init__(self, member_repository: IMemberRepository) -> None:
        self._member_repository = member_repository

    async def execute(
        self,
        tenant_id: str,
        filters: MemberFilters,
        pagination: PaginationParams,
    ) -> PaginatedMembersDTO:
        """Execute the list members use case.

        Args:
            tenant_id: The tenant UUID to list members for.
            filters: Optional filtering criteria (account_type, status).
            pagination: Pagination parameters (limit, cursor).

        Returns:
            PaginatedMembersDTO with member items and pagination cursor.

        Raises:
            ValidationError: If the tenant_id is not a valid UUID.
        """
        # Validate tenant_id format via value object
        validated_tenant_id = TenantId.create(tenant_id)

        # Query repository with tenant isolation, filters, and pagination
        result = await self._member_repository.find_by_tenant_and_filters(
            tenant_id=validated_tenant_id.value,
            filters=filters,
            pagination=pagination,
        )

        # Map domain entities to output DTOs
        items = [
            MemberOutputDTO(
                member_id=member.member_id,
                tenant_id=member.tenant_id,
                user_id=member.user_id,
                account_type=member.account_type,
                account_type_id=member.account_type_id,
                full_name=member.full_name,
                email=member.email,
                status=member.status,
                registration_type=member.registration_type,
                invited_by=member.invited_by,
                metadata=member.metadata,
                created_at=member.created_at,
                updated_at=member.updated_at,
            )
            for member in result.items
        ]

        return PaginatedMembersDTO(
            items=items,
            next_key=result.next_cursor,
        )
