"""Unit tests for UpdateMemberUseCase."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.member.updateMemberInputDto import UpdateMemberInputDTO
from api.member.updateMemberUseCase import UpdateMemberUseCase
from api.accountType.accountType import AccountType
from api.member.member import Member
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError


# ──── Constants ───────────────────────────────────────────────────────────────

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
MEMBER_ID = "660e8400-e29b-41d4-a716-446655440001"
USER_ID = "770e8400-e29b-41d4-a716-446655440002"
ACCOUNT_TYPE_ID = "880e8400-e29b-41d4-a716-446655440003"
NEW_ACCOUNT_TYPE_ID = "990e8400-e29b-41d4-a716-446655440004"


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def member_repository() -> MagicMock:
    """Mock IMemberRepository (sync methods)."""
    mock = MagicMock()
    mock.update.side_effect = lambda m: m
    return mock


@pytest.fixture
def account_type_repository() -> AsyncMock:
    """Mock IAccountTypeRepository (async methods)."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def existing_member() -> Member:
    """An existing member in the database."""
    now = datetime.now(UTC)
    return Member.reconstitute(
        member_id=MEMBER_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        account_type="socio",
        account_type_id=ACCOUNT_TYPE_ID,
        full_name="Juan García",
        email="juan@example.com",
        status="active",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=now - timedelta(days=30),
        updated_at=now - timedelta(days=5),
    )


@pytest.fixture
def active_account_type() -> AccountType:
    """An active account type for validation."""
    return AccountType.reconstitute(
        account_type_id=NEW_ACCOUNT_TYPE_ID,
        tenant_id=TENANT_ID,
        name="profesional",
        description="Professional membership",
        config=None,
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def inactive_account_type() -> AccountType:
    """An inactive account type for validation."""
    return AccountType.reconstitute(
        account_type_id=NEW_ACCOUNT_TYPE_ID,
        tenant_id=TENANT_ID,
        name="profesional",
        description="Professional membership",
        config=None,
        status="inactive",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def use_case(
    member_repository: MagicMock,
    account_type_repository: AsyncMock,
) -> UpdateMemberUseCase:
    """Create an UpdateMemberUseCase with mocked dependencies."""
    return UpdateMemberUseCase(
        member_repository=member_repository,
        account_type_repository=account_type_repository,
    )


# ──── Test: Successful Update (Req 7.3) ──────────────────────────────────────


class TestUpdateMemberSuccess:
    """Tests for successful member update (Req 7.3)."""

    @pytest.mark.asyncio
    async def test_update_full_name_returns_output_dto(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        existing_member: Member,
    ) -> None:
        """Updating full_name returns MemberOutputDTO with updated value."""
        member_repository.find_by_id.return_value = existing_member
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            full_name="Juan Carlos García",
        )

        result = await use_case.execute(input_dto)

        assert result.full_name == "Juan Carlos García"
        assert result.member_id == MEMBER_ID
        assert result.tenant_id == TENANT_ID

    @pytest.mark.asyncio
    async def test_update_preserves_immutable_fields(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        existing_member: Member,
    ) -> None:
        """Update preserves created_at, registration_type, and invited_by."""
        member_repository.find_by_id.return_value = existing_member
        original_created_at = existing_member.created_at
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            full_name="Nuevo Nombre",
        )

        result = await use_case.execute(input_dto)

        assert result.created_at == original_created_at
        assert result.registration_type == "self"
        assert result.invited_by is None

    @pytest.mark.asyncio
    async def test_update_refreshes_updated_at(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        existing_member: Member,
    ) -> None:
        """Update refreshes updated_at timestamp."""
        member_repository.find_by_id.return_value = existing_member
        original_updated_at = existing_member.updated_at
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            email="newemail@example.com",
        )

        result = await use_case.execute(input_dto)

        assert result.updated_at > original_updated_at

    @pytest.mark.asyncio
    async def test_update_persists_via_repository(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        existing_member: Member,
    ) -> None:
        """Updated member is persisted via repository.update()."""
        member_repository.find_by_id.return_value = existing_member
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            full_name="Updated Name",
        )

        await use_case.execute(input_dto)

        member_repository.update.assert_called_once()
        persisted = member_repository.update.call_args[0][0]
        assert isinstance(persisted, Member)
        assert persisted.full_name == "Updated Name"


# ──── Test: Account Type Validation (Req 7.1, 7.4, 7.5) ─────────────────────


