"""Unit tests for InviteUserUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.dtos.member.create_member_input_dto import CreateMemberInputDTO
from application.use_cases.registration.invite_user_use_case import InviteUserUseCase
from domain.entities.account_type import AccountType
from domain.entities.member import Member
from domain.entities.user import User
from domain.errors.conflict_error import ConflictError
from domain.errors.domain_error import DomainError
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError


# ──── Fixtures ────────────────────────────────────────────────────────────────

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
ACCOUNT_TYPE_ID = "660e8400-e29b-41d4-a716-446655440001"
ADMIN_USER_ID = "770e8400-e29b-41d4-a716-446655440002"


@pytest.fixture
def user_repository() -> MagicMock:
    """Mock IUserRepository with sync methods."""
    return MagicMock()


@pytest.fixture
def member_repository() -> MagicMock:
    """Mock IMemberRepository with sync methods."""
    return MagicMock()


@pytest.fixture
def account_type_repository() -> AsyncMock:
    """Mock IAccountTypeRepository with async methods."""
    return AsyncMock()


@pytest.fixture
def cognito_service() -> AsyncMock:
    """Mock ICognitoService with async methods."""
    return AsyncMock()


@pytest.fixture
def use_case(
    user_repository: MagicMock,
    member_repository: MagicMock,
    account_type_repository: AsyncMock,
    cognito_service: AsyncMock,
) -> InviteUserUseCase:
    """Create an InviteUserUseCase with mocked dependencies."""
    return InviteUserUseCase(
        user_repository=user_repository,
        member_repository=member_repository,
        account_type_repository=account_type_repository,
        cognito_service=cognito_service,
    )


@pytest.fixture
def valid_input() -> CreateMemberInputDTO:
    """Valid input DTO for inviting a member."""
    return CreateMemberInputDTO(
        tenant_id=TENANT_ID,
        email="newuser@example.com",
        full_name="Jane Smith",
        account_type="socio",
        roles=["admin", "viewer"],
    )


@pytest.fixture
def active_account_type() -> AccountType:
    """Sample active account type."""
    return AccountType.reconstitute(
        account_type_id=ACCOUNT_TYPE_ID,
        tenant_id=TENANT_ID,
        name="socio",
        description="Asociado",
        config=None,
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def inactive_account_type() -> AccountType:
    """Sample inactive account type."""
    return AccountType.reconstitute(
        account_type_id="880e8400-e29b-41d4-a716-446655440003",
        tenant_id=TENANT_ID,
        name="profesional",
        description="Profesional",
        config=None,
        status="inactive",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def existing_user() -> User:
    """Sample existing user entity."""
    return User.reconstitute(
        user_id="aa0e8400-e29b-41d4-a716-446655440005",
        email="existing@example.com",
        cognito_sub="cognito-sub-existing",
        full_name="Existing User",
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def existing_member() -> Member:
    """Sample existing member for conflict scenarios."""
    return Member.reconstitute(
        member_id="990e8400-e29b-41d4-a716-446655440004",
        tenant_id=TENANT_ID,
        user_id="aa0e8400-e29b-41d4-a716-446655440005",
        account_type="socio",
        account_type_id=ACCOUNT_TYPE_ID,
        full_name="Existing User",
        email="existing@example.com",
        status="active",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


# ──── Test: Successful Invitation of New User (Req 4.1, 4.2) ─────────────────


class TestInviteNewUser:
    """Tests for successful invitation of a user who does not yet exist."""

    @pytest.mark.asyncio
    async def test_new_user_creates_cognito_user_and_persists_atomically(
        self,
        use_case: InviteUserUseCase,
        valid_input: CreateMemberInputDTO,
        account_type_repository: AsyncMock,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        active_account_type: AccountType,
    ) -> None:
        """New user: creates in Cognito and persists User+Membership+Member+Roles atomically."""
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type
        user_repository.find_by_email.return_value = None
        cognito_service.admin_create_user.return_value = "cognito-sub-new"

        result = await use_case.execute(valid_input, ADMIN_USER_ID)

        # Cognito was called
        cognito_service.admin_create_user.assert_called_once_with(
            email="newuser@example.com",
            full_name="Jane Smith",
        )
        # Atomic persistence via user repository
        user_repository.create_user_with_membership.assert_called_once()
        call_kwargs = user_repository.create_user_with_membership.call_args
        user_arg = call_kwargs.kwargs["user"] if call_kwargs.kwargs else call_kwargs[1]["user"] if len(call_kwargs) > 1 else call_kwargs[0][0]

        # Verify output
        assert result.email == "newuser@example.com"
        assert result.full_name == "Jane Smith"
        assert result.tenant_id == TENANT_ID
        assert result.account_type == "socio"
        assert result.account_type_id == ACCOUNT_TYPE_ID
        assert result.status == "active"
        assert result.registration_type == "invited"
        assert result.invited_by == ADMIN_USER_ID

    @pytest.mark.asyncio
    async def test_new_user_has_pending_confirmation_status(
        self,
        use_case: InviteUserUseCase,
        valid_input: CreateMemberInputDTO,
        account_type_repository: AsyncMock,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        active_account_type: AccountType,
    ) -> None:
        """New user is created with status 'pending_confirmation'."""
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type
        user_repository.find_by_email.return_value = None
        cognito_service.admin_create_user.return_value = "cognito-sub-new"

        await use_case.execute(valid_input, ADMIN_USER_ID)

        call_args = user_repository.create_user_with_membership.call_args
        user_entity = call_args.kwargs.get("user") or call_args[1].get("user")
        assert user_entity.status == "pending_confirmation"

    @pytest.mark.asyncio
    async def test_new_user_member_has_active_status(
        self,
        use_case: InviteUserUseCase,
        valid_input: CreateMemberInputDTO,
        account_type_repository: AsyncMock,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        active_account_type: AccountType,
    ) -> None:
        """Member created for new user has status 'active'."""
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type
        user_repository.find_by_email.return_value = None
        cognito_service.admin_create_user.return_value = "cognito-sub-new"

        result = await use_case.execute(valid_input, ADMIN_USER_ID)

        assert result.status == "active"


# ──── Test: Successful Invitation of Existing User (Req 4.3) ──────────────────


class TestInviteExistingUser:
    """Tests for successful invitation of an existing user not in the tenant."""

    @pytest.mark.asyncio
    async def test_existing_user_skips_cognito_and_creates_member_only(
        self,
        use_case: InviteUserUseCase,
        account_type_repository: AsyncMock,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        active_account_type: AccountType,
        existing_user: User,
    ) -> None:
        """Existing user: no Cognito call, creates Membership+Member+Roles atomically."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="existing@example.com",
            full_name="Existing User",
            account_type="socio",
            roles=["viewer"],
        )
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type
        user_repository.find_by_email.return_value = existing_user
        member_repository.find_by_user_in_tenant.return_value = None

        result = await use_case.execute(input_dto, ADMIN_USER_ID)

        # Cognito NOT called
        cognito_service.admin_create_user.assert_not_called()
        # Member repository used for atomic creation
        member_repository.create_member_with_roles.assert_called_once()
        # user_repository.create_user_with_membership NOT called
        user_repository.create_user_with_membership.assert_not_called()
        # Verify output
        assert result.email == "existing@example.com"
        assert result.user_id == "aa0e8400-e29b-41d4-a716-446655440005"
        assert result.registration_type == "invited"
        assert result.invited_by == ADMIN_USER_ID

    @pytest.mark.asyncio
    async def test_existing_user_roles_are_assigned(
        self,
        use_case: InviteUserUseCase,
        account_type_repository: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        active_account_type: AccountType,
        existing_user: User,
    ) -> None:
        """Roles are correctly created for existing user."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="existing@example.com",
            full_name="Existing User",
            account_type="socio",
            roles=["admin", "manager"],
        )
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type
        user_repository.find_by_email.return_value = existing_user
        member_repository.find_by_user_in_tenant.return_value = None

        await use_case.execute(input_dto, ADMIN_USER_ID)

        call_args = member_repository.create_member_with_roles.call_args
        roles = call_args.kwargs.get("roles") or call_args[1].get("roles")
        role_names = [r.role_name for r in roles]
        assert "admin" in role_names
        assert "manager" in role_names


# ──── Test: User Already a Member of Tenant (Req 4.4) ─────────────────────────


class TestUserAlreadyMember:
    """Tests for attempting to invite a user already in the tenant."""

    @pytest.mark.asyncio
    async def test_already_member_raises_conflict_error(
        self,
        use_case: InviteUserUseCase,
        account_type_repository: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        active_account_type: AccountType,
        existing_user: User,
        existing_member: Member,
    ) -> None:
        """Existing member in tenant raises ConflictError."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="existing@example.com",
            full_name="Existing User",
            account_type="socio",
            roles=["viewer"],
        )
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type
        user_repository.find_by_email.return_value = existing_user
        member_repository.find_by_user_in_tenant.return_value = existing_member

        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(input_dto, ADMIN_USER_ID)

        assert "User is already a member of this tenant" in exc_info.value.message


