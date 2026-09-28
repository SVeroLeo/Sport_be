"""Property-based tests for Member use cases.

**Validates: Requirements 5.6, 7.3, 7.4, 7.5, 8.1, 8.4, 8.5**

Properties tested:
- Property 5: Soft Delete Preservation
- Property 7: Member-account_type Referential Integrity
- Property 11: Session Invalidation on Deactivation
- Property 16: Member Update Preserves Immutable Fields
- Property 19: Filter Correctness
- Property 20: User Record Preservation on Member Deactivation
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from api.member.updateMemberInputDto import UpdateMemberInputDTO
from api.common.ports.sharedTypes import MemberFilters, PaginatedResult, PaginationParams
from api.member.deactivateMemberUseCase import DeactivateMemberUseCase
from api.member.listMembersUseCase import ListMembersUseCase
from api.member.updateMemberUseCase import UpdateMemberUseCase
from api.accountType.accountType import AccountType
from api.member.member import Member
from api.common.user.users import User
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError


# ─── Constants ────────────────────────────────────────────────────────────────

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
MEMBER_ID = "660e8400-e29b-41d4-a716-446655440001"
USER_ID = "770e8400-e29b-41d4-a716-446655440002"
ACCOUNT_TYPE_ID = "880e8400-e29b-41d4-a716-446655440003"
NEW_ACCOUNT_TYPE_ID = "990e8400-e29b-41d4-a716-446655440004"
COGNITO_SUB = "cognito-sub-12345"

FIXED_CREATED_AT = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
FIXED_UPDATED_AT = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid full names (1 to 200 chars, non-whitespace-only)
valid_full_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        blacklist_characters="\x00\t\n\r",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

# Valid emails for testing (simplified valid patterns)
valid_emails = st.from_regex(r"[a-z][a-z0-9]{1,10}@[a-z]{2,6}\.[a-z]{2,4}", fullmatch=True)

# Valid member statuses
valid_statuses = st.sampled_from(["active", "inactive", "pending_confirmation"])

# Valid registration types
valid_registration_types = st.sampled_from(["self", "invited"])

# Optional invited_by (UUID-like or None)
optional_invited_by = st.one_of(
    st.none(),
    st.just("aaa00000-bbbb-cccc-dddd-eeeeeeeeeeee"),
)

# Metadata strategies
metadata_values = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-100, max_value=100),
    st.booleans(),
)
optional_metadata = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=10),
        values=metadata_values,
        min_size=0,
        max_size=3,
    ),
)

# Account type names for testing
account_type_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        blacklist_characters="\x00\t\n\r",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

# Cognito sub values
cognito_subs = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=5,
    max_size=40,
).filter(lambda s: len(s.strip()) >= 5)

# Filter strategies for Property 19
optional_filter_account_type = st.one_of(st.none(), account_type_names)
optional_filter_status = st.one_of(
    st.none(),
    st.sampled_from(["active", "inactive", "pending_confirmation"]),
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_active_member(
    full_name: str = "Juan Pérez",
    email: str = "juan@example.com",
    account_type: str = "socio",
    registration_type: str = "self",
    invited_by: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Member:
    """Create an active Member entity for testing."""
    return Member.reconstitute(
        member_id=MEMBER_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        account_type=account_type,
        account_type_id=ACCOUNT_TYPE_ID,
        full_name=full_name,
        email=email,
        status="active",
        registration_type=registration_type,
        invited_by=invited_by,
        metadata=metadata,
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
    )


def _make_user(cognito_sub: str = COGNITO_SUB) -> User:
    """Create a User entity for testing."""
    return User.reconstitute(
        user_id=USER_ID,
        email="juan@example.com",
        cognito_sub=cognito_sub,
        full_name="Juan Pérez",
        status="active",
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
    )


def _make_active_account_type(name: str = "socio") -> AccountType:
    """Create an active AccountType entity for testing."""
    return AccountType.reconstitute(
        account_type_id=NEW_ACCOUNT_TYPE_ID,
        tenant_id=TENANT_ID,
        name=name,
        description="Test account type",
        config=None,
        status="active",
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
    )


def _make_inactive_account_type(name: str = "profesional") -> AccountType:
    """Create an inactive AccountType entity for testing."""
    return AccountType.reconstitute(
        account_type_id=NEW_ACCOUNT_TYPE_ID,
        tenant_id=TENANT_ID,
        name=name,
        description="Inactive account type",
        config=None,
        status="inactive",
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
    )


# ─── Property 5: Soft Delete Preservation ────────────────────────────────────


class TestSoftDeletePreservation:
    """Property 5: Soft Delete Preservation.

    For any active member that is deactivated, ALL historical fields
    (member_id, tenant_id, user_id, email, full_name, account_type,
    account_type_id, registration_type, invited_by, created_at) MUST be
    preserved in the persisted record. Only status changes to "inactive"
    and updated_at is refreshed.

    **Validates: Requirements 8.4**
    """

    @given(
        full_name=valid_full_names,
        email=valid_emails,
        account_type=account_type_names,
        registration_type=valid_registration_types,
        invited_by=optional_invited_by,
        metadata=optional_metadata,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_deactivation_preserves_all_historical_fields(
        self,
        full_name: str,
        email: str,
        account_type: str,
        registration_type: str,
        invited_by: str | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        """For ANY active member, deactivation preserves all historical fields.

        **Validates: Requirements 8.4**
        """
        # Arrange
        member = _make_active_member(
            full_name=full_name,
            email=email,
            account_type=account_type,
            registration_type=registration_type,
            invited_by=invited_by if registration_type == "invited" else None,
            metadata=metadata,
        )

        member_repository = MagicMock()
        user_repository = MagicMock()
        cognito_service = AsyncMock()

        member_repository.find_by_id.return_value = member
        member_repository.update.side_effect = lambda m: m
        user_repository.find_by_id.return_value = _make_user()
        cognito_service.admin_disable_user.return_value = None

        use_case = DeactivateMemberUseCase(
            member_repository=member_repository,
            user_repository=user_repository,
            cognito_service=cognito_service,
        )

        # Act
        await use_case.execute(TENANT_ID, MEMBER_ID)

        # Assert — capture what was persisted
        persisted = member_repository.update.call_args[0][0]

        # All historical fields are preserved
        assert persisted.member_id == MEMBER_ID
        assert persisted.tenant_id == TENANT_ID
        assert persisted.user_id == USER_ID
        assert persisted.email == email
        assert persisted.full_name == full_name
        assert persisted.account_type == account_type
        assert persisted.account_type_id == ACCOUNT_TYPE_ID
        assert persisted.registration_type == registration_type
        assert persisted.invited_by == (invited_by if registration_type == "invited" else None)
        assert persisted.created_at == FIXED_CREATED_AT

        # Status changed to inactive
        assert persisted.status == "inactive"

        # updated_at is refreshed (different from original)
        assert persisted.updated_at > FIXED_UPDATED_AT


# ─── Property 7: Member-account_type Referential Integrity ───────────────────


class TestMemberAccountTypeReferentialIntegrity:
    """Property 7: Member-account_type Referential Integrity.

    For any account_type that does NOT exist or is inactive in the tenant,
    UpdateMemberUseCase MUST ALWAYS reject the update. For any account_type
    that exists and is active, the update MUST succeed.

    **Validates: Requirements 7.3, 7.4, 7.5**
    """

    @given(account_type_name=account_type_names)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_update_with_nonexistent_account_type_always_raises_not_found(
        self,
        account_type_name: str,
    ) -> None:
        """For ANY account_type name that does NOT exist in the tenant,
        UpdateMemberUseCase ALWAYS raises NotFoundError.

        **Validates: Requirements 7.4**
        """
        # Arrange
        member_repository = MagicMock()
        account_type_repository = AsyncMock()

        member_repository.find_by_id.return_value = _make_active_member()
        account_type_repository.find_by_name_in_tenant.return_value = None
        member_repository.update.side_effect = lambda m: m

        use_case = UpdateMemberUseCase(
            member_repository=member_repository,
            account_type_repository=account_type_repository,
        )

        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            account_type=account_type_name,
        )

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await use_case.execute(input_dto)

        assert "account type" in exc_info.value.message.lower() or "account_type" in exc_info.value.message.lower()
        member_repository.update.assert_not_called()

    @given(account_type_name=account_type_names)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_update_with_inactive_account_type_always_raises_domain_error(
        self,
        account_type_name: str,
    ) -> None:
        """For ANY account_type that is inactive in the tenant,
        UpdateMemberUseCase ALWAYS raises DomainError.

        **Validates: Requirements 7.5**
        """
        # Arrange
        member_repository = MagicMock()
        account_type_repository = AsyncMock()

        member_repository.find_by_id.return_value = _make_active_member()
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_inactive_account_type(account_type_name)
        )
        member_repository.update.side_effect = lambda m: m

        use_case = UpdateMemberUseCase(
            member_repository=member_repository,
            account_type_repository=account_type_repository,
        )

        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            account_type=account_type_name,
        )

        # Act & Assert
        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(input_dto)

        assert "not active" in exc_info.value.message.lower()
        member_repository.update.assert_not_called()

    @given(account_type_name=account_type_names)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_update_with_active_account_type_always_succeeds(
        self,
        account_type_name: str,
    ) -> None:
        """For ANY account_type that exists and is active in the tenant,
        UpdateMemberUseCase ALWAYS succeeds.

        **Validates: Requirements 7.3**
        """
        # Arrange
        member_repository = MagicMock()
        account_type_repository = AsyncMock()

        member_repository.find_by_id.return_value = _make_active_member()
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_active_account_type(account_type_name)
        )
        member_repository.update.side_effect = lambda m: m

        use_case = UpdateMemberUseCase(
            member_repository=member_repository,
            account_type_repository=account_type_repository,
        )

        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            account_type=account_type_name,
        )

        # Act
        result = await use_case.execute(input_dto)

        # Assert — update succeeded (account_type is stripped by Member.update())
        member_repository.update.assert_called_once()
        assert result.account_type == account_type_name.strip()


# ─── Property 11: Session Invalidation on Deactivation ───────────────────────


class TestSessionInvalidationOnDeactivation:
    """Property 11: Session Invalidation on Deactivation.

    For any successful member deactivation, admin_disable_user MUST ALWAYS
    be called with the user's cognito_sub to invalidate Cognito tokens.

    **Validates: Requirements 8.1**
    """

    @given(cognito_sub=cognito_subs)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_deactivation_always_calls_admin_disable_user_with_cognito_sub(
        self,
        cognito_sub: str,
    ) -> None:
        """For ANY successful deactivation, admin_disable_user is ALWAYS called
        with the correct cognito_sub.

        **Validates: Requirements 8.1**
        """
        # Arrange
        member_repository = MagicMock()
        user_repository = MagicMock()
        cognito_service = AsyncMock()

        member_repository.find_by_id.return_value = _make_active_member()
        member_repository.update.side_effect = lambda m: m
        user_repository.find_by_id.return_value = _make_user(cognito_sub=cognito_sub)
        cognito_service.admin_disable_user.return_value = None

        use_case = DeactivateMemberUseCase(
            member_repository=member_repository,
            user_repository=user_repository,
            cognito_service=cognito_service,
        )

        # Act
        await use_case.execute(TENANT_ID, MEMBER_ID)

        # Assert — admin_disable_user was called exactly once with the correct sub
        cognito_service.admin_disable_user.assert_called_once_with(cognito_sub)


# ─── Property 16: Member Update Preserves Immutable Fields ───────────────────


class TestMemberUpdatePreservesImmutableFields:
    """Property 16: Member Update Preserves Immutable Fields.

    For ANY combination of update fields, the member's created_at,
    registration_type, and invited_by MUST NEVER change.
    updated_at MUST be refreshed.

    **Validates: Requirements 7.3**
    """

    @given(
        new_full_name=st.one_of(st.none(), valid_full_names),
        new_email=st.one_of(st.none(), valid_emails),
        new_status=st.one_of(st.none(), valid_statuses),
        new_metadata=optional_metadata,
        registration_type=valid_registration_types,
        invited_by=optional_invited_by,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_update_never_changes_immutable_fields(
        self,
        new_full_name: str | None,
        new_email: str | None,
        new_status: str | None,
        new_metadata: dict[str, Any] | None,
        registration_type: str,
        invited_by: str | None,
    ) -> None:
        """For ANY update combination, immutable fields are preserved.

        **Validates: Requirements 7.3**
        """
        # Arrange
        effective_invited_by = invited_by if registration_type == "invited" else None

        member = _make_active_member(
            registration_type=registration_type,
            invited_by=effective_invited_by,
        )

        member_repository = MagicMock()
        account_type_repository = AsyncMock()

        member_repository.find_by_id.return_value = member
        member_repository.update.side_effect = lambda m: m

        use_case = UpdateMemberUseCase(
            member_repository=member_repository,
            account_type_repository=account_type_repository,
        )

        input_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_ID,
            member_id=MEMBER_ID,
            full_name=new_full_name,
            email=new_email,
            status=new_status,
            metadata=new_metadata,
        )

        # Act
        result = await use_case.execute(input_dto)

        # Assert — immutable fields are NEVER changed
        assert result.created_at == FIXED_CREATED_AT
        assert result.registration_type == registration_type
        assert result.invited_by == effective_invited_by

        # updated_at MUST be refreshed (newer than original)
        assert result.updated_at > FIXED_UPDATED_AT


# ─── Property 19: Filter Correctness ─────────────────────────────────────────


class TestFilterCorrectness:
    """Property 19: Filter Correctness.

    For any MemberFilters (account_type, status), the use case ALWAYS
    passes those filters to the repository. The repository is called with
    the correct tenant_id and filters.

    **Validates: Requirements 5.6**
    """

    @given(
        filter_account_type=optional_filter_account_type,
        filter_status=optional_filter_status,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_filters_always_passed_correctly_to_repository(
        self,
        filter_account_type: str | None,
        filter_status: str | None,
    ) -> None:
        """For ANY filter combination, the repository is called with the
        correct tenant_id and filters.

        **Validates: Requirements 5.6**
        """
        # Arrange
        member_repository = AsyncMock()
        member_repository.find_by_tenant_and_filters.return_value = PaginatedResult(
            items=[], next_cursor=None
        )

        use_case = ListMembersUseCase(member_repository=member_repository)

        filters = MemberFilters(
            account_type=filter_account_type,
            status=filter_status,
        )
        pagination = PaginationParams(limit=20, cursor=None)

        # Act
        await use_case.execute(
            tenant_id=TENANT_ID,
            filters=filters,
            pagination=pagination,
        )

        # Assert — repository is called with the correct arguments
        member_repository.find_by_tenant_and_filters.assert_called_once_with(
            tenant_id=TENANT_ID,
            filters=filters,
            pagination=pagination,
        )

        # Verify the filters contain the correct values
        call_kwargs = member_repository.find_by_tenant_and_filters.call_args[1]
        assert call_kwargs["filters"].account_type == filter_account_type
        assert call_kwargs["filters"].status == filter_status
        assert call_kwargs["tenant_id"] == TENANT_ID


# ─── Property 20: User Record Preservation on Member Deactivation ─────────────


class TestUserRecordPreservationOnDeactivation:
    """Property 20: User Record Preservation on Member Deactivation.

    For any member deactivation, the User repository's save/update is NEVER
    called. The user record is ONLY read (find_by_id), never modified.

    **Validates: Requirements 8.5**
    """

    @given(
        full_name=valid_full_names,
        email=valid_emails,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_deactivation_never_modifies_user_record(
        self,
        full_name: str,
        email: str,
        cognito_sub: str,
    ) -> None:
        """For ANY deactivation, the User repository is only read, never written.

        **Validates: Requirements 8.5**
        """
        # Arrange
        member = _make_active_member(full_name=full_name, email=email)

        member_repository = MagicMock()
        user_repository = MagicMock()
        cognito_service = AsyncMock()

        member_repository.find_by_id.return_value = member
        member_repository.update.side_effect = lambda m: m
        user_repository.find_by_id.return_value = _make_user(cognito_sub=cognito_sub)
        cognito_service.admin_disable_user.return_value = None

        use_case = DeactivateMemberUseCase(
            member_repository=member_repository,
            user_repository=user_repository,
            cognito_service=cognito_service,
        )

        # Act
        await use_case.execute(TENANT_ID, MEMBER_ID)

        # Assert — user_repository was read but NEVER written
        user_repository.find_by_id.assert_called_once_with(USER_ID)
        user_repository.save.assert_not_called()
        user_repository.update.assert_not_called()
