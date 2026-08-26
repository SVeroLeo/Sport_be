"""Unit tests for CreateAccountTypeUseCase."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from application.dtos.account_type.create_account_type_input_dto import (
    CreateAccountTypeInputDTO,
)
from application.use_cases.account_type.create_account_type_use_case import (
    CreateAccountTypeUseCase,
)
from domain.entities.account_type import AccountType
from domain.entities.tenant import Tenant
from domain.errors.conflict_error import ConflictError
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError
from domain.value_objects.tenant_id import TenantId


# ──── Fixtures ────────────────────────────────────────────────────────────────


TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def account_type_repository() -> AsyncMock:
    """Mock IAccountTypeRepository."""
    mock = AsyncMock()
    mock.find_by_name_in_tenant.return_value = None  # No duplicate by default
    # save returns the entity passed to it
    mock.save.side_effect = lambda at: at
    return mock


@pytest.fixture
def tenant_repository() -> AsyncMock:
    """Mock ITenantRepository."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def active_tenant() -> Tenant:
    """Active tenant for testing."""
    return Tenant.create(
        tenant_id=TenantId.create(TENANT_ID),
        name="Club Deportivo Test",
        plan="premium",
        status="active",
        allow_self_registration=True,
        default_account_type="socio",
    )


@pytest.fixture
def use_case(
    account_type_repository: AsyncMock,
    tenant_repository: AsyncMock,
) -> CreateAccountTypeUseCase:
    """Create a CreateAccountTypeUseCase with mocked dependencies."""
    return CreateAccountTypeUseCase(
        account_type_repository=account_type_repository,
        tenant_repository=tenant_repository,
    )


@pytest.fixture
def valid_input() -> CreateAccountTypeInputDTO:
    """Valid input DTO for creating an account type."""
    return CreateAccountTypeInputDTO(
        tenant_id=TENANT_ID,
        name="profesional",
        description="Professional membership type",
        config={"max_members": 50},
    )


# ──── Test: Successful Creation (Req 5.1) ────────────────────────────────────


