"""Unit tests for DynamoDBMemberRepository using moto DynamoDB mock."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from api.common.ports.sharedTypes import MemberFilters, PaginatedResult, PaginationParams
from api.member.member import Member
from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.userRole import UserRole
from api.member.dynamodbMemberRepository import DynamoDBMemberRepository


# ──── Constants ───────────────────────────────────────────────────────────────

TABLE_NAME = "test-sport-table"
REGION = "us-east-1"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
MEMBER_ID = "660e8400-e29b-41d4-a716-446655440001"
USER_ID = "770e8400-e29b-41d4-a716-446655440002"
ACCOUNT_TYPE_ID = "880e8400-e29b-41d4-a716-446655440003"


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required environment variables for the config singleton."""
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("REGION", REGION)
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "test-pool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client")


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """Reset module-level singletons between tests."""
    import api.common.config.dynamodbClient as dc_mod
    import api.common.config.environment as env_mod

    env_mod._config = None
    dc_mod._dynamodb_resource = None
    dc_mod._table = None
    yield  # type: ignore[misc]
    env_mod._config = None
    dc_mod._dynamodb_resource = None
    dc_mod._table = None


@pytest.fixture
def dynamodb_table():
    """Create a moto DynamoDB table with the required GSIs."""
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
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
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
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield


@pytest.fixture
def repo(dynamodb_table) -> DynamoDBMemberRepository:
    """Create a repository instance with the mocked table."""
    return DynamoDBMemberRepository()


@pytest.fixture
def sample_member() -> Member:
    """Create a sample Member entity for testing."""
    now = datetime.now(UTC)
    return Member.reconstitute(
        member_id=MEMBER_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        account_type="socio",
        account_type_id=ACCOUNT_TYPE_ID,
        full_name="Juan Garcia",
        email="juan@example.com",
        status="active",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=now,
        updated_at=now,
    )


# ──── Tests: find_by_id ──────────────────────────────────────────────────────


class TestFindById:
    """Tests for find_by_id method."""

    def test_returns_none_when_member_not_found(self, repo: DynamoDBMemberRepository) -> None:
        result = repo.find_by_id(TENANT_ID, "nonexistent-id")
        assert result is None

    def test_returns_member_when_found(
        self, repo: DynamoDBMemberRepository, sample_member: Member
    ) -> None:
        # Persist the member first
        repo.save(sample_member)

        # Find it
        result = repo.find_by_id(TENANT_ID, MEMBER_ID)
        assert result is not None
        assert result.member_id == MEMBER_ID
        assert result.tenant_id == TENANT_ID
        assert result.email == "juan@example.com"
        assert result.full_name == "Juan Garcia"
        assert result.account_type == "socio"
        assert result.status == "active"

    def test_does_not_find_member_from_different_tenant(
        self, repo: DynamoDBMemberRepository, sample_member: Member
    ) -> None:
        repo.save(sample_member)
        other_tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = repo.find_by_id(other_tenant, MEMBER_ID)
        assert result is None


# ──── Tests: find_by_user_in_tenant ───────────────────────────────────────────


class TestFindByUserInTenant:
    """Tests for find_by_user_in_tenant method."""

    def test_returns_none_when_user_not_member(self, repo: DynamoDBMemberRepository) -> None:
        result = repo.find_by_user_in_tenant(TENANT_ID, "nonexistent-user")
        assert result is None

    def test_returns_member_when_user_is_member(
        self, repo: DynamoDBMemberRepository, sample_member: Member
    ) -> None:
        repo.save(sample_member)

        result = repo.find_by_user_in_tenant(TENANT_ID, USER_ID)
        assert result is not None
        assert result.user_id == USER_ID
        assert result.tenant_id == TENANT_ID
        assert result.member_id == MEMBER_ID

    def test_does_not_find_user_in_different_tenant(
        self, repo: DynamoDBMemberRepository, sample_member: Member
    ) -> None:
        repo.save(sample_member)
        other_tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = repo.find_by_user_in_tenant(other_tenant, USER_ID)
        assert result is None


# ──── Tests: save ─────────────────────────────────────────────────────────────


class TestSave:
    """Tests for save method."""

    def test_saves_and_returns_member(
        self, repo: DynamoDBMemberRepository, sample_member: Member
    ) -> None:
        result = repo.save(sample_member)
        assert result.member_id == sample_member.member_id
        assert result.email == sample_member.email

        # Verify it's actually persisted
        found = repo.find_by_id(TENANT_ID, MEMBER_ID)
        assert found is not None
        assert found.member_id == MEMBER_ID


# ──── Tests: update ───────────────────────────────────────────────────────────


class TestUpdate:
    """Tests for update method."""

    def test_updates_member_fields(
        self, repo: DynamoDBMemberRepository, sample_member: Member
    ) -> None:
        repo.save(sample_member)

        # Update the member
        updated_member = sample_member.update(
            full_name="Juan Garcia Updated",
            status="inactive",
        )
        repo.update(updated_member)

        # Verify the update
        found = repo.find_by_id(TENANT_ID, MEMBER_ID)
        assert found is not None
        assert found.full_name == "Juan Garcia Updated"
        assert found.status == "inactive"


