"""IMemberRepository port — defines the contract for member persistence operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.common.ports.sharedTypes import MemberFilters, PaginatedResult, PaginationParams
    from api.member.member import Member
    from api.common.tenant.tenantMembership import TenantMembership
    from api.common.user.userRole import UserRole


class IMemberRepository(ABC):
    """Abstract port defining persistence operations for Member entities.

    Use cases depend on this interface to query and persist members.
    Infrastructure implementations (e.g., DynamoDB) satisfy this contract.
    """

    @abstractmethod
    def find_by_id(self, tenant_id: str, member_id: str) -> Member | None:
        """Find a member by tenant and member ID.

        Args:
            tenant_id: UUID of the tenant.
            member_id: UUID of the member.

        Returns:
            The Member entity if found, otherwise None.
        """

    @abstractmethod
    def find_by_user_in_tenant(self, tenant_id: str, user_id: str) -> Member | None:
        """Find a member by user ID within a specific tenant.

        Used to check if a user is already a member of a tenant (Req 4.4).

        Args:
            tenant_id: UUID of the tenant.
            user_id: UUID of the user.

        Returns:
            The Member entity if found, otherwise None.
        """

    @abstractmethod
    def find_by_tenant_and_filters(
        self,
        tenant_id: str,
        filters: MemberFilters,
        pagination: PaginationParams,
    ) -> PaginatedResult[Member]:
        """Query members within a tenant with optional filters and pagination.

        Supports filtering by:
        - account_type: case-insensitive match (Req 6.2)
        - status: exact match (Req 6.3)

        Pagination is cursor-based with a configurable page size (max 100).

        Args:
            tenant_id: UUID of the tenant.
            filters: Optional filtering criteria.
            pagination: Pagination parameters (limit and cursor).

        Returns:
            A paginated result containing the matching members and a
            next_cursor if more pages exist.
        """

    @abstractmethod
    def save(self, member: Member) -> Member:
        """Persist a new member entity.

        Args:
            member: The Member entity to persist.

        Returns:
            The persisted Member entity.
        """

    @abstractmethod
    def update(self, member: Member) -> Member:
        """Update an existing member entity.

        Args:
            member: The Member entity with updated fields.

        Returns:
            The updated Member entity.
        """

    @abstractmethod
    def create_member_with_roles(
        self,
        membership: TenantMembership,
        member: Member,
        roles: list[UserRole],
    ) -> None:
        """Atomically create a tenant membership, member, and role assignments.

        This operation must be transactional — either all records are persisted
        or none are (Req 12.2). Used during admin-invited member creation when
        the user already exists in the system.

        Args:
            membership: The TenantMembership linking user to tenant.
            member: The Member entity to create.
            roles: List of UserRole assignments for the member.

        Raises:
            Exception: If the atomic transaction fails (implementation-specific).
        """

    @abstractmethod
    def count_active_by_account_type(self, tenant_id: str, account_type_name: str) -> int:
        """Count active members using a specific account type within a tenant.

        Used to prevent deletion of account types that have active members
        assigned (Req 5.7).

        Args:
            tenant_id: UUID of the tenant.
            account_type_name: Name of the account type to check.

        Returns:
            The number of active members using the specified account type.
        """
