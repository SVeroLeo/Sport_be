"""IUserRepository port — defines the contract for user persistence operations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.member import Member
from domain.entities.tenant_membership import TenantMembership
from domain.entities.user import User
from domain.entities.user_role import UserRole
from domain.value_objects.email import Email


class IUserRepository(ABC):
    """Abstract port defining user persistence operations.

    Use cases depend on this interface (Dependency Inversion Principle).
    Infrastructure layer provides the concrete implementation (e.g., DynamoDB).
    """

    @abstractmethod
    def find_by_email(self, email: Email) -> User | None:
        """Find a user by their email address.

        Args:
            email: Validated Email value object.

        Returns:
            The User entity if found, None otherwise.
        """

    @abstractmethod
    def find_by_id(self, user_id: str) -> User | None:
        """Find a user by their unique identifier.

        Args:
            user_id: UUID string of the user.

        Returns:
            The User entity if found, None otherwise.
        """

    @abstractmethod
    def save(self, user: User) -> User:
        """Persist a user entity (create or update).

        Args:
            user: The User entity to persist.

        Returns:
            The persisted User entity.
        """

    @abstractmethod
    def get_roles_for_tenant(self, user_id: str, tenant_id: str) -> list[UserRole]:
        """Get all roles assigned to a user within a specific tenant.

        Args:
            user_id: UUID string of the user.
            tenant_id: UUID string of the tenant.

        Returns:
            List of UserRole entities for the user in the given tenant.
        """

    @abstractmethod
    def register_with_membership(
        self,
        user: User,
        membership: TenantMembership,
        member: Member,
        role: UserRole,
    ) -> None:
        """Atomically create User, TenantMembership, Member, and Role records.

        Used by self-registration flow. All records are persisted in a single
        transaction — if any part fails, no records are created.

        Args:
            user: The new User entity.
            membership: The TenantMembership linking user to tenant.
            member: The Member entity within the tenant.
            role: The default role assignment (typically "viewer").

        Raises:
            Domain or infrastructure errors if the transaction fails.
        """

    @abstractmethod
    def create_user_with_membership(
        self,
        user: User,
        membership: TenantMembership,
        member: Member,
        roles: list[UserRole],
    ) -> None:
        """Atomically create User, TenantMembership, Member, and multiple Roles.

        Used by admin-invited member creation when the user does not yet exist.
        All records are persisted in a single transaction — if any part fails,
        no records are created.

        Args:
            user: The new User entity (status: pending_confirmation).
            membership: The TenantMembership linking user to tenant.
            member: The Member entity within the tenant.
            roles: List of role assignments for the user in the tenant.

        Raises:
            Domain or infrastructure errors if the transaction fails.
        """

    @abstractmethod
    def find_by_cognito_sub(self, cognito_sub: str) -> User | None:
        """Find a user by their Cognito subject identifier.

        Used by the social-login callback flow to detect a returning
        federated user before falling back to email-based lookup.

        Args:
            cognito_sub: The Cognito ``sub`` claim of the user.

        Returns:
            The User entity if found, None otherwise.
        """

    @abstractmethod
    def register_social_user(
        self,
        user: User,
        membership: TenantMembership | None,
        member: Member | None,
        role: UserRole | None,
    ) -> None:
        """Atomically provision a social-login user (idempotently).

        Writes the User record with an ``attribute_not_exists(PK)`` condition so
        that a repeated OAuth callback does not create duplicate records — a
        failing condition check is treated as success. The membership, member,
        and role records are only written when the tenant is known at
        provisioning time; when the tenant cannot be resolved they are omitted
        and the user is left in a pending-tenant state.

        Args:
            user: The new social User entity (registration_type="social").
            membership: The TenantMembership linking user to tenant, or None
                when the tenant is not yet known.
            member: The Member entity within the tenant, or None when the
                tenant is not yet known.
            role: The default role assignment, or None when the tenant is not
                yet known.

        Raises:
            Domain or infrastructure errors if the transaction fails for a
            reason other than the idempotency condition check.
        """

    @abstractmethod
    def associate_tenant(
        self,
        user_id: str,
        membership: TenantMembership,
        member: Member,
        role: UserRole,
        new_status: str,
        new_default_tenant_id: str,
    ) -> None:
        """Atomically associate a pending-tenant user with a tenant.

        Writes the TenantMembership, Member, and UserRole records and updates
        the existing User's ``status`` and ``default_tenant_id`` in a single
        transaction — if any part fails, no changes are applied.

        Args:
            user_id: UUID string of the user being associated.
            membership: The TenantMembership linking user to tenant.
            member: The Member entity within the tenant.
            role: The role assignment (typically "viewer").
            new_status: The status to set on the User (e.g. "active").
            new_default_tenant_id: The tenant id to set as the User's default.

        Raises:
            Domain or infrastructure errors if the transaction fails.
        """
