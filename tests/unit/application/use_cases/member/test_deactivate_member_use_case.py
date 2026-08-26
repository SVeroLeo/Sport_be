"""Unit tests for DeactivateMemberUseCase."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.use_cases.member.deactivate_member_use_case import (
    DeactivateMemberUseCase,
)
from domain.entities.member import Member
from domain.entities.user import User
from domain.errors.not_found_error import NotFoundError
from domain.errors.validation_error import ValidationError


# ──── Fixtures ────────────────────────────────────────────────────────────────


TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
MEMBER_ID = "660e8400-e29b-41d4-a716-446655440001"
USER_ID = "770e8400-e29b-41d4-a716-446655440002"
COGNITO_SUB = "cognito-sub-abc-123"


@pytest.fixture
def member_repository() -> MagicMock:
    """Mock IMemberRepository (sync find_by_id and update)."""
    mock = MagicMock()
    mock.update.side_effect = lambda m: m
    return mock


@pytest.fixture
def user_repository() -> MagicMock:
    """Mock IUserRepository (sync find_by_id)."""
    return MagicMock()


@pytest.fixture
def cognito_service() -> AsyncMock:
    """Mock ICognitoService (async admin_disable_user)."""
    return AsyncMock()


@pytest.fixture
def active_member() -> Member:
    """Active member for testing."""
    return Member.reconstitute(
        member_id=MEMBER_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        account_type="Socio",
        account_type_id="880e8400-e29b-41d4-a716-446655440003",
        full_name="Juan Pérez",
        email="juan@example.com",
        status="active",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def inactive_member() -> Member:
    """Already-inactive member for testing."""
    return Member.reconstitute(
        member_id=MEMBER_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        account_type="Socio",
        account_type_id="880e8400-e29b-41d4-a716-446655440003",
        full_name="Juan Pérez",
        email="juan@example.com",
        status="inactive",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def user() -> User:
    """User entity with cognito_sub."""
    return User.reconstitute(
        user_id=USER_ID,
        email="juan@example.com",
        cognito_sub=COGNITO_SUB,
        full_name="Juan Pérez",
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def use_case(
    member_repository: MagicMock,
    user_repository: MagicMock,
    cognito_service: AsyncMock,
) -> DeactivateMemberUseCase:
    """Create a DeactivateMemberUseCase with mocked dependencies."""
    return DeactivateMemberUseCase(
        member_repository=member_repository,
        user_repository=user_repository,
        cognito_service=cognito_service,
    )


# ──── Test: Successful Deactivation (Req 8.1) ────────────────────────────────


class TestDeactivateMemberSuccess:
    """Tests for successful member deactivation (Req 8.1)."""

    @pytest.mark.asyncio
    async def test_successful_deactivation_returns_none(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        user_repository: MagicMock,
        active_member: Member,
        user: User,
    ) -> None:
        """Successful deactivation returns None (void operation)."""
        member_repository.find_by_id.return_value = active_member
        user_repository.find_by_id.return_value = user

        result = await use_case.execute(TENANT_ID, MEMBER_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_successful_deactivation_sets_status_inactive(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        user_repository: MagicMock,
        active_member: Member,
        user: User,
    ) -> None:
        """Deactivation sets the member status to inactive."""
        member_repository.find_by_id.return_value = active_member
        user_repository.find_by_id.return_value = user

        await use_case.execute(TENANT_ID, MEMBER_ID)

        member_repository.update.assert_called_once()
        updated_member = member_repository.update.call_args[0][0]
        assert updated_member.status == "inactive"

    @pytest.mark.asyncio
    async def test_successful_deactivation_refreshes_updated_at(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        user_repository: MagicMock,
        active_member: Member,
        user: User,
    ) -> None:
        """Deactivation refreshes the updated_at timestamp."""
        original_updated_at = active_member.updated_at
        member_repository.find_by_id.return_value = active_member
        user_repository.find_by_id.return_value = user

        await use_case.execute(TENANT_ID, MEMBER_ID)

        updated_member = member_repository.update.call_args[0][0]
        assert updated_member.updated_at > original_updated_at

    @pytest.mark.asyncio
    async def test_successful_deactivation_disables_user_in_cognito(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        user_repository: MagicMock,
        cognito_service: AsyncMock,
        active_member: Member,
        user: User,
    ) -> None:
        """Deactivation calls admin_disable_user with the user's cognito_sub (Req 8.1)."""
        member_repository.find_by_id.return_value = active_member
        user_repository.find_by_id.return_value = user

        await use_case.execute(TENANT_ID, MEMBER_ID)

        cognito_service.admin_disable_user.assert_called_once_with(COGNITO_SUB)

    @pytest.mark.asyncio
    async def test_successful_deactivation_preserves_member_record(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        user_repository: MagicMock,
        active_member: Member,
        user: User,
    ) -> None:
        """Deactivation preserves the full member record — uses update, not delete (Req 8.4)."""
        member_repository.find_by_id.return_value = active_member
        user_repository.find_by_id.return_value = user

        await use_case.execute(TENANT_ID, MEMBER_ID)

        member_repository.update.assert_called_once()
        updated_member = member_repository.update.call_args[0][0]
        # All historical fields preserved
        assert updated_member.member_id == MEMBER_ID
        assert updated_member.tenant_id == TENANT_ID
        assert updated_member.user_id == USER_ID
        assert updated_member.email == "juan@example.com"
        assert updated_member.full_name == "Juan Pérez"
        assert updated_member.registration_type == "self"
        assert updated_member.created_at == active_member.created_at

    @pytest.mark.asyncio
    async def test_user_record_not_modified(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        user_repository: MagicMock,
        cognito_service: AsyncMock,
        active_member: Member,
        user: User,
    ) -> None:
        """User record is NOT modified or deleted (Req 8.5)."""
        member_repository.find_by_id.return_value = active_member
        user_repository.find_by_id.return_value = user

        await use_case.execute(TENANT_ID, MEMBER_ID)

        # User repository is only used for lookup — no save/update/delete calls
        user_repository.find_by_id.assert_called_once_with(USER_ID)
        user_repository.save.assert_not_called()


