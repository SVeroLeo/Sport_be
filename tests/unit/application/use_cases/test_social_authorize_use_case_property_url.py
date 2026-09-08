"""Property-based tests for SocialAuthorizeUseCase authorization URL contents.

Feature: social-login, Property 4: Authorization URL contains all required OAuth parameters

**Validates: Requirements 2.2**

Property 4: Authorization URL contains all required OAuth parameters
- For any valid provider ("google" or "facebook"), the authorization URL
  returned by SocialAuthorizeUseCase.execute contains the query parameters
  ``response_type``, ``client_id``, ``redirect_uri``, ``scope``,
  ``identity_provider`` and ``state``, each present and non-empty.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import hypothesis.strategies as st
from hypothesis import given, settings

from application.use_cases.social_authorize_use_case import SocialAuthorizeUseCase

# ─── Strategies ───────────────────────────────────────────────────────────────

# Requirement 2.1 restricts valid providers to exactly these two values.
providers = st.sampled_from(["google", "facebook"])

# The required OAuth query parameters that must be present and non-empty (Req 2.2, 2.4).
_REQUIRED_PARAMS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "scope",
    "identity_provider",
    "state",
)


def _make_use_case() -> SocialAuthorizeUseCase:
    """Build a use case with representative, non-empty Cognito configuration."""
    return SocialAuthorizeUseCase(
        client_id="test-client-id",
        redirect_uri="https://api.example.com/auth/social/callback",
        hosted_ui_domain="auth.example.com",
        state_secret="test-state-secret",
    )


# ─── Property 4 ───────────────────────────────────────────────────────────────


@settings(max_examples=100)
@given(provider=providers)
def test_authorization_url_contains_all_required_oauth_parameters(provider: str) -> None:
    """The authorization URL exposes every required OAuth parameter, non-empty.

    Feature: social-login, Property 4: Authorization URL contains all required
    OAuth parameters. Validates Requirement 2.2.
    """
    use_case = _make_use_case()

    result = use_case.execute(provider)

    parsed = urlparse(result.authorization_url)
    # keep_blank_values=True so a present-but-empty value is not silently dropped,
    # letting the non-empty assertion below actually detect it.
    query = parse_qs(parsed.query, keep_blank_values=True)

    for param in _REQUIRED_PARAMS:
        assert param in query, f"missing OAuth parameter: {param}"
        values = query[param]
        assert values, f"no value for OAuth parameter: {param}"
        assert all(value != "" for value in values), f"empty OAuth parameter: {param}"
