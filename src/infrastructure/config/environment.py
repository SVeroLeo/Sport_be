"""Environment configuration — reads settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    """Immutable environment configuration loaded from environment variables.

    Attributes:
        table_name: DynamoDB table name.
        region: AWS region for DynamoDB and other services.
        jwt_secret: Secret used for JWT verification (from Cognito).
        token_expiry: Token expiry time in seconds.
        salt_rounds: Number of bcrypt salt rounds for password hashing.
        cognito_user_pool_id: AWS Cognito User Pool ID.
        cognito_client_id: AWS Cognito App Client ID.
    """

    table_name: str
    region: str
    jwt_secret: str
    token_expiry: int
    salt_rounds: int
    cognito_user_pool_id: str
    cognito_client_id: str

    @staticmethod
    def load() -> EnvironmentConfig:
        """Load configuration from environment variables.

        Returns:
            An EnvironmentConfig instance with values from the environment.

        Raises:
            EnvironmentError: If a required environment variable is missing.
        """
        table_name = os.environ.get("TABLE_NAME", "")
        region = os.environ.get("REGION", "us-east-1")
        jwt_secret = os.environ.get("JWT_SECRET", "")
        token_expiry_raw = os.environ.get("TOKEN_EXPIRY", "3600")
        salt_rounds_raw = os.environ.get("SALT_ROUNDS", "12")
        cognito_user_pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
        cognito_client_id = os.environ.get("COGNITO_CLIENT_ID", "")

        if not table_name:
            raise EnvironmentError("TABLE_NAME environment variable is required")

        if not jwt_secret:
            raise EnvironmentError("JWT_SECRET environment variable is required")

        if not cognito_user_pool_id:
            raise EnvironmentError("COGNITO_USER_POOL_ID environment variable is required")

        if not cognito_client_id:
            raise EnvironmentError("COGNITO_CLIENT_ID environment variable is required")

        try:
            token_expiry = int(token_expiry_raw)
        except ValueError:
            raise EnvironmentError(
                f"TOKEN_EXPIRY must be a valid integer, got: '{token_expiry_raw}'"
            )

        try:
            salt_rounds = int(salt_rounds_raw)
        except ValueError:
            raise EnvironmentError(
                f"SALT_ROUNDS must be a valid integer, got: '{salt_rounds_raw}'"
            )

        return EnvironmentConfig(
            table_name=table_name,
            region=region,
            jwt_secret=jwt_secret,
            token_expiry=token_expiry,
            salt_rounds=salt_rounds,
            cognito_user_pool_id=cognito_user_pool_id,
            cognito_client_id=cognito_client_id,
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