class TestCreateAccountTypeSuccess:
    """Tests for successful account type creation (Req 5.1)."""

    @pytest.mark.asyncio
    async def test_successful_creation_returns_output_dto(
        self,
        use_case: CreateAccountTypeUseCase,
        valid_input: CreateAccountTypeInputDTO,
        tenant_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Successful creation returns AccountTypeOutputDTO with correct fields."""
        tenant_repository.find_by_id.return_value = active_tenant

        result = await use_case.execute(valid_input)

        assert result.tenant_id == TENANT_ID
        assert result.name == "profesional"
        assert result.description == "Professional membership type"
        assert result.config == {"max_members": 50}
        assert result.status == "active"
        assert result.account_type_id is not None
        assert result.created_at is not None
        assert result.updated_at is not None

    @pytest.mark.asyncio
    async def test_successful_creation_persists_entity(
        self,
        use_case: CreateAccountTypeUseCase,
        valid_input: CreateAccountTypeInputDTO,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Created account type is persisted via repository save."""
        tenant_repository.find_by_id.return_value = active_tenant

        await use_case.execute(valid_input)

        account_type_repository.save.assert_called_once()
        saved_entity = account_type_repository.save.call_args[0][0]
        assert isinstance(saved_entity, AccountType)
        assert saved_entity.name == "profesional"
        assert saved_entity.status == "active"

    @pytest.mark.asyncio
    async def test_creation_with_no_description_and_config(
        self,
        use_case: CreateAccountTypeUseCase,
        tenant_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Account type can be created with null description and config."""
        tenant_repository.find_by_id.return_value = active_tenant
        input_dto = CreateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            name="socio",
        )

        result = await use_case.execute(input_dto)

        assert result.name == "socio"
        assert result.description is None
        assert result.config is None
        assert result.status == "active"


# ──── Test: Tenant Not Found ─────────────────────────────────────────────────


class TestTenantNotFound:
    """Tests for non-existent tenant."""

    @pytest.mark.asyncio
    async def test_nonexistent_tenant_raises_not_found_error(
        self,
        use_case: CreateAccountTypeUseCase,
        valid_input: CreateAccountTypeInputDTO,
        tenant_repository: AsyncMock,
    ) -> None:
        """Tenant not found raises NotFoundError."""
        tenant_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(valid_input)

        assert "tenant not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_tenant_does_not_persist(
        self,
        use_case: CreateAccountTypeUseCase,
        valid_input: CreateAccountTypeInputDTO,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
    ) -> None:
        """When tenant doesn't exist, nothing is persisted."""
        tenant_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await use_case.execute(valid_input)

        account_type_repository.save.assert_not_called()


# ──── Test: Name Uniqueness (Req 5.2) ────────────────────────────────────────


class TestNameUniqueness:
    """Tests for case-insensitive name uniqueness within tenant (Req 5.2)."""

    @pytest.mark.asyncio
    async def test_duplicate_name_raises_conflict_error(
        self,
        use_case: CreateAccountTypeUseCase,
        valid_input: CreateAccountTypeInputDTO,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Duplicate name in same tenant raises ConflictError."""
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = (
            AccountType.reconstitute(
                account_type_id="existing-uuid",
                tenant_id=TENANT_ID,
                name="profesional",
                description=None,
                config=None,
                status="active",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )

        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(valid_input)

        assert "already exists" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_duplicate_name_does_not_persist(
        self,
        use_case: CreateAccountTypeUseCase,
        valid_input: CreateAccountTypeInputDTO,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """When name is duplicate, nothing is persisted."""
        tenant_repository.find_by_id.return_value = active_tenant
        account_type_repository.find_by_name_in_tenant.return_value = (
            AccountType.reconstitute(
                account_type_id="existing-uuid",
                tenant_id=TENANT_ID,
                name="profesional",
                description=None,
                config=None,
                status="active",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )

        with pytest.raises(ConflictError):
            await use_case.execute(valid_input)

        account_type_repository.save.assert_not_called()


# ──── Test: Name Validation (Req 5.3) ────────────────────────────────────────


class TestNameValidation:
    """Tests for account type name domain validation (Req 5.3)."""

    @pytest.mark.asyncio
    async def test_empty_name_raises_validation_error(
        self,
        use_case: CreateAccountTypeUseCase,
        tenant_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Empty name raises ValidationError."""
        tenant_repository.find_by_id.return_value = active_tenant
        input_dto = CreateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            name="",
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "name"

    @pytest.mark.asyncio
    async def test_whitespace_only_name_raises_validation_error(
        self,
        use_case: CreateAccountTypeUseCase,
        tenant_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Whitespace-only name raises ValidationError."""
        tenant_repository.find_by_id.return_value = active_tenant
        input_dto = CreateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            name="   ",
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "name"

    @pytest.mark.asyncio
    async def test_name_exceeding_100_chars_raises_validation_error(
        self,
        use_case: CreateAccountTypeUseCase,
        tenant_repository: AsyncMock,
        active_tenant: Tenant,
    ) -> None:
        """Name exceeding 100 characters raises ValidationError."""
        tenant_repository.find_by_id.return_value = active_tenant
        input_dto = CreateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            name="A" * 101,
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "name"


# ──── Test: Input Validation (TenantId) ──────────────────────────────────────


class TestInputValidation:
    """Tests for input validation at the use case boundary."""

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_raises_validation_error(
        self,
        use_case: CreateAccountTypeUseCase,
    ) -> None:
        """Invalid UUID format for tenant_id raises ValidationError."""
        input_dto = CreateAccountTypeInputDTO(
            tenant_id="not-a-uuid",
            name="socio",
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_empty_tenant_id_raises_validation_error(
        self,
        use_case: CreateAccountTypeUseCase,
    ) -> None:
        """Empty tenant_id raises ValidationError."""
        input_dto = CreateAccountTypeInputDTO(
            tenant_id="",
            name="socio",
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_validation_errors_short_circuit_before_repo_calls(
        self,
        use_case: CreateAccountTypeUseCase,
        tenant_repository: AsyncMock,
        account_type_repository: AsyncMock,
    ) -> None:
        """Validation failures prevent any repository calls."""
        input_dto = CreateAccountTypeInputDTO(
            tenant_id="invalid",
            name="socio",
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto)

        tenant_repository.find_by_id.assert_not_called()
        account_type_repository.save.assert_not_called()
