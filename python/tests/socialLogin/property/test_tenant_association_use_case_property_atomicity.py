"""Property-based test for TenantAssociationUseCase atomicity.

**Validates: Requirements 5.3**

Property tested:
- Feature: social-login, Property 9: Tenant association atomicity

This file is intentionally dedicated to Property 9 only, keeping it isolated
from the sibling social-login property tests and example-based unit tests so
the tasks can be implemented independently.

Interpretation note (single ``transact_write_items`` call):
    The atomic, single-``transact_write_items`` write of all three records
    (``TenantMembership``, ``Member``, ``UserRole``) is *encapsulated* inside
    ``IUserRepository.associate_tenant``. Because the repository is mocked at
    the use-case level, this property asserts the use-case invariant that makes
    that atomicity possible: ``associate_tenant`` is invoked exactly once, with
    all three records passed together and ``new_status == "active"``. The literal
    ``transact_write_items`` call (three items, one transaction) is verified at
    the repository layer (tasks 6.3 / 6.4). Together these guarantee that a
    successful ``execute()`` results in all three records being written in a
    single transaction with no partial write ever observable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from api.socialLogin.tenantAssociationUseCase import TenantAssociationUseCase
from api.member.member import Member
from api.common.tenant.tenant import Tenant
from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.users import User
from api.common.user.userRole import UserRole
from api.common.tenant.tenantId import TenantId

# ─── Constants ───────────────────────────────────────────────────────────────

FIXED_CREATED_AT = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
FIXED_UPDATED_AT = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

ACCOUNT_TYPE_ID = "880e8400-e29b-41d4-a716-446655440003"
ACCOUNT_TYPE_NAME = "usuario"


# ─── Strategies ──────────────────────────────────────────────────────────────

# Both user_id and tenant_id must be valid UUID strings: the use case builds a
# ``Member`` whose ``tenant_id`` is validated through ``TenantId.create`` (UUID
# format), so arbitrary junk strings would be rejected by the domain layer
# before the atomicity property could be exercised. Generating full UUIDs keeps
# the generator inside the meaningful input space (smart generation).
uuid_strings = st.builds(lambda: str(uuid.uuid4()))


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_pending_user(user_id: str) -> User:
    """Build a pending-tenant social ``User`` for the given user_id."""
    return User.reconstitute(
        user_id=user_id,
        email="social.user@example.com",
        cognito_sub="cognito-sub-social-12345",
        full_name="Social User",
        status="pending_tenant",
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
        default_tenant_id=None,
        registration_type="social",
    )


def _make_active_tenant(tenant_id: str) -> Tenant:
    """Build a valid, active ``Tenant`` for the given tenant_id."""
    return Tenant.create(
        tenant_id=TenantId(tenant_id),
        name="Test Tenant",
        status="active",
        default_account_type=None,
        created_at=FIXED_CREATED_AT,
    )


def _make_active_account_type() -> MagicMock:
    """Build a stand-in active account type with the attributes the use case reads."""
    account_type = MagicMock()
    account_type.name = ACCOUNT_TYPE_NAME
    account_type.account_type_id = ACCOUNT_TYPE_ID
    account_type.is_active = True
    return account_type


# ─── Property 9: Tenant association atomicity ────────────────────────────────


class TestTenantAssociationAtomicity:
    """Feature: social-login, Property 9: Tenant association atomicity.

    For ANY pending-tenant social ``User`` and ANY valid active ``Tenant``, a
    successful ``TenantAssociationUseCase.execute()`` results in all three
    records (``TenantMembership``, ``Member``, ``UserRole``) being handed to a
    single ``associate_tenant`` write together, and the user transitioning to
    ``"active"``. See the module docstring for the ``transact_write_items``
    interpretation.

    **Validates: Requirements 5.3**
    """

    @given(user_id=uuid_strings, tenant_id=uuid_strings)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_associate_tenant_writes_all_three_records_atomically(
        self,
        user_id: str,
        tenant_id: str,
    ) -> None:
        """All three records go to a single ``associate_tenant`` call and the
        user transitions to ``"active"``.

        **Validates: Requirements 5.3**
        """
        # Arrange — user_repository methods are sync (MagicMock); tenant and
        # account_type repositories are async (AsyncMock).
        user_repository = MagicMock()
        tenant_repository = AsyncMock()
        member_repository = MagicMock()
        account_type_repository = AsyncMock()

        user_repository.find_by_id.return_value = _make_pending_user(user_id)
        tenant_repository.find_by_id.return_value = _make_active_tenant(tenant_id)
        member_repository.find_by_user_in_tenant.return_value = None
        account_type_repository.find_by_name_in_tenant.return_value = (
            _make_active_account_type()
        )

        use_case = TenantAssociationUseCase(
            user_repository=user_repository,
            tenant_repository=tenant_repository,
            member_repository=member_repository,
            account_type_repository=account_type_repository,
        )

        # Act
        result = await use_case.execute(user_id=user_id, tenant_id=tenant_id)

        # Assert — a single atomic write with all three records together.
        user_repository.associate_tenant.assert_called_once()
        _, kwargs = user_repository.associate_tenant.call_args

        membership = kwargs["membership"]
        member = kwargs["member"]
        role = kwargs["role"]

        assert isinstance(membership, TenantMembership)
        assert isinstance(member, Member)
        assert isinstance(role, UserRole)

        # All three records target the same user + tenant.
        assert membership.user_id == user_id
        assert membership.tenant_id == tenant_id
        assert member.user_id == user_id
        assert member.tenant_id == tenant_id
        assert role.user_id == user_id
        assert role.tenant_id == tenant_id

        # The atomic write transitions the user to "active" and sets the
        # chosen tenant as the new default.
        assert kwargs["new_status"] == "active"
        assert kwargs["new_default_tenant_id"] == tenant_id

        # The returned DTO reflects the "active" transition.
        assert result.status == "active"
        assert result.user_id == user_id
        assert result.default_tenant_id == tenant_id
