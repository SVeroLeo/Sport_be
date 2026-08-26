"""Unit tests for DynamoDBTenantRepository."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from infrastructure.persistence.dynamodb_tenant_repository import (
    DynamoDBTenantRepository,
)


# ──── Constants ───────────────────────────────────────────────────────────────

TABLE_NAME = "test-table"
REGION = "us-east-1"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _env_vars() -> None:  # type: ignore[misc]
    """Set required environment variables."""
    os.environ["TABLE_NAME"] = TABLE_NAME
    os.environ["REGION"] = REGION
    os.environ["JWT_SECRET"] = "test-secret"
    os.environ["TOKEN_EXPIRY"] = "3600"
    os.environ["SALT_ROUNDS"] = "4"


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:  # type: ignore[misc]
    """Reset module-level singletons between tests."""
    import infrastructure.config.dynamodb_client as db_module
    import infrastructure.config.environment as env_module

    env_module._config = None
    db_module._dynamodb_resource = None
    db_module._table = None


@pytest.fixture
def dynamodb_table():
    """Create a mocked DynamoDB table with moto."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name=REGION)
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
        yield table


@pytest.fixture
def repository() -> DynamoDBTenantRepository:
    """Create a DynamoDBTenantRepository instance."""
    return DynamoDBTenantRepository()


# ──── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_by_id_returns_tenant_when_exists(dynamodb_table, repository):
    """Should return a Tenant entity when the item exists in DynamoDB."""
    created_at = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    dynamodb_table.put_item(
        Item={
            "PK": f"TENANT#{TENANT_ID}",
            "SK": "METADATA",
            "tenant_id": TENANT_ID,
            "name": "Club Deportivo Test",
            "plan": "premium",
            "status": "active",
            "allow_self_registration": True,
            "default_account_type": "usuario",
            "created_at": created_at.isoformat(),
        }
    )

    with patch(
        "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
        return_value=dynamodb_table,
    ):
        result = await repository.find_by_id(TENANT_ID)

    assert result is not None
    assert result.tenant_id.value == TENANT_ID
    assert result.name == "Club Deportivo Test"
    assert result.plan == "premium"
    assert result.status == "active"
    assert result.allow_self_registration is True
    assert result.default_account_type == "usuario"


@pytest.mark.asyncio
async def test_find_by_id_returns_none_when_not_found(dynamodb_table, repository):
    """Should return None when no tenant exists with the given ID."""
    non_existent_id = "99999999-aaaa-bbbb-cccc-000000000000"

    with patch(
        "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
        return_value=dynamodb_table,
    ):
        result = await repository.find_by_id(non_existent_id)

    assert result is None


@pytest.mark.asyncio
async def test_find_by_id_uses_correct_key_schema(dynamodb_table, repository):
    """Should query using PK=TENANT#{tenant_id} and SK=METADATA."""
    # Put an item with the same PK but different SK — should NOT be returned
    dynamodb_table.put_item(
        Item={
            "PK": f"TENANT#{TENANT_ID}",
            "SK": "OTHER_RECORD",
            "tenant_id": TENANT_ID,
            "name": "Wrong Record",
            "status": "active",
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    )

    with patch(
        "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
        return_value=dynamodb_table,
    ):
        result = await repository.find_by_id(TENANT_ID)

    # Should not find anything since there's no SK=METADATA item
    assert result is None


@pytest.mark.asyncio
async def test_find_by_id_handles_optional_fields(dynamodb_table, repository):
    """Should handle tenants with optional fields set to None/defaults."""
    created_at = datetime(2024, 6, 1, 8, 0, 0, tzinfo=timezone.utc)

    dynamodb_table.put_item(
        Item={
            "PK": f"TENANT#{TENANT_ID}",
            "SK": "METADATA",
            "tenant_id": TENANT_ID,
            "name": "Basic Club",
            "status": "inactive",
            "created_at": created_at.isoformat(),
        }
    )

    with patch(
        "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
        return_value=dynamodb_table,
    ):
        result = await repository.find_by_id(TENANT_ID)

    assert result is not None
    assert result.name == "Basic Club"
    assert result.plan is None
    assert result.status == "inactive"
    assert result.allow_self_registration is False
    assert result.default_account_type is None
