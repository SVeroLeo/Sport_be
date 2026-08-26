"""Unit tests for RegisterUseCase."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.dtos.auth.register_input_dto import RegisterInputDTO
from application.use_cases.registration.register_use_case import RegisterUseCase
from domain.entities.account_type import AccountType
from domain.entities.tenant import Tenant
from domain.entities.user import User
from domain.errors.conflict_error import ConflictError
from domain.errors.domain_error import DomainError
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError
from domain.value_objects.tenant_id import TenantId


# ──── Fixtures ────────────────────────────────────────────────────────────────


TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def cognito_service() -> AsyncMock:
    """Mock ICognitoService."""
    mock = AsyncMock()
    mock.sign_up.return_value = "cognito-sub-new-user-123"
    return mock


@pytest.fixture
def user_repository() -> MagicMock:
    """Mock IUserRepository (sync methods)."""
    mock = MagicMock()
    mock.find_by_email.return_value = None  # No existing user by default
    return mock


@pytest.fixture
def tenant_repository() -> AsyncMock:
    """Mock ITenantRepository (async methods)."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def account_type_repository() -> AsyncMock:
    """Mock IAccountTypeRepository (async methods)."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def active_tenant() -> Tenant:
    """Active tenant that allows self-registration with a default account type."""
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
    """Active account type for testing."""
    return AccountType.reconstitute(
        account_type_id="acctype-uuid-001",
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
    cognito_service: AsyncMock,
    user_repository: MagicMock,
    tenant_repository: AsyncMock,
    account_type_repository: AsyncMock,
) -> RegisterUseCase:
    """Create a RegisterUseCase with mocked dependencies."""
    return RegisterUseCase(
        cognito_service=cognito_service,
        user_repository=user_repository,
        tenant_repository=tenant_repository,
        account_type_repository=account_type_repository,
    )


@pytest.fixture
def valid_input() -> RegisterInputDTO:
    """Valid self-registration input DTO."""
    return RegisterInputDTO(
        email="newuser@example.com",
        password="SecureP@ss1",
        full_name="Jane Doe",
        tenant_id=TENANT_ID,
        account_type=None,
    )


# ──── Test: Successful Registration ──────────────────────────────────────────


class TestRegisterSuccess:
    """Tests for successful self-registration flow (Req 3.1)."""

    @pytest.mark.asyncio
    async def test_successful_registration_returns_pending_status(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """Successful registration returns pending_confirmation status."""
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        result = await use_case.execute(valid_input)

        assert result.status == "pending_confirmation"
        assert result.email == "newuser@example.com"
        assert result.full_name == "Jane Doe"
        assert result.user_id == "cognito-sub-new-user-123"
        assert "verify" in result.message.lower() or "email" in result.message.lower()

    @pytest.mark.asyncio
    async def test_successful_registration_calls_cognito_sign_up(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        cognito_service: AsyncMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """Cognito sign_up is called with correct parameters."""
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        await use_case.execute(valid_input)

        cognito_service.sign_up.assert_called_once_with(
            email="newuser@example.com",
            password="SecureP@ss1",
            full_name="Jane Doe",
        )

    @pytest.mark.asyncio
    async def test_registration_normalizes_email(
        self,
        use_case: RegisterUseCase,
        cognito_service: AsyncMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """Email is normalized (trimmed, lowercased) before processing."""
        input_dto = RegisterInputDTO(
            email="  NewUser@Example.COM  ",
            password="SecureP@ss1",
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
        )
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        result = await use_case.execute(input_dto)

        assert result.email == "newuser@example.com"
        cognito_service.sign_up.assert_called_once_with(
            email="newuser@example.com",
            password="SecureP@ss1",
            full_name="Jane Doe",
        )


# ──── Test: Email Already Registered (Req 3.3) ──────────────────────────────


class TestEmailAlreadyRegistered:
    """Tests for duplicate email detection (Req 3.3)."""

    @pytest.mark.asyncio
    async def test_existing_email_raises_conflict_error(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        user_repository: MagicMock,
    ) -> None:
        """Email already in local DB raises ConflictError."""
        user_repository.find_by_email.return_value = User.reconstitute(
            user_id="existing-user-uuid",
            email="newuser@example.com",
            cognito_sub="existing-sub",
            full_name="Existing User",
            status="active",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(valid_input)

        assert "already registered" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_existing_email_does_not_call_cognito(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        user_repository: MagicMock,
        cognito_service: AsyncMock,
    ) -> None:
        """When email exists locally, Cognito is never called."""
        user_repository.find_by_email.return_value = User.reconstitute(
            user_id="existing-user-uuid",
            email="newuser@example.com",
            cognito_sub="existing-sub",
            full_name="Existing User",
            status="active",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        with pytest.raises(ConflictError):
            await use_case.execute(valid_input)

        cognito_service.sign_up.assert_not_called()


# ──── Test: Tenant Not Found (Req 3.4) ──────────────────────────────────────


class TestTenantNotFound:
    """Tests for non-existent tenant (Req 3.4)."""

    @pytest.mark.asyncio
    async def test_nonexistent_tenant_raises_not_found_error(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        tenant_repository: AsyncMock,
    ) -> None:
        """Tenant not found raises NotFoundError."""
        tenant_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(valid_input)

        assert "tenant not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_tenant_does_not_call_cognito(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        tenant_repository: AsyncMock,
        cognito_service: AsyncMock,
    ) -> None:
        """When tenant doesn't exist, Cognito is never called."""
        tenant_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await use_case.execute(valid_input)

        cognito_service.sign_up.assert_not_called()


