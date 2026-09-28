"""Property-based tests for Pagination correctness.

**Validates: Requirements 5.4, 6.1, 6.4, 6.5**

Properties tested:
- Property 18: Pagination Bounded Response
  - Sub-property 1: Max items per page (limit clamped to [1, 100])
  - Sub-property 2: Non-overlapping cursor pages (full iteration returns all items exactly once)
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Generator

import boto3
import hypothesis.strategies as st
import pytest
from hypothesis import given, settings
from moto import mock_aws

from api.common.ports.sharedTypes import PaginationParams
from api.accountType.accountType import AccountType
from api.accountType.dynamodbAccountTypeRepository import (
    DynamoDBAccountTypeRepository,
)


# â”€â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

TABLE_NAME = "sport-test-table"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


# â”€â”€â”€ DynamoDB Table Setup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required environment variables for DynamoDB client."""
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("REGION", "us-east-1")
    monkeypatch.setenv("TOKEN_EXPIRY", "3600")
    monkeypatch.setenv("SALT_ROUNDS", "4")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "test-pool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@contextmanager
def _moto_repo() -> Generator[DynamoDBAccountTypeRepository, None, None]:
    """Context manager that creates a fresh moto DynamoDB + repo per invocation.

    This avoids Hypothesis's function-scoped fixture issue by managing
    the moto lifecycle inside each generated test case.
    """
    import api.common.config.dynamodbClient as ddb_mod
    import api.common.config.environment as env_mod

    with mock_aws():
        ddb_mod._dynamodb_resource = None
        ddb_mod._table = None
        env_mod._config = None

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(dynamodb)

        try:
            yield DynamoDBAccountTypeRepository()
        finally:
            ddb_mod._dynamodb_resource = None
            ddb_mod._table = None
            env_mod._config = None


# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _make_account_type(index: int) -> AccountType:
    """Create an AccountType entity with a unique ID and name."""
    return AccountType.reconstitute(
        account_type_id=f"at-{index:04d}",
        tenant_id=TENANT_ID,
        name=f"Type{index:04d}",
        description=f"Account type number {index}",
        config=None,
        status="active",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


# â”€â”€â”€ Property 18 Sub-property 1: PaginationParams Limit Clamping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestPaginationBoundedLimit:
    """Property 18 â€” Sub-property 1: Max items per page.

    For ANY requested limit (including values < 1 or > 100),
    PaginationParams ALWAYS clamps the effective limit to [1, 100].
    This guarantees no response page ever exceeds 100 items.

    **Validates: Requirements 5.4, 6.1**
    """

    @given(limit=st.integers(min_value=-1000, max_value=1000))
    @settings(max_examples=200)
    def test_pagination_params_limit_always_clamped_to_1_100(
        self,
        limit: int,
    ) -> None:
        """For ANY integer limit, PaginationParams.limit is always in [1, 100].

        **Validates: Requirements 5.4, 6.1**
        """
        params = PaginationParams(limit=limit)

        assert 1 <= params.limit <= 100

    @given(limit=st.integers(min_value=101, max_value=10000))
    @settings(max_examples=200)
    def test_limit_above_100_clamped_to_100(
        self,
        limit: int,
    ) -> None:
        """For ANY limit > 100, PaginationParams clamps to exactly 100.

        **Validates: Requirements 5.4, 6.1**
        """
        params = PaginationParams(limit=limit)

        assert params.limit == 100

    @given(limit=st.integers(min_value=-10000, max_value=0))
    @settings(max_examples=200)
    def test_limit_below_1_clamped_to_1(
        self,
        limit: int,
    ) -> None:
        """For ANY limit < 1, PaginationParams clamps to exactly 1.

        **Validates: Requirements 5.4, 6.1**
        """
        params = PaginationParams(limit=limit)

        assert params.limit == 1

    @given(limit=st.integers(min_value=1, max_value=100))
    @settings(max_examples=200)
    def test_valid_limit_preserved_unchanged(
        self,
        limit: int,
    ) -> None:
        """For ANY limit in [1, 100], PaginationParams preserves it exactly.

        **Validates: Requirements 5.4, 6.1**
        """
        params = PaginationParams(limit=limit)

        assert params.limit == limit


# â”€â”€â”€ Property 18 Sub-property 2: Non-overlapping Cursor Pages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestPaginationNonOverlappingPages:
    """Property 18 â€” Sub-property 2: Non-overlapping cursor pages.

    When iterating through ALL pages using cursors, the union of all pages
    equals the full result set and NO item appears in more than one page.

    **Validates: Requirements 6.4, 6.5**
    """

    @given(
        num_items=st.integers(min_value=5, max_value=50),
        page_size=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_paginated_iteration_returns_all_items_without_overlap(
        self,
        num_items: int,
        page_size: int,
    ) -> None:
        """For ANY number of items and page size, paginated iteration collects
        all items exactly once with no overlaps.

        **Validates: Requirements 6.4, 6.5**
        """
        with _moto_repo() as repo:
            # Arrange â€” insert N account types
            for i in range(num_items):
                await repo.save(_make_account_type(i))

            # Act â€” paginate through all pages
            all_ids: list[str] = []
            cursor: str | None = None
            pages_visited = 0
            max_pages = num_items + 10  # Safety limit to prevent infinite loops

            while pages_visited < max_pages:
                pagination = PaginationParams(limit=page_size, cursor=cursor)
                result = await repo.find_all_by_tenant(TENANT_ID, pagination)

                # Each page must have at most page_size items
                assert len(result.items) <= page_size

                all_ids.extend(item.account_type_id for item in result.items)
                pages_visited += 1

                if result.next_cursor is None:
                    break
                cursor = result.next_cursor

            # Assert â€” completeness: all items were returned
            assert len(all_ids) == num_items

            # Assert â€” no overlaps: each item appeared exactly once
            assert len(set(all_ids)) == num_items

    @given(
        num_items=st.integers(min_value=1, max_value=30),
        page_size=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_cursor_present_only_when_more_results_exist(
        self,
        num_items: int,
        page_size: int,
    ) -> None:
        """When more results exist, next_cursor is non-None; on the final page
        it is None.

        **Validates: Requirements 6.4**
        """
        with _moto_repo() as repo:
            # Arrange â€” insert items
            for i in range(num_items):
                await repo.save(_make_account_type(i))

            # Act â€” paginate
            cursor: str | None = None
            total_collected = 0
            max_pages = num_items + 10

            for _ in range(max_pages):
                pagination = PaginationParams(limit=page_size, cursor=cursor)
                result = await repo.find_all_by_tenant(TENANT_ID, pagination)

                total_collected += len(result.items)

                if result.next_cursor is None:
                    # This is the last page â€” we should have all items
                    assert total_collected == num_items
                    break
                else:
                    # More pages exist â€” we haven't collected everything yet
                    assert total_collected < num_items
                    cursor = result.next_cursor
            else:
                # If we exhausted max_pages without reaching the end, fail
                pytest.fail("Pagination did not terminate within expected number of pages")

    @given(page_size=st.integers(min_value=1, max_value=10))
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_empty_collection_returns_no_cursor(
        self,
        page_size: int,
    ) -> None:
        """When no items exist, the response has empty items and no cursor.

        **Validates: Requirements 6.4, 6.5**
        """
        with _moto_repo() as repo:
            pagination = PaginationParams(limit=page_size, cursor=None)
            result = await repo.find_all_by_tenant(TENANT_ID, pagination)

            assert result.items == []
            assert result.next_cursor is None