# ──── Tests: find_by_tenant_and_filters ───────────────────────────────────────


class TestFindByTenantAndFilters:
    """Tests for find_by_tenant_and_filters method."""

    def _create_members(self, repo: DynamoDBMemberRepository) -> list[Member]:
        """Create multiple test members with different attributes."""
        now = datetime.now(UTC)
        members = []
        configs = [
            ("mem-001", "socio", "active", "Alice Smith", "alice@example.com"),
            ("mem-002", "socio", "inactive", "Bob Jones", "bob@example.com"),
            ("mem-003", "usuario", "active", "Carlos Lopez", "carlos@example.com"),
            ("mem-004", "profesional", "active", "Diana Garcia", "diana@example.com"),
        ]
        for mid, acc_type, status, name, email in configs:
            m = Member.reconstitute(
                member_id=mid,
                tenant_id=TENANT_ID,
                user_id=f"user-{mid}",
                account_type=acc_type,
                account_type_id=ACCOUNT_TYPE_ID,
                full_name=name,
                email=email,
                status=status,
                registration_type="self",
                invited_by=None,
                metadata=None,
                created_at=now,
                updated_at=now,
            )
            repo.save(m)
            members.append(m)
        return members

    def test_returns_all_members_without_filters(self, repo: DynamoDBMemberRepository) -> None:
        self._create_members(repo)

        result = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(),
            PaginationParams(limit=100),
        )
        assert len(result.items) == 4

    def test_filters_by_account_type(self, repo: DynamoDBMemberRepository) -> None:
        self._create_members(repo)

        result = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(account_type="socio"),
            PaginationParams(limit=100),
        )
        assert len(result.items) == 2
        assert all(m.account_type == "socio" for m in result.items)

    def test_filters_by_account_type_case_insensitive(
        self, repo: DynamoDBMemberRepository
    ) -> None:
        self._create_members(repo)

        result = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(account_type="SOCIO"),
            PaginationParams(limit=100),
        )
        assert len(result.items) == 2

    def test_filters_by_status(self, repo: DynamoDBMemberRepository) -> None:
        self._create_members(repo)

        result = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(status="active"),
            PaginationParams(limit=100),
        )
        assert len(result.items) == 3
        assert all(m.status == "active" for m in result.items)

    def test_filters_by_account_type_and_status(self, repo: DynamoDBMemberRepository) -> None:
        self._create_members(repo)

        result = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(account_type="socio", status="active"),
            PaginationParams(limit=100),
        )
        assert len(result.items) == 1
        assert result.items[0].full_name == "Alice Smith"

    def test_pagination_limits_results(self, repo: DynamoDBMemberRepository) -> None:
        self._create_members(repo)

        result = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(account_type="socio"),
            PaginationParams(limit=1),
        )
        assert len(result.items) == 1
        assert result.next_cursor is not None

    def test_pagination_cursor_returns_next_page(self, repo: DynamoDBMemberRepository) -> None:
        self._create_members(repo)

        # Get first page
        page1 = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(account_type="socio"),
            PaginationParams(limit=1),
        )
        assert len(page1.items) == 1
        assert page1.next_cursor is not None

        # Get second page
        page2 = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(account_type="socio"),
            PaginationParams(limit=1, cursor=page1.next_cursor),
        )
        assert len(page2.items) == 1
        # No overlap between pages
        assert page1.items[0].member_id != page2.items[0].member_id

    def test_returns_empty_for_nonexistent_account_type(
        self, repo: DynamoDBMemberRepository
    ) -> None:
        self._create_members(repo)

        result = repo.find_by_tenant_and_filters(
            TENANT_ID,
            MemberFilters(account_type="nonexistent"),
            PaginationParams(limit=100),
        )
        assert len(result.items) == 0
        assert result.next_cursor is None


# ──── Tests: count_active_by_account_type ─────────────────────────────────────