# ──── Test: Tenant Not Active (Req 3.5) ─────────────────────────────────────


class TestTenantNotActive:
    """Tests for inactive tenant (Req 3.5)."""

    @pytest.mark.asyncio
    async def test_inactive_tenant_raises_domain_error(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        tenant_repository: AsyncMock,
    ) -> None:
        """Inactive tenant raises DomainError with correct message."""
        inactive_tenant = Tenant.create(
            tenant_id=TenantId.create(TENANT_ID),
            name="Inactive Club",
            status="inactive",
            allow_self_registration=True,
        )
        tenant_repository.find_by_id.return_value = inactive_tenant

        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(valid_input)

        assert exc_info.value.message == "Tenant is not active"


# ──── Test: Self-Registration Not Allowed (Req 3.6) ──────────────────────────


class TestSelfRegistrationNotAllowed:
    """Tests for tenant that disallows self-registration (Req 3.6)."""

    @pytest.mark.asyncio
    async def test_self_registration_disabled_raises_domain_error(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        tenant_repository: AsyncMock,
    ) -> None:
        """Tenant with self-registration disabled raises DomainError."""
        no_self_reg_tenant = Tenant.create(
            tenant_id=TenantId.create(TENANT_ID),
            name="Invite-Only Club",
            status="active",
            allow_self_registration=False,
        )
        tenant_repository.find_by_id.return_value = no_self_reg_tenant

        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(valid_input)

        assert "self-registration is not allowed" in exc_info.value.message.lower()


# ──── Test: Account Type Resolution (Req 3.7, 3.8) ──────────────────────────


