"""Property-based test for SocialAuthorizeUseCase provider validation.

**Validates: Requirements 2.1, 2.3**

Property tested:
- Feature: social-login, Property 3: Provider parameter validation

This file is intentionally dedicated to Property 3 only, keeping it isolated
from the sibling property tests (Property 4 authorization-URL parameters) and
the example-based unit tests so the tasks can be implemented independently.
"""

from __future__ import annotations

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from application.use_cases.social_authorize_use_case import SocialAuthorizeUseCase
from domain.errors.validation_error import ValidationError

# ─── Constants ───────────────────────────────────────────────────────────────

# The only two provider values the use case accepts.
_VALID_PROVIDERS = frozenset({"google", "facebook"})

# Fixed, representative Cognito configuration for the use case under test. The
# concrete values are irrelevant to Property 3 — every invalid provider must be
# rejected before any URL is built, regardless of configuration.
_CLIENT_ID = "test-client-id"
_REDIRECT_URI = "https://api.example.com/auth/social/callback"
_HOSTED_UI_DOMAIN = "sport-test.auth.us-east-1.amazoncognito.com"
_STATE_SECRET = "test-social-state-secret-value"


# ─── Strategies ──────────────────────────────────────────────────────────────

# Arbitrary text, then filter out the two accepted providers. This naturally
# covers the empty string, whitespace-only strings, mixed case ("Google"),
# and arbitrary random unicode — every value that is NOT exactly a valid
# provider must be rejected.
_invalid_providers = st.text().filter(lambda s: s not in _VALID_PROVIDERS)


def _make_use_case() -> SocialAuthorizeUseCase:
    """Build a use case instance with fixed test configuration."""
    return SocialAuthorizeUseCase(
        client_id=_CLIENT_ID,
        redirect_uri=_REDIRECT_URI,
        hosted_ui_domain=_HOSTED_UI_DOMAIN,
        state_secret=_STATE_SECRET,
    )


# ─── Property 3: Provider parameter validation ───────────────────────────────


class TestProviderParameterValidation:
    """Feature: social-login, Property 3: Provider parameter validation.

    For ANY string that is not ``"google"`` or ``"facebook"`` (including the
    empty string, whitespace-only, mixed case, and arbitrary random text),
    ``SocialAuthorizeUseCase.execute`` ALWAYS raises ``ValidationError`` and
    never constructs an authorization URL.

    **Validates: Requirements 2.1, 2.3**
    """

    @given(provider=_invalid_providers)
    @settings(max_examples=200)
    def test_invalid_provider_raises_validation_error(self, provider: str) -> None:
        """Every non-valid provider string raises ``ValidationError``.

        **Validates: Requirements 2.1, 2.3**
        """
        use_case = _make_use_case()

        with pytest.raises(ValidationError):
            use_case.execute(provider=provider)
