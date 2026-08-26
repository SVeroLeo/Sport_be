"""Unit tests for LoginUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.dtos.auth.login_input_dto import LoginInputDTO
from application.use_cases.auth.login_use_case import LoginUseCase
from domain.entities.member import Member
from domain.entities.token_pair import TokenPair
from domain.entities.user import User
from domain.entities.user_role import UserRole
from domain.errors.domain_error import DomainError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.errors.validation_error import ValidationError
from domain.value_objects.email import Email


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def cognito_service() -> AsyncMock:
    """Mock ICognitoService with async initiate_auth."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def user_repository() -> MagicMock:
    """Mock IUserRepository with sync methods."""
    mock = MagicMock()
    return mock


@pytest.fixture
def member_repository() -> MagicMock:
    """Mock IMemberRepository with sync methods."""
    mock = MagicMock()
    return mock


@pytest.fixture
def use_case(
    cognito_service: AsyncMock,
    user_repository: MagicMock,
    member_repository: MagicMock,
) -> LoginUseCase:
    """Create a LoginUseCase with mocked dependencies."""
    return LoginUseCase(
        cognito_service=cognito_service,
        user_repository=user_repository,
        member_repository=member_repository,
    )


@pytest.fixture
def valid_input() -> LoginInputDTO:
    """Valid login input DTO."""
    return LoginInputDTO(
        email="user@example.com",
        password="SecureP@ss1",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
    )


@pytest.fixture
def token_pair() -> TokenPair:
    """Sample token pair from Cognito."""
    return TokenPair(
        access_token="access-token-abc123",
        id_token="id-token-def456",
        refresh_token="refresh-token-ghi789",
        expires_in=3600,
    )


