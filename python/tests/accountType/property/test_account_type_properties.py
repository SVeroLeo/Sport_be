"""Property-based tests for Account Type use cases.

**Validates: Requirements 5.2, 5.5, 5.7**

Properties tested:
- Property 4: account_type Name Uniqueness per Tenant
- Property 9: account_type Deletion Protection
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from api.accountType.createAccountTypeInputDto import (
    CreateAccountTypeInputDTO,
)
from api.accountType.updateAccountTypeInputDto import (
    UpdateAccountTypeInputDTO,
)
from api.accountType.createAccountTypeUseCase import (
    CreateAccountTypeUseCase,
)
from api.accountType.deleteAccountTypeUseCase import (
    DeleteAccountTypeUseCase,
)
from api.accountType.updateAccountTypeUseCase import (
    UpdateAccountTypeUseCase,
)
from api.accountType.accountType import AccountType
from api.common.tenant.tenant import Tenant
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.tenant.tenantId import TenantId


# ─── Constants ────────────────────────────────────────────────────────────────

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
ACCOUNT_TYPE_ID = "660e8400-e29b-41d4-a716-446655440001"
OTHER_ACCOUNT_TYPE_ID = "770e8400-e29b-41d4-a716-446655440002"


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid account type names: non-empty text up to 100 chars, stripped is non-empty
valid_account_type_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        blacklist_characters="\x00\t\n\r",
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

# Positive integers for active member counts
positive_active_counts = st.integers(min_value=1, max_value=1000)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_active_tenant() -> Tenant:
    """Create an active Tenant entity for testing."""
    return Tenant.create(
        tenant_id=TenantId.create(TENANT_ID),
        name="Club Deportivo Test",
        plan="premium",
        status="active",
        allow_self_registration=True,
        default_account_type="socio",
    )


def _make_existing_account_type(name: str, account_type_id: str = ACCOUNT_TYPE_ID) -> AccountType:
    """Create an existing AccountType entity for testing."""
    return AccountType.reconstitute(
        account_type_id=account_type_id,
        tenant_id=TENANT_ID,
        name=name,
        description="Existing account type",
        config=None,
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


# ─── Property 4: account_type Name Uniqueness per Tenant ─────────────────────


class TestAccountTypeNameUniquenessCreate:
    """Property 4: account_type Name Uniqueness per Tenant (CREATE).

    For any valid name that already exists in the tenant (case-insensitive),
    CreateAccountTypeUseCase must ALWAYS raise ConflictError.

    **Validates: Requirements 5.2**
    """

    @given(name=valid_account_type_names)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_create_with_existing_name_always_raises_conflict_error(
        self,
        name: str,
    ) -> None:
        """For ANY valid name that already exists in the tenant,
        CreateAccountTypeUseCase ALWAYS raises ConflictError.

        **Validates: Requirements 5.2**
        """
        # Arrange
        account_type_repository = AsyncMock()
        tenant_repository = AsyncMock()

        # Tenant exists
        tenant_repository.find_by_id.return_value = _make_active_tenant()

        # Name already exists (simulates case-insensitive match)
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_existing_account_type(name.lower())
        )
        account_type_repository.save.side_effect = lambda at: at

        use_case = CreateAccountTypeUseCase(
            account_type_repository=account_type_repository,
            tenant_repository=tenant_repository,
        )

        input_dto = CreateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            name=name,
            description="Test description",
        )

        # Act & Assert
        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(input_dto)

        assert "already exists" in exc_info.value.message.lower()
        # Verify nothing was persisted
        account_type_repository.save.assert_not_called()

    @given(name=valid_account_type_names)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_create_with_case_variant_name_always_raises_conflict_error(
        self,
        name: str,
    ) -> None:
        """For ANY name where a case-variant already exists,
        CreateAccountTypeUseCase ALWAYS raises ConflictError.

        The repository performs case-insensitive lookup, so providing
        the name in any case variant should still be detected.

        **Validates: Requirements 5.2**
        """
        # Arrange
        account_type_repository = AsyncMock()
        tenant_repository = AsyncMock()

        tenant_repository.find_by_id.return_value = _make_active_tenant()

        # Existing account type has the UPPER case version of the name
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_existing_account_type(name.upper())
        )
        account_type_repository.save.side_effect = lambda at: at

        use_case = CreateAccountTypeUseCase(
            account_type_repository=account_type_repository,
            tenant_repository=tenant_repository,
        )

        # Input uses the original case
        input_dto = CreateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            name=name,
        )

        # Act & Assert
        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(input_dto)

        assert "already exists" in exc_info.value.message.lower()
        account_type_repository.save.assert_not_called()


class TestAccountTypeNameUniquenessUpdate:
    """Property 4: account_type Name Uniqueness per Tenant (UPDATE).

    For any valid new name that already exists in the tenant (case-insensitive)
    and belongs to a DIFFERENT account type, UpdateAccountTypeUseCase must
    ALWAYS raise ConflictError.

    **Validates: Requirements 5.5**
    """

    @given(name=valid_account_type_names)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_update_with_name_belonging_to_different_account_type_raises_conflict(
        self,
        name: str,
    ) -> None:
        """For ANY new name that belongs to a DIFFERENT account type in the tenant,
        UpdateAccountTypeUseCase ALWAYS raises ConflictError.

        **Validates: Requirements 5.5**
        """
        # Arrange
        account_type_repository = AsyncMock()

        # The account type being updated exists with a different name
        existing = _make_existing_account_type("original_name", ACCOUNT_TYPE_ID)
        account_type_repository.find_by_id.return_value = existing

        # A DIFFERENT account type already has the requested name
        duplicate = _make_existing_account_type(name.lower(), OTHER_ACCOUNT_TYPE_ID)
        account_type_repository.find_by_name_in_tenant.return_value = duplicate

        account_type_repository.update.side_effect = lambda at: at

        use_case = UpdateAccountTypeUseCase(
            account_type_repository=account_type_repository,
        )

        input_dto = UpdateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            account_type_id=ACCOUNT_TYPE_ID,
            name=name,
        )

        # Act & Assert
        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(input_dto)

        assert "already exists" in exc_info.value.message.lower()
        # Verify entity was not updated/persisted
        account_type_repository.update.assert_not_called()

    @given(name=valid_account_type_names)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_update_with_case_variant_name_belonging_to_different_type_raises_conflict(
        self,
        name: str,
    ) -> None:
        """For ANY case-variant of a name belonging to a DIFFERENT account type,
        UpdateAccountTypeUseCase ALWAYS raises ConflictError.

        **Validates: Requirements 5.5**
        """
        # Arrange
        account_type_repository = AsyncMock()

        # Existing account type being updated
        existing = _make_existing_account_type("something_else", ACCOUNT_TYPE_ID)
        account_type_repository.find_by_id.return_value = existing

        # Another account type owns this name (upper case variant)
        duplicate = _make_existing_account_type(name.upper(), OTHER_ACCOUNT_TYPE_ID)
        account_type_repository.find_by_name_in_tenant.return_value = duplicate

        account_type_repository.update.side_effect = lambda at: at

        use_case = UpdateAccountTypeUseCase(
            account_type_repository=account_type_repository,
        )

        input_dto = UpdateAccountTypeInputDTO(
            tenant_id=TENANT_ID,
            account_type_id=ACCOUNT_TYPE_ID,
            name=name,
        )

        # Act & Assert
        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(input_dto)

        assert "already exists" in exc_info.value.message.lower()
        account_type_repository.update.assert_not_called()


# ─── Property 9: account_type Deletion Protection ────────────────────────────


class TestAccountTypeDeletionProtection:
    """Property 9: account_type Deletion Protection.

    For any account type that has at least 1 active member,
    DeleteAccountTypeUseCase must ALWAYS raise DomainError with
    "active members" in the message, and the entity is never deactivated.

    **Validates: Requirements 5.7**
    """

    @given(active_count=positive_active_counts)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_any_positive_active_count_always_raises_domain_error(
        self,
        active_count: int,
    ) -> None:
        """For ANY positive active member count (1-1000),
        DeleteAccountTypeUseCase ALWAYS raises DomainError.

        **Validates: Requirements 5.7**
        """
        # Arrange
        account_type_repository = AsyncMock()
        member_repository = MagicMock()

        existing = _make_existing_account_type("Profesional")
        account_type_repository.find_by_id.return_value = existing

        # Sync method returns a positive count
        member_repository.count_active_by_account_type.return_value = active_count

        account_type_repository.update.side_effect = lambda at: at

        use_case = DeleteAccountTypeUseCase(
            account_type_repository=account_type_repository,
            member_repository=member_repository,
        )

        # Act & Assert
        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        assert "active members" in exc_info.value.message.lower()
        # Entity is never deactivated — update is never called
        account_type_repository.update.assert_not_called()
        # Status remains "active" — deactivate() was never called
        assert existing.status == "active"

    @given(active_count=positive_active_counts)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_deletion_protection_never_modifies_entity(
        self,
        active_count: int,
    ) -> None:
        """For ANY account type with active members, the entity is never modified.

        The deactivate() method is never called and updated_at stays the same.

        **Validates: Requirements 5.7**
        """
        # Arrange
        account_type_repository = AsyncMock()
        member_repository = MagicMock()

        existing = _make_existing_account_type("Socio")
        original_updated_at = existing.updated_at
        account_type_repository.find_by_id.return_value = existing

        member_repository.count_active_by_account_type.return_value = active_count

        use_case = DeleteAccountTypeUseCase(
            account_type_repository=account_type_repository,
            member_repository=member_repository,
        )

        # Act & Assert
        with pytest.raises(DomainError):
            await use_case.execute(TENANT_ID, ACCOUNT_TYPE_ID)

        # Entity was never modified
        assert existing.status == "active"
        assert existing.updated_at == original_updated_at