# ──── Test: Account Type Not Found (Req 4.5) ─────────────────────────────────


class TestAccountTypeNotFound:
    """Tests for specifying an account type that does not exist."""

    @pytest.mark.asyncio
    async def test_nonexistent_account_type_raises_not_found(
        self,
        use_case: InviteUserUseCase,
        valid_input: CreateMemberInputDTO,
        account_type_repository: AsyncMock,
    ) -> None:
        """Nonexistent account type raises NotFoundError."""
        account_type_repository.find_by_name_in_tenant.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(valid_input, ADMIN_USER_ID)

        assert "Account type does not exist in this tenant" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_nonexistent_account_type_does_not_call_user_repo(
        self,
        use_case: InviteUserUseCase,
        valid_input: CreateMemberInputDTO,
        account_type_repository: AsyncMock,
        user_repository: MagicMock,
    ) -> None:
        """Validation short-circuits before checking user existence."""
        account_type_repository.find_by_name_in_tenant.return_value = None

        with pytest.raises(NotFoundError):
            await use_case.execute(valid_input, ADMIN_USER_ID)

        user_repository.find_by_email.assert_not_called()


# ──── Test: Account Type Inactive (Req 4.6) ──────────────────────────────────


class TestAccountTypeInactive:
    """Tests for specifying an inactive account type."""

    @pytest.mark.asyncio
    async def test_inactive_account_type_raises_domain_error(
        self,
        use_case: InviteUserUseCase,
        account_type_repository: AsyncMock,
        inactive_account_type: AccountType,
    ) -> None:
        """Inactive account type raises DomainError."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="newuser@example.com",
            full_name="Jane Smith",
            account_type="profesional",
            roles=["viewer"],
        )
        account_type_repository.find_by_name_in_tenant.return_value = inactive_account_type

        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(input_dto, ADMIN_USER_ID)

        assert "Account type is not active" in exc_info.value.message


# ──── Test: Invalid Roles (Req 4.7) ──────────────────────────────────────────


class TestInvalidRoles:
    """Tests for invalid role names."""

    @pytest.mark.asyncio
    async def test_invalid_role_name_raises_validation_error(
        self,
        use_case: InviteUserUseCase,
    ) -> None:
        """Invalid role name raises ValidationError."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="newuser@example.com",
            full_name="Jane Smith",
            account_type="socio",
            roles=["admin", "superuser"],
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto, ADMIN_USER_ID)

        assert "Invalid role" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_empty_role_name_raises_validation_error(
        self,
        use_case: InviteUserUseCase,
    ) -> None:
        """Empty role name string raises ValidationError."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="newuser@example.com",
            full_name="Jane Smith",
            account_type="socio",
            roles=[""],
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto, ADMIN_USER_ID)

        assert "Invalid role" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_role_validation_happens_before_account_type_check(
        self,
        use_case: InviteUserUseCase,
        account_type_repository: AsyncMock,
    ) -> None:
        """Role validation occurs before account type lookup."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="newuser@example.com",
            full_name="Jane Smith",
            account_type="socio",
            roles=["nonexistent_role"],
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto, ADMIN_USER_ID)

        account_type_repository.find_by_name_in_tenant.assert_not_called()


