"""CDK app entry point.

Synthesizes one application stack per environment (dev and prod), both in
sa-east-1. Select which environments to deploy with the `-c env=dev|prod|all`
context flag; defaults to synthesizing both.

Examples:
    cdk synth
    cdk deploy -c env=dev
    cdk deploy -c env=prod
    cdk deploy -c env=all --require-approval never
"""

from __future__ import annotations

import os

import aws_cdk as cdk

from config import get_env_config
from stacks.app_stack import AccountManagementStack


def _account() -> str | None:
    """Resolve the target AWS account from the standard CDK env var, if present."""
    return os.environ.get("CDK_DEFAULT_ACCOUNT")


def main() -> None:
    """Build the CDK app and its per-environment stacks."""
    app = cdk.App()

    # Which environment(s) to synthesize: dev, prod, or all (default).
    selected = str(app.node.try_get_context("env") or "all").lower()
    env_names = ["dev", "prod"] if selected == "all" else [selected]

    for env_name in env_names:
        cfg = get_env_config(env_name)
        AccountManagementStack(
            app,
            f"AccountManagement-{cfg.name}",
            config=cfg,
            env=cdk.Environment(account=_account(), region=cfg.region),
            description=f"Account Management backend ({cfg.name}) - single region {cfg.region}",
        )

    app.synth()


if __name__ == "__main__":
    main()
