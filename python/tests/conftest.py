"""Shared pytest fixtures.

Resets module-level singletons between tests so that per-test environment
variables (set via monkeypatch/os.environ in individual fixtures) are picked up
fresh, instead of leaking a configuration cached by an earlier test.

The infrastructure layer caches the environment config and DynamoDB client as
module-level singletons for Lambda warm-invocation reuse. In the test process
those singletons persist across tests, which makes behavior depend on test
ordering. This autouse fixture clears them before each test.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_infra_singletons() -> None:
    """Reset cached config/client singletons before each test."""
    import api.common.config.dynamodbClient as dynamodb_client
    import api.common.config.environment as environment

    environment._config = None
    dynamodb_client._dynamodb_resource = None
    dynamodb_client._table = None
