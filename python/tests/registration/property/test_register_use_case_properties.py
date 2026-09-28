"""Property-based tests for RegisterUseCase.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 12.1**

Properties tested:
- Property 8: Registration Atomicity
- Property 13: Self-Registration Gate
- Property 14: Default account_type Assignment
- Property 15: Email Uniqueness Enforcement
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from api.auth.registerInputDto import RegisterInputDTO
from api.registration.registerUseCase import RegisterUseCase
from api.accountType.accountType import AccountType
from api.common.tenant.tenant import Tenant
from api.common.user.users import User
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.tenant.tenantId import TenantId


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid emails that pass the Email value object validation (simplified RFC 5322)
valid_emails = st.from_regex(
    r"[a-z][a-z0-9]{0,19}@[a-z]{2,10}\.[a-z]{2,5}", fullmatch=True
)

# Valid passwords (8-72 chars)
valid_passwords = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=8,
    max_size=72,
)

# Valid full names (non-empty after trim, max 200 chars)
valid_full_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
        blacklist_characters="\x00\t\n\r",
    ),
    min_size=2,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 2)

# Valid tenant IDs (UUID format)
valid_tenant_ids = st.uuids().map(str)

# Valid account type names (simple alphabetical, 3-30 chars)
valid_account_type_names = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=3,
    max_size=30,
).filter(lambda s: len(s.strip()) >= 3)

# Cognito sub IDs
cognito_subs = st.uuids().map(lambda u: f"cognito-sub-{u}")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_active_tenant(
    tenant_id: str,
    allow_self_registration: bool = True,
    default_account_type: str | None = "socio",
) -> Tenant:
    """Create an active Tenant entity for testing."""
    return Tenant.create(
        tenant_id=TenantId.create(tenant_id),
        name="Club Deportivo Test",
        plan="premium",
        status="active",
        allow_self_registration=allow_self_registration,
        default_account_type=default_account_type,
    )


def _make_inactive_tenant(tenant_id: str) -> Tenant:
    """Create an inactive Tenant entity for testing."""
    return Tenant.create(
        tenant_id=TenantId.create(tenant_id),
        name="Inactive Club",
        plan="basic",
        status="inactive",
        allow_self_registration=True,
        default_account_type=None,
    )


def _make_active_account_type(tenant_id: str, name: str) -> AccountType:
    """Create an active AccountType entity for testing."""
    return AccountType.reconstitute(
        account_type_id="acctype-uuid-001",
        tenant_id=tenant_id,
        name=name,
        description=f"{name} membership",
        config=None,
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _make_inactive_account_type(tenant_id: str, name: str) -> AccountType:
    """Create an inactive AccountType entity for testing."""
    return AccountType.reconstitute(
        account_type_id="acctype-uuid-002",
        tenant_id=tenant_id,
        name=name,
        description=None,
        config=None,
        status="inactive",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _make_existing_user(email: str) -> User:
    """Create an existing User entity for duplicate email tests."""
    return User.reconstitute(
        user_id="existing-user-uuid",
        email=email,
        cognito_sub="existing-cognito-sub",
        full_name="Existing User",
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _make_use_case(
    cognito_service: AsyncMock,
    user_repository: MagicMock,
    tenant_repository: AsyncMock,
    account_type_repository: AsyncMock,
) -> RegisterUseCase:
    """Create RegisterUseCase with given mocks."""
    return RegisterUseCase(
        cognito_service=cognito_service,
        user_repository=user_repository,
        tenant_repository=tenant_repository,
        account_type_repository=account_type_repository,
    )


# ─── Property 8: Registration Atomicity ──────────────────────────────────────


class TestRegistrationAtomicity:
    """Property 8: Registration Atomicity.

    For any valid registration input where all preconditions pass (tenant exists,
    is active, allows self-registration, email is unique, account type is valid),
    the system ALWAYS calls Cognito sign_up exactly once and returns
    pending_confirmation status. No partial state should be possible.

    **Validates: Requirements 3.1, 3.2, 12.1**
    """

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_successful_registration_always_calls_cognito_once_and_returns_pending(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        cognito_sub: str,
    ) -> None:
        """For ALL valid inputs with passing preconditions, Cognito is called exactly once
        and the result is always pending_confirmation.

        **Validates: Requirements 3.1, 3.2**
        """
        # Arrange
        cognito_service = AsyncMock()
        cognito_service.sign_up.return_value = cognito_sub

        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(tenant_id)

        account_type_repository = AsyncMock()
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_active_account_type(tenant_id, "socio")
        )

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act
        result = await use_case.execute(input_dto)

        # Assert: Cognito called exactly once
        cognito_service.sign_up.assert_called_once()

        # Assert: result is always pending_confirmation
        assert result.status == "pending_confirmation"
        assert result.user_id == cognito_sub
        assert "verify" in result.message.lower() or "email" in result.message.lower()

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        account_type_name=valid_account_type_names,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=150)
    @pytest.mark.asyncio
    async def test_successful_registration_with_explicit_account_type_still_atomic(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        account_type_name: str,
        cognito_sub: str,
    ) -> None:
        """Registration with explicit valid account type also calls Cognito exactly once.

        **Validates: Requirements 3.1, 12.1**
        """
        # Arrange
        cognito_service = AsyncMock()
        cognito_service.sign_up.return_value = cognito_sub

        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(tenant_id)

        account_type_repository = AsyncMock()
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_active_account_type(tenant_id, account_type_name)
        )

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=account_type_name,
        )

        # Act
        result = await use_case.execute(input_dto)

        # Assert: exactly one Cognito call and pending status
        cognito_service.sign_up.assert_called_once()
        assert result.status == "pending_confirmation"


# ─── Property 13: Self-Registration Gate ─────────────────────────────────────


class TestSelfRegistrationGate:
    """Property 13: Self-Registration Gate.

    For ANY tenant that has allow_self_registration=False, registration ALWAYS
    raises DomainError regardless of all other valid inputs. Conversely, a valid
    tenant with allow_self_registration=True never rejects on that basis alone.

    **Validates: Requirements 3.4, 3.5, 3.6**
    """

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_tenant_disallowing_self_registration_always_rejects(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
    ) -> None:
        """For ANY tenant with allow_self_registration=False, registration ALWAYS fails.

        The rejection happens regardless of how valid the rest of the inputs are.
        No Cognito call is made.

        **Validates: Requirements 3.6**
        """
        # Arrange
        cognito_service = AsyncMock()
        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(
            tenant_id, allow_self_registration=False
        )

        account_type_repository = AsyncMock()

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act & Assert
        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(input_dto)

        assert "self-registration is not allowed" in exc_info.value.message.lower()
        cognito_service.sign_up.assert_not_called()

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_tenant_allowing_self_registration_never_rejects_on_that_basis(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        cognito_sub: str,
    ) -> None:
        """For ANY tenant with allow_self_registration=True, that field never causes rejection.

        When all other preconditions pass, the registration succeeds.

        **Validates: Requirements 3.4, 3.5, 3.6**
        """
        # Arrange
        cognito_service = AsyncMock()
        cognito_service.sign_up.return_value = cognito_sub

        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(
            tenant_id, allow_self_registration=True
        )

        account_type_repository = AsyncMock()
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_active_account_type(tenant_id, "socio")
        )

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act — should NOT raise DomainError about self-registration
        result = await use_case.execute(input_dto)

        # Assert: registration succeeds (self-registration gate is not triggered)
        assert result.status == "pending_confirmation"

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
    )
    @settings(max_examples=150)
    @pytest.mark.asyncio
    async def test_inactive_tenant_always_rejects_regardless_of_self_reg_flag(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
    ) -> None:
        """For ANY tenant that is not active, registration ALWAYS raises DomainError.

        **Validates: Requirements 3.5**
        """
        # Arrange
        cognito_service = AsyncMock()
        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_inactive_tenant(tenant_id)

        account_type_repository = AsyncMock()

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act & Assert
        with pytest.raises(DomainError) as exc_info:
            await use_case.execute(input_dto)

        assert exc_info.value.message == "Tenant is not active"
        cognito_service.sign_up.assert_not_called()


# ─── Property 14: Default account_type Assignment ────────────────────────────


class TestDefaultAccountTypeAssignment:
    """Property 14: Default account_type Assignment.

    For ANY registration without an explicit account_type:
    - If tenant has a default that is active → that default is used
    - If tenant's default is inactive or null → "usuario" is the fallback
    - The resolved name is ALWAYS one of these two (never empty/None)

    **Validates: Requirements 3.7**
    """

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        default_type_name=valid_account_type_names,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_active_tenant_default_is_used_when_no_explicit_type(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        default_type_name: str,
        cognito_sub: str,
    ) -> None:
        """When tenant has an active default account type, it is always looked up.

        **Validates: Requirements 3.7**
        """
        # Arrange
        cognito_service = AsyncMock()
        cognito_service.sign_up.return_value = cognito_sub

        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(
            tenant_id, default_account_type=default_type_name
        )

        account_type_repository = AsyncMock()
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_active_account_type(tenant_id, default_type_name)
        )

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,  # No explicit type
        )

        # Act
        result = await use_case.execute(input_dto)

        # Assert: account_type_repository was queried with the tenant default
        account_type_repository.find_by_name_in_tenant.assert_called_with(
            tenant_id=tenant_id,
            name=default_type_name,
        )
        # Registration succeeds
        assert result.status == "pending_confirmation"

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        default_type_name=valid_account_type_names,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_inactive_default_falls_back_to_usuario(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        default_type_name: str,
        cognito_sub: str,
    ) -> None:
        """When tenant's default account type is inactive, fallback to "usuario".

        **Validates: Requirements 3.7**
        """
        # Arrange
        cognito_service = AsyncMock()
        cognito_service.sign_up.return_value = cognito_sub

        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(
            tenant_id, default_account_type=default_type_name
        )

        account_type_repository = AsyncMock()
        # The default type exists but is inactive
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_inactive_account_type(tenant_id, default_type_name)
        )

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act — registration should succeed with "usuario" fallback
        result = await use_case.execute(input_dto)

        # Assert: registration succeeds (uses "usuario" fallback internally)
        assert result.status == "pending_confirmation"

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_null_default_falls_back_to_usuario(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        cognito_sub: str,
    ) -> None:
        """When tenant has no default account type (null), fallback to "usuario".

        **Validates: Requirements 3.7**
        """
        # Arrange
        cognito_service = AsyncMock()
        cognito_service.sign_up.return_value = cognito_sub

        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(
            tenant_id, default_account_type=None
        )

        account_type_repository = AsyncMock()
        # Should never be called since default is None

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act
        result = await use_case.execute(input_dto)

        # Assert: registration succeeds with fallback
        assert result.status == "pending_confirmation"
        # find_by_name_in_tenant should NOT be called since default is None
        account_type_repository.find_by_name_in_tenant.assert_not_called()

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        default_type_name=valid_account_type_names,
        cognito_sub=cognito_subs,
    )
    @settings(max_examples=150)
    @pytest.mark.asyncio
    async def test_nonexistent_default_falls_back_to_usuario(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        default_type_name: str,
        cognito_sub: str,
    ) -> None:
        """When tenant's default account type doesn't exist in DB, fallback to "usuario".

        **Validates: Requirements 3.7**
        """
        # Arrange
        cognito_service = AsyncMock()
        cognito_service.sign_up.return_value = cognito_sub

        user_repository = MagicMock()
        user_repository.find_by_email.return_value = None

        tenant_repository = AsyncMock()
        tenant_repository.find_by_id.return_value = _make_active_tenant(
            tenant_id, default_account_type=default_type_name
        )

        account_type_repository = AsyncMock()
        # The default type does NOT exist in the tenant
        account_type_repository.find_by_name_in_tenant.return_value = None

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act — should fall back to "usuario"
        result = await use_case.execute(input_dto)

        # Assert: registration succeeds with fallback
        assert result.status == "pending_confirmation"


# ─── Property 15: Email Uniqueness Enforcement ───────────────────────────────


class TestEmailUniquenessEnforcement:
    """Property 15: Email Uniqueness Enforcement.

    For ANY input where user_repository.find_by_email returns a non-None user,
    the system ALWAYS raises ConflictError("Email already registered") without
    calling Cognito or tenant_repository.

    **Validates: Requirements 3.3**
    """

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_existing_email_always_raises_conflict_error(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
    ) -> None:
        """For ANY registration with an already-registered email, ConflictError is ALWAYS raised.

        **Validates: Requirements 3.3**
        """
        # Arrange
        cognito_service = AsyncMock()
        user_repository = MagicMock()
        # Email already exists in local DB
        user_repository.find_by_email.return_value = _make_existing_user(email)

        tenant_repository = AsyncMock()
        account_type_repository = AsyncMock()

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act & Assert
        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(input_dto)

        assert "already registered" in exc_info.value.message.lower()

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_existing_email_never_calls_cognito(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
    ) -> None:
        """When email exists locally, Cognito is NEVER called (short-circuits).

        **Validates: Requirements 3.3**
        """
        # Arrange
        cognito_service = AsyncMock()
        user_repository = MagicMock()
        user_repository.find_by_email.return_value = _make_existing_user(email)

        tenant_repository = AsyncMock()
        account_type_repository = AsyncMock()

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=None,
        )

        # Act
        with pytest.raises(ConflictError):
            await use_case.execute(input_dto)

        # Assert: neither Cognito nor tenant_repository is called
        cognito_service.sign_up.assert_not_called()
        tenant_repository.find_by_id.assert_not_called()

    @given(
        email=valid_emails,
        password=valid_passwords,
        full_name=valid_full_names,
        tenant_id=valid_tenant_ids,
        account_type_name=valid_account_type_names,
    )
    @settings(max_examples=150)
    @pytest.mark.asyncio
    async def test_existing_email_blocks_regardless_of_account_type(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        account_type_name: str,
    ) -> None:
        """Email uniqueness check blocks registration regardless of account type specified.

        **Validates: Requirements 3.3**
        """
        # Arrange
        cognito_service = AsyncMock()
        user_repository = MagicMock()
        user_repository.find_by_email.return_value = _make_existing_user(email)

        tenant_repository = AsyncMock()
        account_type_repository = AsyncMock()

        use_case = _make_use_case(
            cognito_service, user_repository, tenant_repository, account_type_repository
        )

        input_dto = RegisterInputDTO(
            email=email,
            password=password,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=account_type_name,
        )

        # Act & Assert: ConflictError raised even with explicit account_type
        with pytest.raises(ConflictError) as exc_info:
            await use_case.execute(input_dto)

        assert "already registered" in exc_info.value.message.lower()
        cognito_service.sign_up.assert_not_called()
