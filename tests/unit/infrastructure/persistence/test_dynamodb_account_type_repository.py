"""Unit tests for DynamoDBAccountTypeRepository using moto mock.

Tests all repository methods against a local mocked DynamoDB table.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from typing import Generator
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from application.ports.shared_types import PaginatedResult, PaginationParams
from domain.entities.account_type import AccountType
from infrastructure.persistence.dynamodb_account_type_repository import (
    DynamoDBAccountTypeRepository,
)


# ──── DynamoDB Table Setup ────────────────────────────────────────────────────

TABLE_NAME = "sport-test-table"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required environment variables for DynamoDB client."""
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "test-pool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def _create_table(dynamodb_resource: object) -> object:
    """Create the DynamoDB table with the required schema and GSIs."""
    table = dynamodb_resource.create_table(  # type: ignore[attr-defined]
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture
def repo() -> Generator[DynamoDBAccountTypeRepository, None, None]:
    """Create repository with mocked DynamoDB table."""
    with mock_aws():
        # Reset singletons so they pick up the mocked environment
        import infrastructure.config.dynamodb_client as ddb_mod
        import infrastructure.config.environment as env_mod

        ddb_mod._dynamodb_resource = None
        ddb_mod._table = None
        env_mod._config = None

        # Create the mocked table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)

        yield DynamoDBAccountTypeRepository()

        # Clean up singletons
        ddb_mod._dynamodb_resource = None
        ddb_mod._table = None
        env_mod._config = None


def _make_account_type(
    name: str = "Socio",
    account_type_id: str = "at-uuid-001",
    status: str = "active",
) -> AccountType:
    """Create an AccountType entity for testing."""
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    return AccountType.reconstitute(
        account_type_id=account_type_id,
        tenant_id=TENANT_ID,
        name=name,
        description="Test account type",
        config={"color": "blue"},
        status=status,
        created_at=now,
        updated_at=now,
    )


# ──── Test: save ──────────────────────────────────────────────────────────────


class TestSave:
    """Tests for the save method."""

    @pytest.mark.asyncio
    async def test_save_persists_and_returns_entity(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """save() persists the account type and returns the same entity."""
        account_type = _make_account_type()

        result = await repo.save(account_type)

        assert result == account_type
        assert result.name == "Socio"
        assert result.tenant_id == TENANT_ID

    @pytest.mark.asyncio
    async def test_save_makes_entity_retrievable(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """After save, entity is retrievable by find_by_id."""
        account_type = _make_account_type()
        await repo.save(account_type)

        found = await repo.find_by_id(TENANT_ID, "at-uuid-001")

        assert found is not None
        assert found.account_type_id == "at-uuid-001"
        assert found.name == "Socio"


# ──── Test: find_by_id ────────────────────────────────────────────────────────


class TestFindById:
    """Tests for the find_by_id method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_by_id returns None when no matching item exists."""
        result = await repo.find_by_id(TENANT_ID, "nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_correct_entity(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_by_id returns the correct entity with all fields."""
        account_type = _make_account_type()
        await repo.save(account_type)

        result = await repo.find_by_id(TENANT_ID, "at-uuid-001")

        assert result is not None
        assert result.account_type_id == "at-uuid-001"
        assert result.tenant_id == TENANT_ID
        assert result.name == "Socio"
        assert result.description == "Test account type"
        assert result.config == {"color": "blue"}
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_isolation_between_tenants(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_by_id does not return items from a different tenant."""
        account_type = _make_account_type()
        await repo.save(account_type)

        other_tenant = "99999999-0000-0000-0000-000000000000"
        result = await repo.find_by_id(other_tenant, "at-uuid-001")

        assert result is None


# ──── Test: find_by_name_in_tenant ────────────────────────────────────────────


class TestFindByNameInTenant:
    """Tests for the find_by_name_in_tenant method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_name_not_found(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_by_name_in_tenant returns None when no matching name exists."""
        result = await repo.find_by_name_in_tenant(TENANT_ID, "NonExistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_finds_by_exact_name_case_insensitive(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_by_name_in_tenant matches regardless of case."""
        account_type = _make_account_type(name="Profesional")
        await repo.save(account_type)

        # Search with different case
        result = await repo.find_by_name_in_tenant(TENANT_ID, "PROFESIONAL")

        assert result is not None
        assert result.name == "Profesional"

    @pytest.mark.asyncio
    async def test_finds_with_lowercase_input(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_by_name_in_tenant works with lowercase input."""
        account_type = _make_account_type(name="Usuario")
        await repo.save(account_type)

        result = await repo.find_by_name_in_tenant(TENANT_ID, "usuario")

        assert result is not None
        assert result.name == "Usuario"

    @pytest.mark.asyncio
    async def test_does_not_cross_tenants(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_by_name_in_tenant does not return items from other tenants."""
        account_type = _make_account_type(name="Socio")
        await repo.save(account_type)

        other_tenant = "99999999-0000-0000-0000-000000000000"
        result = await repo.find_by_name_in_tenant(other_tenant, "Socio")

        assert result is None


# ──── Test: find_all_by_tenant ────────────────────────────────────────────────


class TestFindAllByTenant:
    """Tests for the find_all_by_tenant method."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_items(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_all_by_tenant returns empty list when no account types exist."""
        pagination = PaginationParams(limit=20)

        result = await repo.find_all_by_tenant(TENANT_ID, pagination)

        assert result.items == []
        assert result.next_cursor is None

    @pytest.mark.asyncio
    async def test_returns_all_items_for_tenant(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_all_by_tenant returns all account types for the tenant."""
        at1 = _make_account_type(name="Socio", account_type_id="at-001")
        at2 = _make_account_type(name="Usuario", account_type_id="at-002")
        at3 = _make_account_type(name="Profesional", account_type_id="at-003")
        await repo.save(at1)
        await repo.save(at2)
        await repo.save(at3)

        pagination = PaginationParams(limit=20)
        result = await repo.find_all_by_tenant(TENANT_ID, pagination)

        assert len(result.items) == 3
        names = {item.name for item in result.items}
        assert names == {"Socio", "Usuario", "Profesional"}

    @pytest.mark.asyncio
    async def test_pagination_limits_results(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_all_by_tenant respects the pagination limit."""
        for i in range(5):
            at = _make_account_type(name=f"Type{i}", account_type_id=f"at-{i:03d}")
            await repo.save(at)

        pagination = PaginationParams(limit=3)
        result = await repo.find_all_by_tenant(TENANT_ID, pagination)

        assert len(result.items) == 3
        assert result.next_cursor is not None

    @pytest.mark.asyncio
    async def test_pagination_cursor_retrieves_next_page(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """Using next_cursor retrieves the remaining items."""
        for i in range(5):
            at = _make_account_type(name=f"Type{i}", account_type_id=f"at-{i:03d}")
            await repo.save(at)

        # First page
        pagination = PaginationParams(limit=3)
        first_page = await repo.find_all_by_tenant(TENANT_ID, pagination)

        # Second page using cursor
        pagination2 = PaginationParams(limit=3, cursor=first_page.next_cursor)
        second_page = await repo.find_all_by_tenant(TENANT_ID, pagination2)

        assert len(second_page.items) == 2
        # Ensure no overlap
        first_ids = {item.account_type_id for item in first_page.items}
        second_ids = {item.account_type_id for item in second_page.items}
        assert first_ids.isdisjoint(second_ids)

    @pytest.mark.asyncio
    async def test_does_not_return_other_tenant_items(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """find_all_by_tenant only returns items for the specified tenant."""
        # Save for our tenant
        at1 = _make_account_type(name="Socio", account_type_id="at-001")
        await repo.save(at1)

        # Save for another tenant (manually using a different entity)
        other_at = AccountType.reconstitute(
            account_type_id="at-other",
            tenant_id="99999999-0000-0000-0000-000000000000",
            name="Other",
            description=None,
            config=None,
            status="active",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        await repo.save(other_at)

        pagination = PaginationParams(limit=20)
        result = await repo.find_all_by_tenant(TENANT_ID, pagination)

        assert len(result.items) == 1
        assert result.items[0].name == "Socio"

    @pytest.mark.asyncio
    async def test_invalid_cursor_treated_as_no_cursor(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """An invalid cursor string is gracefully ignored (starts from beginning)."""
        at = _make_account_type(name="Socio", account_type_id="at-001")
        await repo.save(at)

        pagination = PaginationParams(limit=20, cursor="invalid-base64-cursor")
        result = await repo.find_all_by_tenant(TENANT_ID, pagination)

        assert len(result.items) == 1


# ──── Test: update ────────────────────────────────────────────────────────────


class TestUpdate:
    """Tests for the update method."""

    @pytest.mark.asyncio
    async def test_update_persists_changes(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """update() persists changes to the entity."""
        account_type = _make_account_type(name="Socio")
        await repo.save(account_type)

        # Modify entity
        account_type.update_name("Socio Premium")
        await repo.update(account_type)

        # Verify
        found = await repo.find_by_id(TENANT_ID, "at-uuid-001")
        assert found is not None
        assert found.name == "Socio Premium"

    @pytest.mark.asyncio
    async def test_update_updates_gsi_keys(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """update() updates GSI1 keys so name lookup reflects the change."""
        account_type = _make_account_type(name="Socio")
        await repo.save(account_type)

        # Modify name
        account_type.update_name("Socio Gold")
        await repo.update(account_type)

        # Old name should not be found
        old_result = await repo.find_by_name_in_tenant(TENANT_ID, "Socio")
        assert old_result is None

        # New name should be found
        new_result = await repo.find_by_name_in_tenant(TENANT_ID, "Socio Gold")
        assert new_result is not None
        assert new_result.name == "Socio Gold"

    @pytest.mark.asyncio
    async def test_update_returns_entity(
        self, repo: DynamoDBAccountTypeRepository
    ) -> None:
        """update() returns the updated entity."""
        account_type = _make_account_type(name="Socio")
        await repo.save(account_type)

        account_type.update_name("Socio Plus")
        result = await repo.update(account_type)

        assert result.name == "Socio Plus"
