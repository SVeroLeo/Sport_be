"""Property-based tests for LoginUseCase credential error opacity.

**Validates: Requirements 1.2, 1.3, 1.5**

Property 2: Credential Error Opacity
- For any login attempt with invalid credentials (whether due to non-existent email,
  wrong password, or lack of active membership in the tenant resolved from the user's
  default_tenant_id), the System returns the same generic "Invalid credentials" error,
  making it impossible to distinguish between failure modes.

Note: login is tenant-agnostic — the caller supplies only email + password and the
active tenant is resolved from the user's default_tenant_id stored in DynamoDB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from api.auth.loginInputDto import LoginInputDTO
from api.auth.loginUseCase import LoginUseCase
from api.auth.tokenPair import TokenPair
from api.common.user.user import User
from api.common.errors.invalidCredentialsError import InvalidCredentialsError

# ─── Failure Scenario Enum ────────────────────────────────────────────────────


class FailureScenario(Enum):
    """The three distinct authentication failure paths that must be opaque."""

    COGNITO_AUTH_FAILS = "cognito_auth_fails"
    USER_NOT_FOUND_IN_DB = "user_not_found_in_db"
    NO_MEMBERSHIP_IN_TENANT = "no_membership_in_tenant"


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid email strings that will pass the Email value object validation
valid_emails = st.emails().filter(lambda e: len(e.strip()) <= 254)

# Valid passwords (8-72 chars to pass Password VO validation)
valid_passwords = st.text(min_size=8, max_size=72)

# Failure scenario strategy: one of the three failure paths
failure_scenarios = st.sampled_from(list(FailureScenario))


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_token_pair() -> TokenPair:
    """Create a dummy TokenPair for scenarios where Cognito succeeds."""
    return TokenPair(
        access_token="access-token-dummy",
        id_token="id-token-dummy",
        refresh_token="refresh-token-dummy",
        expires_in=3600,
    )


def _make_user() -> User:
    """Create a dummy User entity for scenarios where user lookup succeeds.

    The user has a default_tenant_id so the login flow resolves the active tenant
    from the profile and proceeds to the membership check (the tenant is never
    supplied by the caller).
    """
    return User.reconstitute(
        user_id="user-uuid-001",
        email="test@example.com",
        cognito_sub="cognito-sub-abc",
        full_name="Test User",
        status="active",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        default_tenant_id="550e8400-e29b-41d4-a716-446655440000",
    )


def _configure_mocks_for_scenario(
    scenario: FailureScenario,
    cognito_service: AsyncMock,
    user_repository: MagicMock,
    member_repository: MagicMock,
) -> None:
    """Configure mocks according to the failure scenario.

    Each scenario simulates a different point of failure in the login flow,
    all of which must result in the same opaque error.
    """
    if scenario == FailureScenario.COGNITO_AUTH_FAILS:
        # Cognito rejects credentials (bad email or password)
        cognito_service.initiate_auth.side_effect = InvalidCredentialsError(
            "NotAuthorizedException"
        )

    elif scenario == FailureScenario.USER_NOT_FOUND_IN_DB:
        # Cognito succeeds but user is not in local database
        cognito_service.initiate_auth.return_value = _make_token_pair()
        user_repository.find_by_email.return_value = None

    elif scenario == FailureScenario.NO_MEMBERSHIP_IN_TENANT:
        # Cognito succeeds, user found, tenant resolved from default_tenant_id,
        # but the user has no membership in that resolved tenant.
        cognito_service.initiate_auth.return_value = _make_token_pair()
        user_repository.find_by_email.return_value = _make_user()
        member_repository.find_by_user_in_tenant.return_value = None


# ─── Property Tests ───────────────────────────────────────────────────────────


class TestCredentialErrorOpacity:
    """Property 2: Credential Error Opacity.

    For ALL possible authentication failure scenarios, the error raised is ALWAYS
    InvalidCredentialsError with message exactly "Invalid credentials". No additional
    information leaks about which step failed.
    """

    @given(
        scenario=failure_scenarios,
        email=valid_emails,
        password=valid_passwords,
    )
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_all_failure_paths_produce_identical_error(
        self,
        scenario: FailureScenario,
        email: str,
        password: str,
    ) -> None:
        """Regardless of which step fails, the error is always the same generic message.

        This prevents attackers from enumerating valid emails or determining
        membership status based on error response differences.

        **Validates: Requirements 1.2, 1.3, 1.5**
        """
        # Arrange: fresh mocks for each generated example
        cognito_service = AsyncMock()
        user_repository = MagicMock()
        member_repository = MagicMock()

        _configure_mocks_for_scenario(
            scenario, cognito_service, user_repository, member_repository
        )

        use_case = LoginUseCase(
            cognito_service=cognito_service,
            user_repository=user_repository,
            member_repository=member_repository,
        )

        input_dto = LoginInputDTO(
            email=email,
            password=password,
        )

        # Act & Assert
        with pytest.raises(InvalidCredentialsError) as exc_info:
            await use_case.execute(input_dto)

        # The error message MUST be exactly "Invalid credentials" — no variation
        assert exc_info.value.message == "Invalid credentials"

    @given(
        scenario_a=failure_scenarios,
        scenario_b=failure_scenarios,
        email=valid_emails,
        password=valid_passwords,
    )
    @settings(max_examples=150)
    @pytest.mark.asyncio
    async def test_different_failure_paths_are_indistinguishable(
        self,
        scenario_a: FailureScenario,
        scenario_b: FailureScenario,
        email: str,
        password: str,
    ) -> None:
        """Any two failure scenarios produce errors that cannot be distinguished.

        An attacker observing the response should not be able to tell whether
        the failure was due to Cognito rejection, user not found, or missing
        membership.

        **Validates: Requirements 1.3, 1.5**
        """
        input_dto = LoginInputDTO(
            email=email,
            password=password,
        )

        errors: list[InvalidCredentialsError] = []

        for scenario in (scenario_a, scenario_b):
            cognito_service = AsyncMock()
            user_repository = MagicMock()
            member_repository = MagicMock()

            _configure_mocks_for_scenario(
                scenario, cognito_service, user_repository, member_repository
            )

            use_case = LoginUseCase(
                cognito_service=cognito_service,
                user_repository=user_repository,
                member_repository=member_repository,
            )

            with pytest.raises(InvalidCredentialsError) as exc_info:
                await use_case.execute(input_dto)

            errors.append(exc_info.value)

        # Both errors must be identical in type and message
        assert type(errors[0]) is type(errors[1])
        assert errors[0].message == errors[1].message
        assert errors[0].message == "Invalid credentials"
