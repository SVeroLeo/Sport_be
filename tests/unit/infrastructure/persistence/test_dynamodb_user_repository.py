"""Unit tests for DynamoDBUserRepository using moto mock."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from domain.entities.member import Member
from domain.entities.tenant_membership import TenantMembership
from domain.entities.user import User
from domain.entities.user_role import UserRole
from domain.value_objects.email import Email
from infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars for moto and environment config."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "sport-test-table")
    monkeypatch.setenv("REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "test-pool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client")


@pytest.fixture
def dynamodb_table():
    """Create a moto-mocked DynamoDB table and return the Table resource."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="sport-test-table",
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
        table.wait_until_exists()
        yield table


@pytest.fixture
def repo(dynamodb_table) -> DynamoDBUserRepository:
    """Create a DynamoDBUserRepository with the moto-mocked table."""
    return DynamoDBUserRepository(table=dynamodb_table)


def _make_user(
    email: str = "test@example.com",
    user_id: str | None = None,
    status: str = "active",
) -> User:
    """Helper to create a User entity for testing."""
    uid = user_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    return User.reconstitute(
        user_id=uid,
        email=email,
        cognito_sub=f"cognito-sub-{uid[:8]}",
        full_name="Test User",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_membership(user_id: str, tenant_id: str) -> TenantMembership:
    """Helper to create a TenantMembership entity."""
    return TenantMembership.reconstitute(
        user_id=user_id,
        tenant_id=tenant_id,
        status="active",
        joined_at=datetime.now(UTC),
    )


def _make_member(tenant_id: str, user_id: str) -> Member:
    """Helper to create a Member entity."""
    return Member.reconstitute(
        member_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        account_type="socio",
        account_type_id=str(uuid.uuid4()),
        full_name="Test User",
        email="test@example.com",
        status="active",
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_role(user_id: str, tenant_id: str, role_name: str = "viewer") -> UserRole:
    """Helper to create a UserRole entity."""
    return UserRole.reconstitute(
        user_id=user_id,
        tenant_id=tenant_id,
        role_name=role_name,
        assigned_at=datetime.now(UTC),
    )


class TestFindByEmail:
    """Tests for DynamoDBUserRepository.find_by_email."""

    def test_returns_user_when_found(self, repo: DynamoDBUserRepository) -> None:
        user = _make_user(email="alice@example.com")
        repo.save(user)

        result = repo.find_by_email(Email(value="alice@example.com"))

        assert result is not None
        assert result.user_id == user.user_id
        assert result.email.value == "alice@example.com"

    def test_returns_none_when_not_found(self, repo: DynamoDBUserRepository) -> None:
        result = repo.find_by_email(Email(value="noone@example.com"))

        assert result is None


class TestFindById:
    """Tests for DynamoDBUserRepository.find_by_id."""

    def test_returns_user_when_found(self, repo: DynamoDBUserRepository) -> None:
        user = _make_user(email="bob@example.com", user_id="uid-123-456")
        repo.save(user)

        result = repo.find_by_id("uid-123-456")

        assert result is not None
        assert result.user_id == "uid-123-456"
        assert result.email.value == "bob@example.com"

    def test_returns_none_when_not_found(self, repo: DynamoDBUserRepository) -> None:
        result = repo.find_by_id("nonexistent-id")

        assert result is None


class TestSave:
    """Tests for DynamoDBUserRepository.save."""

    def test_creates_new_user(self, repo: DynamoDBUserRepository) -> None:
        user = _make_user(email="new@example.com")
        result = repo.save(user)

        assert result.user_id == user.user_id

        # Verify it can be read back
        found = repo.find_by_email(Email(value="new@example.com"))
        assert found is not None
        assert found.user_id == user.user_id

    def test_overwrites_existing_user(self, repo: DynamoDBUserRepository) -> None:
        user = _make_user(email="update@example.com", status="active")
        repo.save(user)

        # Reconstitute with updated status
        updated = User.reconstitute(
            user_id=user.user_id,
            email="update@example.com",
            cognito_sub=user.cognito_sub,
            full_name="Updated Name",
            status="inactive",
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
        )
        repo.save(updated)

        found = repo.find_by_email(Email(value="update@example.com"))
        assert found is not None
        assert found.status == "inactive"
        assert found.full_name.value == "Updated Name"


class TestGetRolesForTenant:
    """Tests for DynamoDBUserRepository.get_roles_for_tenant."""

    def test_returns_roles_for_user_in_tenant(self, repo: DynamoDBUserRepository) -> None:
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        user = _make_user(email="roles@example.com", user_id=user_id)
        membership = _make_membership(user_id, tenant_id)
        member = _make_member(tenant_id, user_id)
        role = _make_role(user_id, tenant_id, "admin")

        repo.register_with_membership(user, membership, member, role)

        roles = repo.get_roles_for_tenant(user_id, tenant_id)

        assert len(roles) == 1
        assert roles[0].role_name == "admin"
        assert roles[0].user_id == user_id
        assert roles[0].tenant_id == tenant_id

    def test_returns_empty_list_when_no_roles(self, repo: DynamoDBUserRepository) -> None:
        roles = repo.get_roles_for_tenant("no-user", "no-tenant")

        assert roles == []


class TestRegisterWithMembership:
    """Tests for DynamoDBUserRepository.register_with_membership."""

    def test_creates_all_records_atomically(self, repo: DynamoDBUserRepository, dynamodb_table) -> None:
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        user = _make_user(email="register@example.com", user_id=user_id)
        membership = _make_membership(user_id, tenant_id)
        member = _make_member(tenant_id, user_id)
        role = _make_role(user_id, tenant_id, "viewer")

        repo.register_with_membership(user, membership, member, role)

        # Verify user was created
        found_user = repo.find_by_email(Email(value="register@example.com"))
        assert found_user is not None
        assert found_user.user_id == user_id

        # Verify membership was created
        membership_response = dynamodb_table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{user_id}",
                "SK": "MEMBERSHIP",
            }
        )
        assert "Item" in membership_response

        # Verify member was created
        member_response = dynamodb_table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#MEMBER#{member.member_id}",
                "SK": "PROFILE",
            }
        )
        assert "Item" in member_response

        # Verify role was created
        role_response = dynamodb_table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{user_id}",
                "SK": "ROLE#viewer",
            }
        )
        assert "Item" in role_response

    def test_fails_if_user_already_exists(self, repo: DynamoDBUserRepository) -> None:
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        user = _make_user(email="duplicate@example.com", user_id=user_id)
        membership = _make_membership(user_id, tenant_id)
        member = _make_member(tenant_id, user_id)
        role = _make_role(user_id, tenant_id, "viewer")

        # First registration should succeed
        repo.register_with_membership(user, membership, member, role)

        # Second registration with same email should fail (condition expression)
        user2 = _make_user(email="duplicate@example.com", user_id=str(uuid.uuid4()))
        member2 = _make_member(tenant_id, user2.user_id)
        membership2 = _make_membership(user2.user_id, tenant_id)
        role2 = _make_role(user2.user_id, tenant_id, "viewer")

        with pytest.raises(Exception):  # ClientError from DynamoDB
            repo.register_with_membership(user2, membership2, member2, role2)


class TestCreateUserWithMembership:
    """Tests for DynamoDBUserRepository.create_user_with_membership."""

    def test_creates_all_records_with_multiple_roles(
        self, repo: DynamoDBUserRepository, dynamodb_table
    ) -> None:
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        user = _make_user(email="invited@example.com", user_id=user_id, status="pending_confirmation")
        membership = _make_membership(user_id, tenant_id)
        member = _make_member(tenant_id, user_id)
        roles = [
            _make_role(user_id, tenant_id, "admin"),
            _make_role(user_id, tenant_id, "manager"),
        ]

        repo.create_user_with_membership(user, membership, member, roles)

        # Verify user was created
        found_user = repo.find_by_email(Email(value="invited@example.com"))
        assert found_user is not None
        assert found_user.status == "pending_confirmation"

        # Verify both roles were created
        found_roles = repo.get_roles_for_tenant(user_id, tenant_id)
        assert len(found_roles) == 2
        role_names = {r.role_name for r in found_roles}
        assert role_names == {"admin", "manager"}