# ──── Test: Input Validation (Req 11.1, 11.2, 11.3) ──────────────────────────


class TestInputValidation:
    """Tests for input value object validation."""

    @pytest.mark.asyncio
    async def test_invalid_email_raises_validation_error(
        self,
        use_case: InviteUserUseCase,
    ) -> None:
        """Invalid email format raises ValidationError."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="not-an-email",
            full_name="Jane Smith",
            account_type="socio",
            roles=["viewer"],
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto, ADMIN_USER_ID)

    @pytest.mark.asyncio
    async def test_empty_full_name_raises_validation_error(
        self,
        use_case: InviteUserUseCase,
    ) -> None:
        """Empty full name raises ValidationError."""
        input_dto = CreateMemberInputDTO(
            tenant_id=TENANT_ID,
            email="valid@example.com",
            full_name="   ",
            account_type="socio",
            roles=["viewer"],
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto, ADMIN_USER_ID)

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_raises_validation_error(
        self,
        use_case: InviteUserUseCase,
    ) -> None:
        """Invalid tenant ID raises ValidationError."""
        input_dto = CreateMemberInputDTO(
            tenant_id="not-a-uuid",
            email="valid@example.com",
            full_name="Jane Smith",
            account_type="socio",
            roles=["viewer"],
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto, ADMIN_USER_ID)
