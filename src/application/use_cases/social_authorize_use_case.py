"""SocialAuthorizeUseCase — builds the Cognito Hosted UI authorization URL.

This use case backs the ``GET /auth/social/authorize`` endpoint. It validates
the requested social provider, generates a CSRF state token, and constructs the
Cognito Hosted UI authorization URL the frontend redirects the browser to in
order to begin the OAuth Authorization Code flow.

Requirements satisfied: 2.1, 2.2, 2.3, 2.4, 2.5
"""

from __future__ import annotations

from urllib.parse import urlencode

from application.dtos.social_login_dtos import SocialAuthorizeOutputDTO
from application.services import state_token
from domain.errors.validation_error import ValidationError

# Error code raised when the provider parameter is missing or unsupported.
_INVALID_PROVIDER = "invalid_provider"

# OAuth scopes requested from the Cognito Hosted UI.
_OAUTH_SCOPE = "openid email profile"

# Maps the public provider query value to the Cognito identity provider name.
_IDENTITY_PROVIDER_BY_PROVIDER = {
    "google": "Google",
    "facebook": "Facebook",
}


class SocialAuthorizeUseCase:
    """Application use case for starting the social login OAuth flow.

    Orchestrates:
    1. Validate ``provider`` is ``"google"`` or ``"facebook"``.
    2. Generate a signed state token for CSRF protection.
    3. Build the Cognito Hosted UI authorization URL with the required OAuth
       query parameters (``response_type``, ``client_id``, ``redirect_uri``,
       ``scope``, ``identity_provider``, ``state``).
    4. Return the URL wrapped in a :class:`SocialAuthorizeOutputDTO`.

    The Cognito configuration (client id, redirect uri, hosted UI domain) and
    the HMAC signing secret are injected via the constructor so the use case
    stays free of environment/config coupling.

    Requirements satisfied: 2.1, 2.2, 2.3, 2.4, 2.5
    """

    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        hosted_ui_domain: str,
        state_secret: str,
    ) -> None:
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._hosted_ui_domain = hosted_ui_domain
        self._state_secret = state_secret

    def execute(self, provider: str) -> SocialAuthorizeOutputDTO:
        """Build the authorization URL for the requested provider.

        Args:
            provider: The social provider to authorize with. Must be
                ``"google"`` or ``"facebook"``.

        Returns:
            A :class:`SocialAuthorizeOutputDTO` wrapping the Cognito Hosted UI
            authorization URL.

        Raises:
            ValidationError: With code ``"invalid_provider"`` when ``provider``
                is missing or not a supported value.
        """
        # 1. Validate the provider (Req 2.1, 2.3).
        identity_provider = _IDENTITY_PROVIDER_BY_PROVIDER.get(provider)
        if identity_provider is None:
            raise ValidationError(_INVALID_PROVIDER)

        # 2. Generate a signed, timestamped state token for CSRF protection (Req 2.4).
        state = state_token.generate_state(self._state_secret)

        # 3. Build the Cognito Hosted UI authorization URL (Req 2.2).
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "scope": _OAUTH_SCOPE,
                "identity_provider": identity_provider,
                "state": state,
            }
        )
        authorization_url = f"https://{self._hosted_ui_domain}/oauth2/authorize?{query}"

        # 4. Return the URL for the frontend to redirect to (Req 2.5).
        return SocialAuthorizeOutputDTO(authorization_url=authorization_url)
