"""Environment configuration — reads settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_list(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated environment value into a tuple of trimmed items.

    Empty entries are dropped. Returns an empty tuple for blank input.

    Args:
        raw: The raw environment variable value (comma-separated).

    Returns:
        A tuple of non-empty, trimmed string items.
    """
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _issuer_for_pool(region: str, user_pool_id: str) -> str:
    """Build the Cognito issuer URL for a given region and User Pool.

    Args:
        region: AWS region of the User Pool.
        user_pool_id: The Cognito User Pool ID.

    Returns:
        The issuer URL: https://cognito-idp.{region}.amazonaws.com/{user_pool_id}
    """
    return f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    """Immutable environment configuration loaded from environment variables.

    The legacy symmetric ``JWT_SECRET`` is intentionally absent: token
    verification uses RS256/JWKS against the pool identified by the token's
    ``iss`` claim, driven by the ``cognito_issuers``/``cognito_client_ids``
    allow-lists below.

    Attributes:
        table_name: DynamoDB table name.
        region: AWS region for DynamoDB and other services.
        cognito_user_pool_id: AWS Cognito User Pool ID for the region-local pool
            used by the CognitoAuthService admin operations (sign-up, admin
            create user, initiate auth). Not used for token verification.
        cognito_client_id: AWS Cognito App Client ID for the region-local client
            used by the CognitoAuthService. Not used for token verification.
        cognito_issuers: Allow-list of accepted token issuer URLs (one Cognito
            User Pool per region). Access tokens are verified with RS256 against
            the JWKS of the pool identified by the token's ``iss`` claim.
        cognito_client_ids: Allow-list of accepted Cognito App Client IDs.
    """

    table_name: str
    region: str
    cognito_user_pool_id: str
    cognito_client_id: str
    cognito_issuers: tuple[str, ...]
    cognito_client_ids: tuple[str, ...]

    @staticmethod
    def load() -> EnvironmentConfig:
        """Load configuration from environment variables.

        Multi-region RS256 verification is driven by two allow-lists:
        - ``COGNITO_ISSUERS``: comma-separated issuer URLs, one User Pool per region.
        - ``COGNITO_CLIENT_IDS``: comma-separated allowed app client ids.

        For backward compatibility with single-region setups, when the list
        variables are absent the values are derived from the singular
        ``COGNITO_USER_POOL_ID`` / ``REGION`` / ``COGNITO_CLIENT_ID`` variables.

        Returns:
            An EnvironmentConfig instance with values from the environment.

        Raises:
            EnvironmentError: If a required environment variable is missing.
        """
        table_name = os.environ.get("TABLE_NAME", "")
        region = os.environ.get("REGION", "us-east-1")
        cognito_user_pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
        cognito_client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        # Token verification allow-lists are the source of truth (RS256/JWKS,
        # multi-region). Each entry in COGNITO_ISSUERS is one User Pool per region.
        cognito_issuers = _parse_list(os.environ.get("COGNITO_ISSUERS", ""))
        cognito_client_ids = _parse_list(os.environ.get("COGNITO_CLIENT_IDS", ""))

        # Backward-compat: derive the allow-lists from the singular single-region
        # variables when the multi-region allow-lists are not provided.
        if not cognito_issuers and cognito_user_pool_id:
            cognito_issuers = (_issuer_for_pool(region, cognito_user_pool_id),)

        if not cognito_client_ids and cognito_client_id:
            cognito_client_ids = (cognito_client_id,)

        if not table_name:
            raise EnvironmentError("TABLE_NAME environment variable is required")

        if not cognito_issuers:
            raise EnvironmentError(
                "No Cognito issuers configured: set COGNITO_ISSUERS "
                "(or COGNITO_USER_POOL_ID + REGION for single-region)"
            )

        if not cognito_client_ids:
            raise EnvironmentError(
                "No Cognito client ids configured: set COGNITO_CLIENT_IDS "
                "(or COGNITO_CLIENT_ID for single-region)"
            )

        return EnvironmentConfig(
            table_name=table_name,
            region=region,
            cognito_user_pool_id=cognito_user_pool_id,
            cognito_client_id=cognito_client_id,
            cognito_issuers=cognito_issuers,
            cognito_client_ids=cognito_client_ids,
        )


# Module-level singleton — created once on cold start, reused on warm invocations.
_config: EnvironmentConfig | None = None


def get_environment_config() -> EnvironmentConfig:
    """Get the singleton environment configuration.

    Loads from environment variables on first call (Lambda cold start),
    returns cached instance on subsequent calls (warm invocations).

    Returns:
        The EnvironmentConfig singleton instance.
    """
    global _config  # noqa: PLW0603
    if _config is None:
        _config = EnvironmentConfig.load()
    return _config
