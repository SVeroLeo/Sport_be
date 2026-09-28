"""Property-based test for SocialCallbackUseCase pending-tenant flag mapping.

**Validates: Requirements 5.1, 7.4**

Property tested:
- Feature: social-login, Property 7: Pending-tenant flag matches user status

This file is intentionally dedicated to Property 7 only, keeping it isolated
from the sibling social-login property tests and example-based unit tests so
the tasks can be implemented independently.

Interpretation note (``build_callback_response`` vs ``_finalize``):
    The design's Property 7 references a ``build_callback_response(user,
    token_pair)`` function. The actual implementation has no such standalone
    function — the callback response is built by
    ``SocialCallbackUseCase._finalize(user, token_pair, provider, outcome,
    start)``, which sets
    ``requires_tenant_selection = (user.status == "pending_tenant")`` on the
    returned :class:`SocialLoginOutputDTO`. This test therefore exercises the
    real response-building behavior via ``_finalize``. ``_finalize`` is
    synchronous (it only emits structured logs/metrics via the module logger,
    which is harmless in a test), so no async harness is needed. The repository/
    Cognito/tenant collaborators are mocked because ``_finalize`` never touches
    them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
from hypothesis import given, settings

from api.socialLogin.socialCallbackUseCase import SocialCallbackUseCase
from api.auth.tokenPair import TokenPair
from api.common.user.user import User

# ─── Constants ───────────────────────────────────────────────────────────────

FIXED_CREATED_AT = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
FIXED_UPDATED_AT = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# The full set of UserStatus Literal values from domain.entities.user.UserStatus.
ALL_USER_STATUSES = [
    "active",
    "inactive",
    "suspended",
    "pending_confirmation",
    "pending_tenant",
]

PENDING_TENANT_STATUS = "pending_tenant"


# ─── Strategies ──────────────────────────────────────────────────────────────

# Draw status from every UserStatus value so the iff relationship is exercised
# for both the pending-tenant case and every non-pending case.
user_statuses = st.sampled_from(ALL_USER_STATUSES)

# Token strings are opaque to _finalize (it just copies them onto the DTO), so
# any non-empty text is a meaningful input.
token_strings = st.text(min_size=1, max_size=64)

expires_in_values = st.integers(min_value=1, max_value=86_400)

# Provider/outcome only feed logs + metrics inside _finalize; keep them to the
# values the real flow uses so the generated inputs stay realistic.
providers = st.sampled_from(["google", "facebook"])
outcomes = st.sampled_from(["existing_user", "linked_user", "new_user"])


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_use_case() -> SocialCallbackUseCase:
    """Build a use case with mocked collaborators.

    ``_finalize`` never touches the repositories or Cognito service, so plain
    mocks suffice. Async collaborators use ``AsyncMock`` to match their real
    interfaces even though they are not exercised here.
    """
    return SocialCallbackUseCase(
        user_repository=MagicMock(),
        cognito_service=AsyncMock(),
        tenant_repository=AsyncMock(),
        redirect_uri="https://example.com/callback",
        hosted_ui_domain="auth.example.com",
        state_secret="test-secret",
    )


def _make_user(status: str) -> User:
    """Build a ``User`` with the given status via ``reconstitute``."""
    return User.reconstitute(
        user_id=str(uuid.uuid4()),
        email="social.user@example.com",
        cognito_sub="cognito-sub-12345",
        full_name="Social User",
        status=status,
        created_at=FIXED_CREATED_AT,
        updated_at=FIXED_UPDATED_AT,
        default_tenant_id=None,
        registration_type="social",
    )


# ─── Property 7: Pending-tenant flag matches user status ─────────────────────


class TestPendingTenantFlagMatchesStatus:
    """Feature: social-login, Property 7: Pending-tenant flag matches user status.

    For ANY ``User`` whose status is drawn from the full set of ``UserStatus``
    values, the callback response's ``requires_tenant_selection`` flag is
    ``True`` if and only if ``user.status == "pending_tenant"``.

    **Validates: Requirements 5.1, 7.4**
    """

    @given(
        status=user_statuses,
        access_token=token_strings,
        id_token=token_strings,
        refresh_token=token_strings,
        expires_in=expires_in_values,
        provider=providers,
        outcome=outcomes,
    )
    @settings(max_examples=100)
    def test_requires_tenant_selection_iff_pending_tenant(
        self,
        status: str,
        access_token: str,
        id_token: str,
        refresh_token: str,
        expires_in: int,
        provider: str,
        outcome: str,
    ) -> None:
        """``requires_tenant_selection`` is True iff status is pending_tenant.

        **Validates: Requirements 5.1, 7.4**
        """
        # Arrange
        use_case = _make_use_case()
        user = _make_user(status)
        token_pair = TokenPair(
            access_token=access_token,
            id_token=id_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

        # Act — _finalize is the real response builder (see module docstring).
        result = use_case._finalize(
            user=user,
            token_pair=token_pair,
            provider=provider,
            outcome=outcome,
            start=0.0,
        )

        # Assert — the iff relationship holds for every status value.
        assert result.requires_tenant_selection is (status == PENDING_TENANT_STATUS)

        # Sanity: the token set is copied through unchanged, confirming we are
        # exercising the real response-building path.
        assert result.access_token == access_token
        assert result.id_token == id_token
        assert result.refresh_token == refresh_token
        assert result.expires_in == expires_in
        assert result.user_id == user.user_id