class TestAccountTypeValidation:
    """Tests for account type change validation (Req 7.1, 7.4, 7.5)."""

    @pytest.mark.asyncio
    async def test_update_account_type_validates_exists_and_active(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        account_type_repository: AsyncMock,
        existing_member: Member,
        active_account_type: AccountType,
    ) -> None:
        """Changing account_type validates it exists and is active (Req 7.1)."""
        member_repository.find_by_id.return_value = existing_member
        account_type_repository.find_by_name_in_tenant.return_value = active_account_type
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            account_type="profesional",
        )

        result = await use_case.execute(input_dto)

        assert result.account_type == "profesional"
        assert result.account_type_id == NEW_ACCOUNT_TYPE_ID
        account_type_repository.find_by_name_in_tenant.assert_called_once_with(
            tenant_id=TENANT_ID,
            name="profesional",
        )

    @pytest.mark.asyncio
    async def test_nonexistent_account_type_raises_not_found(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        account_type_repository: AsyncMock,
        existing_member: Member,
    ) -> None:
        """Non-existent account type raises NotFoundError (Req 7.4)."""
        member_repository.find_by_id.return_value = existing_member
        account_type_repository.find_by_name_in_tenant.return_value = None
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            account_type="nonexistent",
        )

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(input_dto)

        assert "Account type does not exist in this tenant" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_inactive_account_type_raises_domain_error(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        account_type_repository: AsyncMock,
        existing_member: Member,
        inactive_account_type: AccountType,
    ) -> None:
        """Inactive account type raises DomainError (Req 7.5)."""
        member_repository.find_by_id.return_value = existing_member
        account_type_repository.find_by_name_in_tenant.return_value = inactive_account_type
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            account_type="profesional",
        )

        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(input_dto)

        assert "Account type is not active" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_no_account_type_change_skips_validation(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
        account_type_repository: AsyncMock,
        existing_member: Member,
    ) -> None:
        """When account_type is not provided, no account type validation occurs."""
        member_repository.find_by_id.return_value = existing_member
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            full_name="New Name Only",
        )

        await use_case.execute(input_dto)

        account_type_repository.find_by_name_in_tenant.assert_not_called()


# ──── Test: Member Not Found (Req 7.2) ───────────────────────────────────────


class TestMemberNotFound:
    """Tests for non-existent member (Req 7.2)."""

    @pytest.mark.asyncio
    async def test_nonexistent_member_raises_not_found(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
    ) -> None:
        """Non-existent member raises NotFoundError (Req 7.2)."""
        member_repository.find_by_id.return_value = None
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            full_name="Does not matter",
        )

        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(input_dto)

        assert "Member not found" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_nonexistent_member_does_not_persist(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
    ) -> None:
        """When member doesn't exist, nothing is persisted."""
        member_repository.find_by_id.return_value = None
        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            full_name="Does not matter",
        )

        with pytest.raises(NotFoundError):
            await use_case.execute(input_dto)

        member_repository.update.assert_not_called()


# ──── Test: Input Validation (TenantId) ──────────────────────────────────────


class TestInputValidation:
    """Tests for input validation at the use case boundary."""

    @pytest.mark.asyncio
    async def test_invalid_tenant_id_raises_validation_error(
        self,
        use_case: UpdateMemberUseCase,
    ) -> None:
        """Invalid UUID format for tenant_id raises ValidationError."""
        input_dto = UpdateMemberInputDTO(
            tenant_id="not-a-uuid",
            member_id=MEMBER_ID,
            full_name="Test",
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_empty_tenant_id_raises_validation_error(
        self,
        use_case: UpdateMemberUseCase,
    ) -> None:
        """Empty tenant_id raises ValidationError."""
        input_dto = UpdateMemberInputDTO(
            tenant_id="",
            member_id=MEMBER_ID,
            full_name="Test",
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.field == "tenant_id"

    @pytest.mark.asyncio
    async def test_validation_error_prevents_repo_calls(
        self,
        use_case: UpdateMemberUseCase,
        member_repository: MagicMock,
    ) -> None:
        """Validation failures prevent any repository calls."""
        input_dto = UpdateMemberInputDTO(
            tenant_id="invalid",
            member_id=MEMBER_ID,
            full_name="Test",
        )

        with pytest.raises(ValidationError):
            await use_case.execute(input_dto)

        member_repository.find_by_id.assert_not_called()
        member_repository.update.assert_not_called()
