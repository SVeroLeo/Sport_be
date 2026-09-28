"""Unit tests for SocialAuthorizeUseCase.

Example-based tests covering the authorize endpoint use case:

* A valid Cognito Hosted UI authorization URL is returned for the supported
  providers ``"google"`` and ``"facebook"`` (Req 2.1, 2.2).
* A ``ValidationError`` with code ``"invalid_provider"`` is raised for absent or
  unsupported provider values (Req 2.1, 2.3).

Property-based coverage lives in separate files (tasks 8.2/8.3); these are
standard pytest example tests.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from api.socialLogin.socialLoginDtos import SocialAuthorizeOutputDTO
from api.socialLogin.socialAuthorizeUseCase import SocialAuthorizeUseCase
from api.common.errors.validationError import ValidationError

# ──── Test configuration constants ────────────────────────────────────────────

_CLIENT_ID = "test-client-id-123"
_REDIRECT_URI = "https://api.test.sport-app.com/auth/social/callback"
_HOSTED_UI_DOMAIN = "auth.test.sport-app.com"
_STATE_SECRET = "test-state-secret"

# Maps the public provider query value to the expected Cognito identity provider.
_EXPECTED_IDENTITY_PROVIDER = {
    "google": "Google",
    "facebook": "Facebook",
}


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def use_case() -> SocialAuthorizeUseCase:
    """Create a SocialAuthorizeUseCase with test Cognito configuration."""
    return SocialAuthorizeUseCase(
        client_id=_CLIENT_ID,
        redirect_uri=_REDIRECT_URI,
        hosted_ui_domain=_HOSTED_UI_DOMAIN,
        state_secret=_STATE_SECRET,
    )


def _parse_query(authorization_url: str) -> dict[str, str]:
    """Return the query parameters of ``authorization_url`` as a flat dict."""
    parsed = urlparse(authorization_url)
    return {key: values[0] for key, values in parse_qs(parsed.query).items()}


# ──── Test: Valid providers ───────────────────────────────────────────────────


class TestValidProvider:
    """Tests for supported provider values (Req 2.1, 2.2)."""

    @pytest.mark.parametrize("provider", ["google", "facebook"])
    def test_returns_output_dto(
        self, use_case: SocialAuthorizeUseCase, provider: str
    ) -> None:
        """A valid provider yields a SocialAuthorizeOutputDTO with a URL."""
        result = use_case.execute(provider)

        assert isinstance(result, SocialAuthorizeOutputDTO)
        assert result.authorization_url

    @pytest.mark.parametrize("provider", ["google", "facebook"])
    def test_url_targets_hosted_ui_authorize_endpoint(
        self, use_case: SocialAuthorizeUseCase, provider: str
    ) -> None:
        """The URL points at the Cognito Hosted UI /oauth2/authorize endpoint."""
        result = use_case.execute(provider)

        parsed = urlparse(result.authorization_url)
        assert parsed.scheme == "https"
        assert parsed.netloc == _HOSTED_UI_DOMAIN
        assert parsed.path == "/oauth2/authorize"

    @pytest.mark.parametrize("provider", ["google", "facebook"])
    def test_url_maps_provider_to_identity_provider(
        self, use_case: SocialAuthorizeUseCase, provider: str
    ) -> None:
        """The identity_provider param maps google->Google, facebook->Facebook."""
        result = use_case.execute(provider)

        params = _parse_query(result.authorization_url)
        assert params["identity_provider"] == _EXPECTED_IDENTITY_PROVIDER[provider]

    @pytest.mark.parametrize("provider", ["google", "facebook"])
    def test_url_contains_required_oauth_params(
        self, use_case: SocialAuthorizeUseCase, provider: str
    ) -> None:
        """The URL carries all required OAuth query params (Req 2.2, 2.4)."""
        result = use_case.execute(provider)

        params = _parse_query(result.authorization_url)
        assert params["response_type"] == "code"
        assert params["client_id"] == _CLIENT_ID
        assert params["redirect_uri"] == _REDIRECT_URI
        assert params["scope"] == "openid email profile"
        assert params["identity_provider"] == _EXPECTED_IDENTITY_PROVIDER[provider]
        # A signed state token must be present for CSRF protection (Req 2.4).
        assert params["state"]

    def test_google_and_facebook_produce_different_identity_providers(
        self, use_case: SocialAuthorizeUseCase
    ) -> None:
        """Different providers yield distinct identity_provider values."""
        google_params = _parse_query(use_case.execute("google").authorization_url)
        facebook_params = _parse_query(use_case.execute("facebook").authorization_url)

        assert google_params["identity_provider"] == "Google"
        assert facebook_params["identity_provider"] == "Facebook"


# ──── Test: Invalid providers ─────────────────────────────────────────────────


class TestInvalidProvider:
    """Tests for absent or unsupported provider values (Req 2.1, 2.3)."""

    @pytest.mark.parametrize(
        "provider",
        [
            "",  # absent / empty
            "twitter",  # unsupported provider
            "GOOGLE",  # wrong case, not an exact match
            "Facebook",  # wrong case, not an exact match
            "google ",  # trailing whitespace
            "apple",  # unsupported provider
        ],
    )
    def test_invalid_provider_raises_validation_error(
        self, use_case: SocialAuthorizeUseCase, provider: str
    ) -> None:
        """An invalid provider raises ValidationError with code invalid_provider."""
        with pytest.raises(ValidationError) as exc_info:
            use_case.execute(provider)

        assert exc_info.value.message == "invalid_provider"
