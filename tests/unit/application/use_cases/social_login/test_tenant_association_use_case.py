"""Unit tests for TenantAssociationUseCase.

Example-based tests covering the select-tenant use case that associates a
pending-tenant social user with a tenant:

* A missing or inactive tenant raises ``NotFoundError("tenant_not_found")``,
  which the HTTP layer maps to 404 (Req 5.4).
* A user that is already a member of the tenant raises
  ``ConflictError("already_member")``, mapped to 409 (Req 5.5).
* A successful association persists the records atomically and returns the
  updated user data as a ``TenantAssociationOutputDTO`` (Req 5.3, 5.6).

The named property test for this use case (Property 9) lives in its own file;
these are standard pytest example tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.dtos.social_login_dtos import TenantAssociationOutputDTO
from application.use_cases.tenant_association_use_case import (
    TenantAssociationUseCase,
)
from domain.entities.account_type import AccountType
from domain.entities.tenant import Tenant
from domain.entities.user import User
from domain.errors.conflict_error import ConflictError
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError
from domain.value_objects.tenant_id import TenantId

# ──── Constants ───────────────────────────────────────────────────────────────

USER_ID = "9f0c6a2e-1c3b-4d5e-8f7a-0b1c2d3e4f5a"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
ACCOUNT_TYPE_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
USER_EMAIL = "social.user@example.com"


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def user_repository() -> MagicMock:
    """Mock IUserRepository (sync methods: find_by_id, associate_tenant)."""
    return MagicMock()


@pytest.fixture
def tenant_repository() -> AsyncMock:
    """Mock ITenantRepository (async find_by_id)."""
    return AsyncMock()


@pytest.fixture
def member_repository() -> MagicMock:
    """Mock IMemberRepository (sync find_by_user_in_tenant)."""
    mock = MagicMock()
    mock.find_by_user_in_tenant.return_value = None  # Not a member by default
    return mock


@pytest.fixture
def account_type_repository() -> AsyncMock:
    """Mock IAccountTypeRepository (async find_by_name_in_tenant)."""
    return AsyncMock()


@pytest.fixture
def pending_user() -> User:
    """A social user awaiting tenant selection (status == 'pending_tenant')."""
    return User.reconstitute(
        user_id=USER_ID,
        email=USER_EMAIL,
        cognito_sub="cognito-sub-social-abc",
        full_name="Social User",
        status="pending_tenant",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        default_tenant_id=None,
        registration_type="social",
    )


@pytest.fixture
def active_tenant() -> Tenant:
    """An active tenant with a configured default account type."""
    return Tenant.create(
        tenant_id=TenantId.create(TENANT_ID),
        name="Club Deportivo Test",
        plan="premium",
        status="active",
        allow_self_registration=True,
        default_account_type="socio",
    )


@pytest.fixture
def active_account_type() -> AccountType:
    """The active account type resolved for the new member record."""
    return AccountType.reconstitute(
        account_type_id=ACCOUNT_TYPE_ID,
        tenant_id=TENANT_ID,
        name="socio",
        description="Socio membership",
        config=None,
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def use_case(
    user_repository: MagicMock,
    tenant_repository: AsyncMock,
    member_repository: MagicMock,
    account_type_repository: AsyncMock,
) -> TenantAssociationUseCase:
    """Create a TenantAssociationUseCase with mocked dependencies."""
    return TenantAssociationUseCase(
        user_repository,
        tenant_repository,
        member_repository,
        account_type_repository,
    )


# ──── Test: Tenant Not Found / Inactive (Req 5.4 — HTTP 404) ─────────────────


class TestTenantNotFound:
    """Missing or inactive tenant raises NotFoundError('tenant_not_found')."""

    @pytest.mark.asyncio
    async def test_nonexistent_tenant_raises_not_found(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        pending_user: User,
    ) -> None:
        """A tenant that does not exist raises NotFoundError with code 'tenant_not_found'."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(USER_ID, TENANT_ID)

        assert exc_info.value.message == "tenant_not_found"
        assert exc_info.value.resource == "tenant"

    @pytest.mark.asyncio
    async def test_inactive_tenant_raises_not_found(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        pending_user: User,
    ) -> None:
        """An inactive tenant is treated as not found (code 'tenant_not_found')."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = Tenant.create(
            tenant_id=TenantId.create(TENANT_ID),
            name="Inactive Club",
            status="inactive",
        )

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(USER_ID, TENANT_ID)

        assert exc_info.value.message == "tenant_not_found"

    @pytest.mark.asyncio
    async def test_tenant_not_found_does_not_persist(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        member_repository: MagicMock,
        pending_user: User,
    ) -> None:
        """When the tenant is missing, no membership is checked or persisted."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await use_case.execute(USER_ID, TENANT_ID)

        member_repository.find_by_user_in_tenant.assert_not_called()
        user_repository.associate_tenant.assert_not_called()


