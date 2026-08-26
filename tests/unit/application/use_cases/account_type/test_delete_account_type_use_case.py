"""Unit tests for DeleteAccountTypeUseCase."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.use_cases.account_type.delete_account_type_use_case import (
    DeleteAccountTypeUseCase,
)
from domain.entities.account_type import AccountType
from domain.errors.domain_error import DomainError
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError


# ──── Fixtures ────────────────────────────────────────────────────────────────


TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
ACCOUNT_TYPE_ID = "660e8400-e29b-41d4-a716-446655440001"


@pytest.fixture
def account_type_repository() -> AsyncMock:
    """Mock IAccountTypeRepository (async methods)."""
    mock = AsyncMock()
    mock.update.side_effect = lambda at: at
    return mock


@pytest.fixture
def member_repository() -> MagicMock:
    """Mock IMemberRepository (sync count_active_by_account_type)."""
    mock = MagicMock()
    mock.count_active_by_account_type.return_value = 0  # No active members by default
    return mock


@pytest.fixture
def active_account_type() -> AccountType:
    """Active account type for testing."""
    return AccountType.reconstitute(
        account_type_id=ACCOUNT_TYPE_ID,
        tenant_id=TENANT_ID,
        name="Profesional",
        description="Professional membership",
        config=None,
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def use_case(
    account_type_repository: AsyncMock,
    member_repository: MagicMock,
) -> DeleteAccountTypeUseCase:
    """Create a DeleteAccountTypeUseCase with mocked dependencies."""
    return DeleteAccountTypeUseCase(
        account_type_repository=account_type_repository,
        member_repository=member_repository,
    )


# ──── Test: Successful Deletion (Req 5.6) ────────────────────────────────────


class TestDeleteAccountTypeSuccess:
    """Tests for successful soft-delete of an account type (Req 5.6)."""

    @pytest.mark.asyncio
    async def test_successful_deletion_returns_none(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        active_account_type: AccountType,
    ) -> None:
        """Successful deletion returns None (void operation)."""
        account_type_repository.find_by_id.return_value = active_account_type

        result = await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_successful_deletion_sets_status_inactive(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        active_account_type: AccountType,
    ) -> None:
        """Soft delete sets the account type status to inactive."""
        account_type_repository.find_by_id.return_value = active_account_type

        await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        account_type_repository.update.assert_called_once()
        updated_entity = account_type_repository.update.call_args[0][0]
        assert updated_entity.status == "inactive"

    @pytest.mark.asyncio
    async def test_successful_deletion_refreshes_updated_at(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        active_account_type: AccountType,
    ) -> None:
        """Soft delete refreshes the updated_at timestamp."""
        original_updated_at = active_account_type.updated_at
        account_type_repository.find_by_id.return_value = active_account_type

        await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        updated_entity = account_type_repository.update.call_args[0][0]
        assert updated_entity.updated_at > original_updated_at

    @pytest.mark.asyncio
    async def test_successful_deletion_checks_active_members(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        member_repository: MagicMock,
        active_account_type: AccountType,
    ) -> None:
        """Deletion checks active member count with lowercase name."""
        account_type_repository.find_by_id.return_value = active_account_type

        await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        member_repository.count_active_by_account_type.assert_called_once_with(
            TENANT_ID, "profesional"
        )


# ──── Test: Account Type Not Found ───────────────────────────────────────────


class TestAccountTypeNotFound:
    """Tests for non-existent account type."""

    @pytest.mark.asyncio
    async def test_nonexistent_account_type_raises_not_found_error(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
    ) -> None:
        """Account type not found raises NotFoundError."""
        account_type_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        assert "account type not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_account_type_does_not_check_members(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        member_repository: MagicMock,
    ) -> None:
        """When account type doesn't exist, member count is never checked."""
        account_type_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        member_repository.count_active_by_account_type.assert_not_called()


# ──── Test: Active Members Prevent Deletion (Req 5.7) ────────────────────────


class TestActiveMembersPreventDeletion:
    """Tests for deletion protection when active members exist (Req 5.7)."""

    @pytest.mark.asyncio
    async def test_active_members_raises_domain_error(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        member_repository: MagicMock,
        active_account_type: AccountType,
    ) -> None:
        """Active members using account type raises DomainError."""
        account_type_repository.find_by_id.return_value = active_account_type
        member_repository.count_active_by_account_type.return_value = 3

        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        assert "cannot delete account type" in exc_info.value.message.lower()
        assert "active members" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_active_members_does_not_deactivate(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        member_repository: MagicMock,
        active_account_type: AccountType,
    ) -> None:
        """When active members exist, account type is not deactivated."""
        account_type_repository.find_by_id.return_value = active_account_type
        member_repository.count_active_by_account_type.return_value = 1

        with pytest.raises(DomainError):
            await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        account_type_repository.update.assert_not_called()
        assert active_account_type.status == "active"


# ──── Test: Input Validation (TenantId) ──────────────────────────────────────


class TestInputValidation:
    """Tests for input validation at the use case boundary."""

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_raises_validation_error(
        self,
        use_case: DeleteAccountTypeUseCase,
    ) -> None:
        """Invalid UUID format for tenant_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute("not-a-uuid", ACCOUNT_TYPE_ID)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_empty_tenant_id_raises_validation_error(
        self,
        use_case: DeleteAccountTypeUseCase,
    ) -> None:
        """Empty tenant_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute("", ACCOUNT_TYPE_ID)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_validation_errors_short_circuit_before_repo_calls(
        self,
        use_case: DeleteAccountTypeUseCase,
        account_type_repository: AsyncMock,
        member_repository: MagicMock,
    ) -> None:
        """Validation failures prevent any repository calls."""
        with pytest.raises(ValidationError):
            await use_case.execute("invalid", ACCOUNT_TYPE_ID)

        account_type_repository.find_by_id.assert_not_called()
        member_repository.count_active_by_account_type.assert_not_called()
