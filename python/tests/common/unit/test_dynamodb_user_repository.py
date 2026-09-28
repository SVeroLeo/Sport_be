"""Unit tests for DynamoDBUserRepository using moto mock."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from api.member.member import Member
from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.user import User
from api.common.user.userRole import UserRole
from api.common.valueObjects.email import Email
from api.common.user.dynamodbUserRepository import DynamoDBUserRepository


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


def _make_social_user(
    email: str = "social@example.com",
    user_id: str | None = None,
    cognito_sub: str | None = None,
    status: str = "pending_tenant",
    default_tenant_id: str | None = None,
) -> User:
    """Helper to create a social-login User entity for testing.

    Builds a User via the domain factory with registration_type="social",
    exercising the fields added in task 1 (registration_type + pending_tenant).
    """
    uid = user_id or str(uuid.uuid4())
    return User.create(
        email=email,
        cognito_sub=cognito_sub or f"social-sub-{uid[:8]}",
        full_name="Social User",
        status=status,
        default_tenant_id=default_tenant_id,
        registration_type="social",
    )


def _make_social_member(tenant_id: str, user_id: str) -> Member:
    """Helper to create a Member entity with registration_type="social"."""
    return Member.reconstitute(
        member_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        account_type="socio",
        account_type_id=str(uuid.uuid4()),
        full_name="Social User",
        email="social@example.com",
        status="active",
        registration_type="social",
        invited_by=None,
        metadata=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _transaction_canceled_error(reason_codes: list[str]) -> ClientError:
    """Build a TransactionCanceledException ClientError.

    Mirrors the shape boto3 produces for a cancelled TransactWriteItems: an
    error Code of "TransactionCanceledException" plus a per-item
    CancellationReasons list ordered to match the request items.
    """
    return ClientError(
        {
            "Error": {
                "Code": "TransactionCanceledException",
                "Message": "Transaction cancelled",
            },
            "CancellationReasons": [{"Code": code} for code in reason_codes],
        },
        "TransactWriteItems",
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


class TestFindByCognitoSub:
    """Tests for DynamoDBUserRepository.find_by_cognito_sub.

    Covers the social-login lookup path (Requirement 3.6 / supports 4.1).
    """

    def test_returns_user_when_scan_matches(self, repo: DynamoDBUserRepository) -> None:
        """Happy path: a scan match reconstitutes and returns the User."""
        user = _make_social_user(
            email="found@example.com", cognito_sub="cognito-sub-abc123"
        )
        repo.save(user)

        result = repo.find_by_cognito_sub("cognito-sub-abc123")

        assert result is not None
        assert result.cognito_sub == "cognito-sub-abc123"
        assert result.email.value == "found@example.com"

    def test_returns_none_when_no_match(self, repo: DynamoDBUserRepository) -> None:
        """Not found: an empty Items list yields None."""
        result = repo.find_by_cognito_sub("nonexistent-sub")

        assert result is None

    def test_scan_uses_cognito_sub_and_profile_filter(
        self, repo: DynamoDBUserRepository
    ) -> None:
        """Verifies the scan filters on cognito_sub and SK=PROFILE.

        Requirements: 4.1 (locate the social user by their Cognito sub).
        """
        mock_table = MagicMock()
        mock_table.scan.return_value = {"Items": []}
        repo._table = mock_table

        result = repo.find_by_cognito_sub("sub-xyz")

        assert result is None
        mock_table.scan.assert_called_once()
        kwargs = mock_table.scan.call_args.kwargs
        assert "cognito_sub = :sub" in kwargs["FilterExpression"]
        assert "SK = :sk" in kwargs["FilterExpression"]
        assert kwargs["ExpressionAttributeValues"] == {
            ":sub": "sub-xyz",
            ":sk": "PROFILE",
        }


class TestRegisterSocialUser:
    """Tests for DynamoDBUserRepository.register_social_user.

    Covers atomic provisioning, idempotency, and error propagation
    (Requirements 4.1, 4.6, 4.7, 9.1, 9.2).
    """

    def test_writes_four_items_with_user_condition_when_tenant_known(
        self, repo: DynamoDBUserRepository
    ) -> None:
        """Happy path (tenant known): 4 items written, User Put is conditional.

        Requirements: 4.1, 4.6 (atomic write of all records when tenant known),
        9.1 (idempotency guard via attribute_not_exists(PK)).
        """
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        user = _make_social_user(
            email="provision@example.com", user_id=user_id, status="active",
            default_tenant_id=tenant_id,
        )
        membership = _make_membership(user_id, tenant_id)
        member = _make_social_member(tenant_id, user_id)
        role = _make_role(user_id, tenant_id, "viewer")

        with patch.object(repo._table.meta, "client") as mock_client:
            repo.register_social_user(user, membership, member, role)

        mock_client.transact_write_items.assert_called_once()
        transact_items = mock_client.transact_write_items.call_args.kwargs[
            "TransactItems"
        ]
        assert len(transact_items) == 4
        user_put = transact_items[0]["Put"]
        assert user_put["ConditionExpression"] == "attribute_not_exists(PK)"
        assert user_put["Item"]["cognito_sub"] == user.cognito_sub

    def test_writes_only_user_item_when_tenant_unknown(
        self, repo: DynamoDBUserRepository
    ) -> None:
        """Happy path (no tenant): only the User item is written.

        Requirements: 4.7 (pending_tenant social user provisioned without a
        tenant association until the user selects one).
        """
        user = _make_social_user(
            email="pending@example.com", status="pending_tenant"
        )

        with patch.object(repo._table.meta, "client") as mock_client:
            repo.register_social_user(user, None, None, None)

        mock_client.transact_write_items.assert_called_once()
        transact_items = mock_client.transact_write_items.call_args.kwargs[
            "TransactItems"
        ]
        assert len(transact_items) == 1
        assert transact_items[0]["Put"]["ConditionExpression"] == (
            "attribute_not_exists(PK)"
        )

    def test_swallows_conditional_check_failure_on_user(
        self, repo: DynamoDBUserRepository
    ) -> None:
        """Idempotency: a ConditionalCheckFailed on the User item is swallowed.

        A repeated callback invocation cancels the transaction because the User
        already exists; the method must return None without raising.

        Requirements: 9.1, 9.2 (idempotent re-invocation is safe).
        """
        user = _make_social_user(email="dupe@example.com", status="pending_tenant")

        with patch.object(repo._table.meta, "client") as mock_client:
            mock_client.transact_write_items.side_effect = (
                _transaction_canceled_error(["ConditionalCheckFailed"])
            )

            # Must not raise.
            result = repo.register_social_user(user, None, None, None)

        assert result is None

    def test_propagates_non_conditional_client_error(
        self, repo: DynamoDBUserRepository
    ) -> None:
        """Error propagation: a non-conditional ClientError is re-raised.

        A transaction cancelled for a reason other than the User's conditional
        check (e.g. a validation error) must not be swallowed.

        Requirements: 4.6 (atomicity — genuine failures surface to the caller).
        """
        user = _make_social_user(email="boom@example.com", status="pending_tenant")

        with patch.object(repo._table.meta, "client") as mock_client:
            mock_client.transact_write_items.side_effect = (
                _transaction_canceled_error(["ValidationError"])
            )

            with pytest.raises(ClientError):
                repo.register_social_user(user, None, None, None)


class TestAssociateTenant:
    """Tests for DynamoDBUserRepository.associate_tenant.

    Covers the atomic tenant-association write and the missing-user guard
    (Requirements 5.3, 9).
    """

    def test_writes_three_puts_and_user_update(
        self, repo: DynamoDBUserRepository
    ) -> None:
        """Happy path: TenantMembership, Member, UserRole Puts + User Update.

        The User Update must set default_tenant_id and status, aliasing the
        reserved word ``status`` via an ExpressionAttributeNames entry.

        Requirements: 5.3 (atomic association of a pending-tenant user).
        """
        tenant_id = str(uuid.uuid4())

        # Persist a pending-tenant user so find_by_id resolves the email.
        # User.create() generates its own user_id, so read it back off the entity.
        existing = _make_social_user(
            email="associate@example.com", status="pending_tenant"
        )
        repo.save(existing)
        user_id = existing.user_id

        membership = _make_membership(user_id, tenant_id)
        member = _make_social_member(tenant_id, user_id)
        role = _make_role(user_id, tenant_id, "viewer")

        # Patch only transact_write_items on the real client so the internal
        # find_by_id scan still resolves the user through moto.
        client = repo._table.meta.client
        with patch.object(client, "transact_write_items") as mock_txn:
            repo.associate_tenant(
                user_id=user_id,
                membership=membership,
                member=member,
                role=role,
                new_status="active",
                new_default_tenant_id=tenant_id,
            )

        mock_txn.assert_called_once()
        transact_items = mock_txn.call_args.kwargs["TransactItems"]
        assert len(transact_items) == 4

        puts = [i for i in transact_items if "Put" in i]
        updates = [i for i in transact_items if "Update" in i]
        assert len(puts) == 3
        assert len(updates) == 1

        update = updates[0]["Update"]
        assert update["Key"] == {
            "PK": "USER#associate@example.com",
            "SK": "PROFILE",
        }
        assert "default_tenant_id = :tid" in update["UpdateExpression"]
        assert "#s = :status" in update["UpdateExpression"]
        assert update["ExpressionAttributeNames"] == {"#s": "status"}
        assert update["ExpressionAttributeValues"] == {
            ":tid": tenant_id,
            ":status": "active",
        }

    def test_raises_value_error_when_user_not_found(
        self, repo: DynamoDBUserRepository
    ) -> None:
        """Error: an unresolvable user_id raises ValueError before any write.

        Requirements: 5.3 (association requires an existing pending-tenant user).
        """
        tenant_id = str(uuid.uuid4())
        missing_id = str(uuid.uuid4())
        membership = _make_membership(missing_id, tenant_id)
        member = _make_social_member(tenant_id, missing_id)
        role = _make_role(missing_id, tenant_id, "viewer")

        with pytest.raises(ValueError):
            repo.associate_tenant(
                user_id=missing_id,
                membership=membership,
                member=member,
                role=role,
                new_status="active",
                new_default_tenant_id=tenant_id,
            )