# ──── Test: Missing User (NotFoundError) / Non-Pending (ValidationError) ─────


class TestUserPreconditions:
    """User must exist and be in the pending_tenant state."""

    @pytest.mark.asyncio
    async def test_missing_user_raises_not_found(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
    ) -> None:
        """A user that does not exist raises NotFoundError('user_not_found')."""
        user_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(USER_ID, TENANT_ID)

        assert exc_info.value.message == "user_not_found"
        assert exc_info.value.resource == "user"
        # The tenant is never looked up when the user is missing.
        tenant_repository.find_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_pending_user_raises_validation_error(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
    ) -> None:
        """An already-active user is not awaiting tenant selection -> ValidationError."""
        active_user = User.reconstitute(
            user_id=USER_ID,
            email=USER_EMAIL,
            cognito_sub="cognito-sub-social-abc",
            full_name="Social User",
            status="active",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            default_tenant_id=TENANT_ID,
            registration_type="social",
        )
        user_repository.find_by_id.return_value = active_user

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(USER_ID, TENANT_ID)

        assert exc_info.value.field == "status"
        tenant_repository.find_by_id.assert_not_called()


# ──── Test: Already a Member (Req 5.5 — HTTP 409) ────────────────────────────


class TestAlreadyMember:
    """A user already in the tenant raises ConflictError('already_member')."""

    @pytest.mark.asyncio
    async def test_existing_membership_raises_conflict(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        member_repository: MagicMock,
        pending_user: User,
        active_tenant: Tenant,
    ) -> None:
        """When find_by_user_in_tenant returns a member, ConflictError is raised."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = active_tenant
        member_repository.find_by_user_in_tenant.return_value = MagicMock()

        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(USER_ID, TENANT_ID)

        assert exc_info.value.message == "already_member"
        assert exc_info.value.resource == "member"

    @pytest.mark.asyncio
    async def test_already_member_does_not_persist(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        member_repository: MagicMock,
        pending_user: User,
        active_tenant: Tenant,
    ) -> None:
        """A conflicting membership short-circuits before any writes occur."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = active_tenant
        member_repository.find_by_user_in_tenant.return_value = MagicMock()

        with pytest.raises(ConflictError):
            await use_case.execute(USER_ID, TENANT_ID)

        user_repository.associate_tenant.assert_not_called()

    @pytest.mark.asyncio
    async def test_membership_looked_up_with_user_and_tenant(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        member_repository: MagicMock,
        account_type_repository: AsyncMock,
        pending_user: User,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """The membership check is scoped to the requesting user and chosen tenant."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        await use_case.execute(USER_ID, TENANT_ID)

        member_repository.find_by_user_in_tenant.assert_called_once_with(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
        )


# ──── Test: Successful Association (Req 5.3, 5.6 — HTTP 200) ─────────────────


class TestSuccessfulAssociation:
    """Successful association persists records and returns updated user data."""

    @pytest.mark.asyncio
    async def test_success_returns_updated_user_dto(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        pending_user: User,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """A successful association returns the user's updated state as a DTO."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        result = await use_case.execute(USER_ID, TENANT_ID)

        assert isinstance(result, TenantAssociationOutputDTO)
        assert result.user_id == USER_ID
        assert result.email == USER_EMAIL
        assert result.default_tenant_id == TENANT_ID
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_success_persists_records_atomically(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        pending_user: User,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """associate_tenant is called once with the new active status and tenant."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        await use_case.execute(USER_ID, TENANT_ID)

        user_repository.associate_tenant.assert_called_once()
        _, kwargs = user_repository.associate_tenant.call_args
        assert kwargs["user_id"] == USER_ID
        assert kwargs["new_status"] == "active"
        assert kwargs["new_default_tenant_id"] == TENANT_ID
        # The membership, member, and role records are all provided.
        assert kwargs["membership"] is not None
        assert kwargs["member"] is not None
        assert kwargs["role"] is not None

    @pytest.mark.asyncio
    async def test_success_builds_social_member_with_user_details(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        pending_user: User,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """The Member record carries the user's name/email and social registration."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        await use_case.execute(USER_ID, TENANT_ID)

        _, kwargs = user_repository.associate_tenant.call_args
        member = kwargs["member"]
        assert member.email == USER_EMAIL
        assert member.full_name == "Social User"
        assert member.registration_type == "social"
        assert member.account_type == "socio"

    @pytest.mark.asyncio
    async def test_success_resolves_tenant_default_account_type(
        self,
        use_case: TenantAssociationUseCase,
        user_repository: MagicMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        pending_user: User,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """The tenant's default account type is resolved within the chosen tenant."""
        user_repository.find_by_id.return_value = pending_user
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        await use_case.execute(USER_ID, TENANT_ID)

        account_type_repository.find_by_name_in_tenant.assert_awaited_with(
            tenant_id=TENANT_ID,
            name="socio",
        )