# ──── Test: Member Not Found (Req 8.3) ───────────────────────────────────────


class TestMemberNotFound:
    """Tests for non-existent member (Req 8.3)."""

    @pytest.mark.asyncio
    async def test_nonexistent_member_raises_not_found_error(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
    ) -> None:
        """Non-existent member raises NotFoundError with appropriate message."""
        member_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(TENANT_ID, MEMBER_ID)

        assert "member not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_member_does_not_call_cognito(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        cognito_service: AsyncMock,
    ) -> None:
        """When member doesn't exist, Cognito is never called."""
        member_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await use_case.execute(TENANT_ID, MEMBER_ID)

        cognito_service.admin_disable_user.assert_not_called()


# ──── Test: Already Inactive (Req 8.2) ───────────────────────────────────────


class TestAlreadyInactive:
    """Tests for already-inactive member (Req 8.2)."""

    @pytest.mark.asyncio
    async def test_already_inactive_raises_validation_error(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        inactive_member: Member,
    ) -> None:
        """Already inactive member raises ValidationError."""
        member_repository.find_by_id.return_value = inactive_member

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(TENANT_ID, MEMBER_ID)

        assert "already inactive" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_already_inactive_does_not_update_or_call_cognito(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        cognito_service: AsyncMock,
        inactive_member: Member,
    ) -> None:
        """Already inactive member does not trigger update or Cognito call."""
        member_repository.find_by_id.return_value = inactive_member

        with pytest.raises(ValidationError):
            await use_case.execute(TENANT_ID, MEMBER_ID)

        member_repository.update.assert_not_called()
        cognito_service.admin_disable_user.assert_not_called()


# ──── Test: Input Validation (TenantId) ──────────────────────────────────────


class TestInputValidation:
    """Tests for input validation at the use case boundary."""

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_raises_validation_error(
        self,
        use_case: DeactivateMemberUseCase,
    ) -> None:
        """Invalid UUID format for tenant_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute("not-a-uuid", MEMBER_ID)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_empty_tenant_id_raises_validation_error(
        self,
        use_case: DeactivateMemberUseCase,
    ) -> None:
        """Empty tenant_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute("", MEMBER_ID)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_validation_errors_short_circuit_before_repo_calls(
        self,
        use_case: DeactivateMemberUseCase,
        member_repository: MagicMock,
        cognito_service: AsyncMock,
    ) -> None:
        """Validation failures prevent any repository or Cognito calls."""
        with pytest.raises(ValidationError):
            await use_case.execute("invalid", MEMBER_ID)

        member_repository.find_by_id.assert_not_called()
        cognito_service.admin_disable_user.assert_not_called()