class TestCountActiveByAccountType:
    """Tests for count_active_by_account_type method."""

    def test_counts_only_active_members(self, repo: DynamoDBMemberRepository) -> None:
        now = datetime.now(UTC)
        # Create 2 active and 1 inactive member with same account_type
        for i, status in enumerate(["active", "active", "inactive"]):
            m = Member.reconstitute(
                member_id=f"count-{i}",
                tenant_id=TENANT_ID,
                user_id=f"user-count-{i}",
                account_type="socio",
                account_type_id=ACCOUNT_TYPE_ID,
                full_name=f"User {i}",
                email=f"user{i}@example.com",
                status=status,
                registration_type="self",
                invited_by=None,
                metadata=None,
                created_at=now,
                updated_at=now,
            )
            repo.save(m)

        count = repo.count_active_by_account_type(TENANT_ID, "socio")
        assert count == 2

    def test_returns_zero_when_no_active_members(self, repo: DynamoDBMemberRepository) -> None:
        count = repo.count_active_by_account_type(TENANT_ID, "nonexistent")
        assert count == 0

    def test_case_insensitive_account_type_match(self, repo: DynamoDBMemberRepository) -> None:
        now = datetime.now(UTC)
        m = Member.reconstitute(
            member_id="case-test",
            tenant_id=TENANT_ID,
            user_id="user-case-test",
            account_type="Socio",
            account_type_id=ACCOUNT_TYPE_ID,
            full_name="Case Test",
            email="case@example.com",
            status="active",
            registration_type="self",
            invited_by=None,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        repo.save(m)

        # Query with different casing
        count = repo.count_active_by_account_type(TENANT_ID, "SOCIO")
        assert count == 1


# ──── Tests: create_member_with_roles ─────────────────────────────────────────


class TestCreateMemberWithRoles:
    """Tests for create_member_with_roles method."""

    def test_creates_all_records_atomically(self, repo: DynamoDBMemberRepository) -> None:
        now = datetime.now(UTC)

        membership = TenantMembership.reconstitute(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            status="active",
            joined_at=now,
        )

        member = Member.reconstitute(
            member_id=MEMBER_ID,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            account_type="socio",
            account_type_id=ACCOUNT_TYPE_ID,
            full_name="Juan Garcia",
            email="juan@example.com",
            status="active",
            registration_type="invited",
            invited_by="admin-user-id",
            metadata=None,
            created_at=now,
            updated_at=now,
        )

        role = UserRole.reconstitute(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            role_name="viewer",
            assigned_at=now,
        )

        repo.create_member_with_roles(membership, member, [role])

        # Verify member was created
        found = repo.find_by_id(TENANT_ID, MEMBER_ID)
        assert found is not None
        assert found.member_id == MEMBER_ID
        assert found.full_name == "Juan Garcia"

        # Verify membership was created (check via raw table access)
        from api.common.config.dynamodbClient import get_dynamodb_table

        table = get_dynamodb_table()
        membership_response = table.get_item(
            Key={
                "PK": f"TENANT#{TENANT_ID}#USER#{USER_ID}",
                "SK": "MEMBERSHIP",
            }
        )
        assert "Item" in membership_response
        assert membership_response["Item"]["status"] == "active"

        # Verify role was created
        role_response = table.get_item(
            Key={
                "PK": f"TENANT#{TENANT_ID}#USER#{USER_ID}",
                "SK": "ROLE#viewer",
            }
        )
        assert "Item" in role_response
        assert role_response["Item"]["role_name"] == "viewer"

    def test_creates_multiple_roles(self, repo: DynamoDBMemberRepository) -> None:
        now = datetime.now(UTC)

        membership = TenantMembership.reconstitute(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            status="active",
            joined_at=now,
        )

        member = Member.reconstitute(
            member_id=MEMBER_ID,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            account_type="socio",
            account_type_id=ACCOUNT_TYPE_ID,
            full_name="Juan Garcia",
            email="juan@example.com",
            status="active",
            registration_type="invited",
            invited_by="admin-user-id",
            metadata=None,
            created_at=now,
            updated_at=now,
        )

        roles = [
            UserRole.reconstitute(
                user_id=USER_ID,
                tenant_id=TENANT_ID,
                role_name="admin",
                assigned_at=now,
            ),
            UserRole.reconstitute(
                user_id=USER_ID,
                tenant_id=TENANT_ID,
                role_name="manager",
                assigned_at=now,
            ),
        ]

        repo.create_member_with_roles(membership, member, roles)

        # Verify both roles were created
        from api.common.config.dynamodbClient import get_dynamodb_table

        table = get_dynamodb_table()

        admin_response = table.get_item(
            Key={
                "PK": f"TENANT#{TENANT_ID}#USER#{USER_ID}",
                "SK": "ROLE#admin",
            }
        )
        assert "Item" in admin_response

        manager_response = table.get_item(
            Key={
                "PK": f"TENANT#{TENANT_ID}#USER#{USER_ID}",
                "SK": "ROLE#manager",
            }
        )
        assert "Item" in manager_response


# ──── Tests: cursor encoding/decoding ─────────────────────────────────────────


class TestCursorEncoding:
    """Tests for pagination cursor encoding/decoding."""

    def test_encode_decode_roundtrip(self) -> None:
        key = {"PK": "TENANT#123#MEMBER#456", "SK": "PROFILE"}
        encoded = DynamoDBMemberRepository._encode_cursor(key)
        decoded = DynamoDBMemberRepository._decode_cursor(encoded)
        assert decoded == key

    def test_cursor_is_base64_string(self) -> None:
        key = {"PK": "test", "SK": "value"}
        encoded = DynamoDBMemberRepository._encode_cursor(key)
        # Should be valid base64
        decoded_bytes = base64.b64decode(encoded)
        parsed = json.loads(decoded_bytes)
        assert parsed == key