class TestAccountTypeResolution:
    """Tests for account type determination logic (Req 3.7, 3.8)."""

    @pytest.mark.asyncio
    async def test_explicit_valid_account_type_is_used(
        self,
        use_case: RegisterUseCase,
        cognito_service: AsyncMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """When user specifies a valid, active account type, it's used."""
        input_dto = RegisterInputDTO(
            email="newuser@example.com",
            password="SecureP@ss1",
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
            account_type="profesional",
        )
        profesional_type = AccountType.reconstitute(
            account_type_id="acctype-uuid-002",
            tenant_id=TENANT_ID,
            name="profesional",
            description=None,
            config=None,
            status="active",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = profesional_type

        result = await use_case.execute(input_dto)

        assert result.status == "pending_confirmation"
        # Verify account type was looked up
        account_type_repository.find_by_name_in_tenant.assert_called_with(
            tenant_id=TENANT_ID,
            name="profesional",
        )

    @pytest.mark.asyncio
    async def test_explicit_nonexistent_account_type_raises_error(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Specifying non-existent account type raises ValidationError (Req 3.8)."""
        input_dto = RegisterInputDTO(
            email="newuser@example.com",
            password="SecureP@ss1",
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
            account_type="nonexistent",
        )
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = None

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert "invalid account type" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_explicit_inactive_account_type_raises_error(
        self,
        use_case: RegisterUseCase,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Specifying inactive account type raises ValidationError (Req 3.8)."""
        input_dto = RegisterInputDTO(
            email="newuser@example.com",
            password="SecureP@ss1",
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
            account_type="old_type",
        )
        inactive_type = AccountType.reconstitute(
            account_type_id="acctype-uuid-003",
            tenant_id=TENANT_ID,
            name="old_type",
            description=None,
            config=None,
            status="inactive",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = inactive_type

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert "invalid account type" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_no_account_type_uses_tenant_default(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
        active_account_type: AccountType,
    ) -> None:
        """When no account type specified, uses tenant's defaultAccountType (Req 3.7)."""
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type

        result = await use_case.execute(valid_input)

        assert result.status == "pending_confirmation"
        account_type_repository.find_by_name_in_tenant.assert_called_with(
            tenant_id=TENANT_ID,
            name="socio",
        )

    @pytest.mark.asyncio
    async def test_no_account_type_fallback_when_default_is_inactive(
        self,
        use_case: RegisterUseCase,
        valid_input: RegisterInputDTO,
        cognito_service: AsyncMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """When tenant default is inactive, falls back to 'usuario' (Req 3.7)."""
        inactive_default = AccountType.reconstitute(
            account_type_id="acctype-uuid-004",
            tenant_id=TENANT_ID,
            name="socio",
            description=None,
            config=None,
            status="inactive",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = inactive_default

        result = await use_case.execute(valid_input)

        # Falls back to "usuario" — registration still succeeds
        assert result.status == "pending_confirmation"

    @pytest.mark.asyncio
    async def test_no_account_type_fallback_when_default_is_null(
        self,
        use_case: RegisterUseCase,
        cognito_service: AsyncMock,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
    ) -> None:
        """When tenant has no default account type, falls back to 'usuario' (Req 3.7)."""
        tenant_no_default = Tenant.create(
            tenant_id=TenantId.create(TENANT_ID),
            name="Club Sin Default",
            status="active",
            allow_self_registration=True,
            default_account_type=None,
        )
        tenant_repository.find_by_id.return_value = tenant_no_default
        # find_by_name_in_tenant won't be called since default is None

        result = await use_case.execute(
            RegisterInputDTO(
                email="newuser@example.com",
                password="SecureP@ss1",
                full_name="Jane Doe",
                tenant_id=TENANT_ID,
            )
        )

        assert result.status == "pending_confirmation"


# ──── Test: Input Validation ──────────────────────────────────────────────────


class TestInputValidation:
    """Tests for value object validation at the use case boundary."""

    @pytest.mark.asyncio
    async def test_invalid_email_raises_validation_error(
        self,
        use_case: RegisterUseCase,
    ) -> None:
        """Invalid email format raises ValidationError."""
        input_dto = RegisterInputDTO(
            email="invalid-email",
            password="SecureP@ss1",
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto)

    @pytest.mark.asyncio
    async def test_short_password_raises_validation_error(
        self,
        use_case: RegisterUseCase,
    ) -> None:
        """Password below minimum length raises ValidationError."""
        input_dto = RegisterInputDTO(
            email="newuser@example.com",
            password="short",
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "password"

    @pytest.mark.asyncio
    async def test_long_password_raises_validation_error(
        self,
        use_case: RegisterUseCase,
    ) -> None:
        """Password exceeding 72 chars raises ValidationError."""
        input_dto = RegisterInputDTO(
            email="newuser@example.com",
            password="A" * 73,
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "password"

    @pytest.mark.asyncio
    async def test_empty_full_name_raises_validation_error(
        self,
        use_case: RegisterUseCase,
    ) -> None:
        """Empty full name raises ValidationError."""
        input_dto = RegisterInputDTO(
            email="newuser@example.com",
            password="SecureP@ss1",
            full_name="   ",
            tenant_id=TENANT_ID,
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "full_name"

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_raises_validation_error(
        self,
        use_case: RegisterUseCase,
    ) -> None:
        """Invalid UUID format for tenant_id raises ValidationError."""
        input_dto = RegisterInputDTO(
            email="newuser@example.com",
            password="SecureP@ss1",
            full_name="Jane Doe",
            tenant_id="not-a-uuid",
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_validation_errors_short_circuit_before_db_calls(
        self,
        use_case: RegisterUseCase,
        user_repository: MagicMock,
        cognito_service: AsyncMock,
    ) -> None:
        """Validation failures prevent any repository or service calls."""
        input_dto = RegisterInputDTO(
            email="invalid",
            password="SecureP@ss1",
            full_name="Jane Doe",
            tenant_id=TENANT_ID,
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto)

        user_repository.find_by_email.assert_not_called()
        cognito_service.sign_up.assert_not_called()
