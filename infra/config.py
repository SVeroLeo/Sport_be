"""Per-environment configuration for the CDK app (dev and prod).

Single-region deployment in sa-east-1 (Sao Paulo). The multi-region concerns
(Route 53 failover, DynamoDB Global Tables, WAF, Cognito ASF) are tracked in the
`aws-multiregion-infrastructure` spec and are intentionally out of scope here.

Token verification in the backend is RS256/JWKS and tenant-agnostic: the Lambda
reads COGNITO_ISSUERS / COGNITO_CLIENT_IDS allow-lists (derived here from the
User Pool created per environment) and resolves tenant/roles from DynamoDB.
There is no symmetric JWT secret.
"""

from __future__ import annotations

from dataclasses import dataclass

# Single region for now (Brazil / Sao Paulo). See the multi-region spec for expansion.
REGION = "sa-east-1"


@dataclass(frozen=True)
class EnvConfig:
    """Immutable per-environment settings.

    Attributes:
        name: Environment name ("dev" or "prod").
        region: AWS region to deploy into.
        table_name: DynamoDB single-table name for this environment.
        removal_policy_destroy: Whether stateful resources are destroyed on stack
            deletion. True for dev (easy teardown), False for prod (retain data).
        point_in_time_recovery: Enable PITR on the table (recommended for prod).
        log_retention_days: CloudWatch log retention for the Lambdas.
        lambda_memory_mb: Memory size for the Lambda functions.
        lambda_timeout_seconds: Timeout for the Lambda functions.
        api_throttle_rate: API Gateway steady-state requests/sec (stage throttling).
        api_throttle_burst: API Gateway burst capacity.
        waf_rate_limit_per_5min: WAF rate-based rule limit (requests per source
            IP over a 5-minute window) before the IP is temporarily blocked.
        social_callback_urls: OAuth `callback_urls` registered on the Cognito
            App Client — the frontend/API destinations Cognito is allowed to
            redirect to after a social login. These are the URLs the Hosted UI
            redirects to with the authorization `code` (the app then forwards
            it to the `/auth/social/callback` endpoint). Config-driven per
            environment rather than hardcoded so dev/prod can differ.
        social_logout_urls: OAuth `logout_urls` registered on the Cognito App
            Client — the frontend destinations Cognito is allowed to redirect
            to after a Hosted UI sign-out. Config-driven per environment.
    """

    name: str
    region: str
    table_name: str
    removal_policy_destroy: bool
    point_in_time_recovery: bool
    log_retention_days: int
    lambda_memory_mb: int
    lambda_timeout_seconds: int
    api_throttle_rate: int
    api_throttle_burst: int
    waf_rate_limit_per_5min: int
    social_callback_urls: tuple[str, ...]
    social_logout_urls: tuple[str, ...]


_CONFIGS: dict[str, EnvConfig] = {
    "dev": EnvConfig(
        name="dev",
        region=REGION,
        table_name="sport-account-management-dev",
        removal_policy_destroy=True,
        point_in_time_recovery=False,
        log_retention_days=14,
        lambda_memory_mb=256,
        lambda_timeout_seconds=15,
        api_throttle_rate=20,
        api_throttle_burst=40,
        waf_rate_limit_per_5min=2000,
        social_callback_urls=(
            "https://dev.sport-app.com/auth/social/callback",
        ),
        social_logout_urls=(
            "https://dev.sport-app.com/logout",
        ),
    ),
    "prod": EnvConfig(
        name="prod",
        region=REGION,
        table_name="sport-account-management-prod",
        removal_policy_destroy=False,
        point_in_time_recovery=True,
        log_retention_days=90,
        lambda_memory_mb=512,
        lambda_timeout_seconds=30,
        api_throttle_rate=100,
        api_throttle_burst=200,
        waf_rate_limit_per_5min=10000,
        social_callback_urls=(
            "https://sport-app.com/auth/social/callback",
        ),
        social_logout_urls=(
            "https://sport-app.com/logout",
        ),
    ),
}


def get_env_config(name: str) -> EnvConfig:
    """Return the EnvConfig for the given environment name.

    Args:
        name: "dev" or "prod".

    Returns:
        The matching EnvConfig.

    Raises:
        ValueError: If the environment name is unknown.
    """
    key = name.strip().lower()
    if key not in _CONFIGS:
        valid = ", ".join(sorted(_CONFIGS))
        raise ValueError(f"Unknown environment '{name}'. Valid: {valid}")
    return _CONFIGS[key]