@pytest.fixture
def user() -> User:
    """Sample active user entity."""
    return User.reconstitute(
        user_id="user-uuid-001",
        email="user@example.com",
        cognito_sub="cognito-sub-xyz",
        full_name="John Doe",
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def active_member() -> Member:
    """Sample active member entity."""
    return Member.reconstitute(
        member_id="member-uuid-001",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        user_id="user-uuid-001",
        account_type="socio",
        account_type_id="acctype-uuid-001",
        full_name="John Doe",
        email="user@example.com",
        status="active",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def inactive_member() -> Member:
    """Sample inactive member entity."""
    return Member.reconstitute(
        member_id="member-uuid-002",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        user_id="user-uuid-001",
        account_type="socio",
        account_type_id="acctype-uuid-001",
        full_name="John Doe",
        email="user@example.com",
        status="inactive",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def user_roles() -> list[UserRole]:
    """Sample user roles."""
    return [
        UserRole.reconstitute(
            user_id="user-uuid-001",
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            role_name="admin",
            assigned_at=datetime(2024, 1, 1, tzinfo=UTC),
        ),
        UserRole.reconstitute(
            user_id="user-uuid-001",
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            role_name="manager",
            assigned_at=datetime(2024, 1, 1, tzinfo=UTC),
        ),
    ]


# ──── Test: Successful Login ──────────────────────────────────────────────────


class TestLoginSuccess:
    """Tests for successful authentication flow (Req 1.1, 1.2, 1.6)."""

    @pytest.mark.asyncio
    async def test_successful_login_returns_tokens_and_roles(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        token_pair: TokenPair,
        user: User,
        active_member: Member,
        user_roles: list[UserRole],
    ) -> None:
        """Successful login returns TokenPair + user roles for the tenant."""
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = user
        member_repository.find_by_user_in_tenant.return_value = active_member
        user_repository.get_roles_for_tenant.return_value = user_roles

        result = await use_case.execute(valid_input)

        assert result.access_token == "access-token-abc123"
        assert result.id_token == "id-token-def456"
        assert result.refresh_token == "refresh-token-ghi789"
        assert result.expires_in == 3600
        assert result.roles == ["admin", "manager"]

    @pytest.mark.asyncio
    async def test_successful_login_calls_cognito_with_normalized_email(
        self,
        use_case: LoginUseCase,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        token_pair: TokenPair,
        user: User,
        active_member: Member,
        user_roles: list[UserRole],
    ) -> None:
        """Cognito is called with the normalized (lowercased, trimmed) email."""
        input_dto = LoginInputDTO(
            email="  User@Example.COM  ",
            password="SecureP@ss1",
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
        )
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = user
        member_repository.find_by_user_in_tenant.return_value = active_member
        user_repository.get_roles_for_tenant.return_value = user_roles

        await use_case.execute(input_dto)

        cognito_service.initiate_auth.assert_called_once_with(
            email="user@example.com",
            password="SecureP@ss1",
        )

    @pytest.mark.asyncio
    async def test_successful_login_queries_member_with_correct_tenant(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        token_pair: TokenPair,
        user: User,
        active_member: Member,
        user_roles: list[UserRole],
    ) -> None:
        """Member repository is queried with correct tenant_id and user_id."""
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = user
        member_repository.find_by_user_in_tenant.return_value = active_member
        user_repository.get_roles_for_tenant.return_value = user_roles

        await use_case.execute(valid_input)

        member_repository.find_by_user_in_tenant.assert_called_once_with(
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            user_id="user-uuid-001",
        )


# ──── Test: Cognito Auth Failure ──────────────────────────────────────────────


class TestCognitoAuthFailure:
    """Tests for Cognito authentication failure (Req 1.3)."""

    @pytest.mark.asyncio
    async def test_cognito_failure_raises_invalid_credentials(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
    ) -> None:
        """Cognito auth failure raises generic InvalidCredentialsError."""
        cognito_service.initiate_auth.side_effect = InvalidCredentialsError(
            "NotAuthorizedException"
        )

        with pytest.raises(InvalidCredentialsError) as exc_info:
            await use_case.execute(valid_input)

        assert exc_info.value.message == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_cognito_failure_does_not_reveal_email_existence(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
    ) -> None:
        """When Cognito fails, user repository is never called (no info leak)."""
        cognito_service.initiate_auth.side_effect = InvalidCredentialsError()

        with pytest.raises(InvalidCredentialsError):
            await use_case.execute(valid_input)

        user_repository.find_by_email.assert_not_called()


# ──── Test: User Not Found ────────────────────────────────────────────────────


class TestUserNotFound:
    """Tests for user not found in local database (Req 1.5)."""

    @pytest.mark.asyncio
    async def test_user_not_found_raises_invalid_credentials(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        token_pair: TokenPair,
    ) -> None:
        """User not found in DB after Cognito success → generic InvalidCredentialsError."""
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = None

        with pytest.raises(InvalidCredentialsError) as exc_info:
            await use_case.execute(valid_input)

        assert exc_info.value.message == "Invalid credentials"


# ──── Test: Member Not Found in Tenant ────────────────────────────────────────


class TestMemberNotFoundInTenant:
    """Tests for user without membership in the specified tenant (Req 1.5)."""

    @pytest.mark.asyncio
    async def test_no_membership_raises_invalid_credentials(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        token_pair: TokenPair,
        user: User,
    ) -> None:
        """No membership in tenant → generic InvalidCredentialsError."""
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = user
        member_repository.find_by_user_in_tenant.return_value = None

        with pytest.raises(InvalidCredentialsError) as exc_info:
            await use_case.execute(valid_input)

        assert exc_info.value.message == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_no_membership_does_not_reveal_status(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        token_pair: TokenPair,
        user: User,
    ) -> None:
        """When no membership, roles are never queried (short-circuit)."""
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = user
        member_repository.find_by_user_in_tenant.return_value = None

        with pytest.raises(InvalidCredentialsError):
            await use_case.execute(valid_input)

        user_repository.get_roles_for_tenant.assert_not_called()


# ──── Test: Inactive Membership ───────────────────────────────────────────────


class TestInactiveMembership:
    """Tests for membership that is not active (Req 1.4)."""

    @pytest.mark.asyncio
    async def test_inactive_membership_raises_domain_error(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        token_pair: TokenPair,
        user: User,
        inactive_member: Member,
    ) -> None:
        """Inactive membership raises DomainError with 'Account is not active'."""
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = user
        member_repository.find_by_user_in_tenant.return_value = inactive_member

        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(valid_input)

        assert exc_info.value.message == "Account is not active"

    @pytest.mark.asyncio
    async def test_pending_confirmation_membership_raises_domain_error(
        self,
        use_case: LoginUseCase,
        valid_input: LoginInputDTO,
        cognito_service: AsyncMock,
        user_repository: MagicMock,
        member_repository: MagicMock,
        token_pair: TokenPair,
        user: User,
    ) -> None:
        """Membership with 'pending_confirmation' status raises DomainError."""
        pending_member = Member.reconstitute(
            member_id="member-uuid-003",
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            user_id="user-uuid-001",
            account_type="socio",
            account_type_id="acctype-uuid-001",
            full_name="John Doe",
            email="user@example.com",
            status="pending_confirmation",
            registration_type="invited",
            invited_by="admin-uuid-001",
            metadata=None,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        cognito_service.initiate_auth.return_value = token_pair
        user_repository.find_by_email.return_value = user
        member_repository.find_by_user_in_tenant.return_value = pending_member

        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(valid_input)

        assert exc_info.value.message == "Account is not active"


# ──── Test: Invalid Email Format ──────────────────────────────────────────────


class TestInvalidEmailFormat:
    """Tests for invalid email format (Req 11.1)."""

    @pytest.mark.asyncio
    async def test_empty_email_raises_validation_error(
        self,
        use_case: LoginUseCase,
    ) -> None:
        """Empty email raises ValidationError before any service call."""
        input_dto = LoginInputDTO(
            email="",
            password="SecureP@ss1",
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
        )

        with pytest.raises(ValidationError, match="Invalid email format"):
            await use_case.execute(input_dto)

    @pytest.mark.asyncio
    async def test_malformed_email_raises_validation_error(
        self,
        use_case: LoginUseCase,
    ) -> None:
        """Malformed email raises ValidationError."""
        input_dto = LoginInputDTO(
            email="not-an-email",
            password="SecureP@ss1",
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
        )

        with pytest.raises(ValidationError, match="Invalid email format"):
            await use_case.execute(input_dto)

    @pytest.mark.asyncio
    async def test_invalid_email_does_not_call_cognito(
        self,
        use_case: LoginUseCase,
        cognito_service: AsyncMock,
    ) -> None:
        """Invalid email short-circuits before calling Cognito."""
        input_dto = LoginInputDTO(
            email="invalid",
            password="SecureP@ss1",
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto)

        cognito_service.initiate_auth.assert_not_called()
