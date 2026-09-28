"""Unit tests for the Post Confirmation Lambda handler.

Validates Requirement 3.2: on PostConfirmation_ConfirmSignUp, the handler
creates User + TenantMembership + Member + viewer Role atomically in DynamoDB.

Tests use moto-mocked DynamoDB so repositories use the same mock automatically.
"""

from __future__ import annotations

import uuid
from typing import Any

import boto3
import pytest
from moto import mock_aws


# ──── Constants ───────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
COGNITO_SUB = str(uuid.uuid4())
EMAIL = "test@example.com"
FULL_NAME = "Test User"
ACCOUNT_TYPE = "usuario"
TABLE_NAME = "sport-test"
REGION = "us-east-1"


def _make_event(
    trigger_source: str = "PostConfirmation_ConfirmSignUp",
    tenant_id: str = TENANT_ID,
    account_type: str = ACCOUNT_TYPE,
    sub: str = COGNITO_SUB,
    email: str = EMAIL,
    name: str = FULL_NAME,
) -> dict[str, Any]:
    return {
        "triggerSource": trigger_source,
        "request": {
            "userAttributes": {
                "sub": sub,
                "email": email,
                "name": name,
                "custom:tenant_id": tenant_id,
                "custom:account_type": account_type,
            }
        },
    }


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("REGION", REGION)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    # Required by get_environment_config() when creating repositories in test assertions
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_TestPool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client-id")


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """Reset all module-level singletons before and after each test."""
    import api.registration.postConfirmationHandler as h
    import api.common.config.dynamodbClient as dc

    h._user_repository = None
    h._account_type_repository = None
    dc._dynamodb_resource = None
    dc._table = None
    yield
    h._user_repository = None
    h._account_type_repository = None
    dc._dynamodb_resource = None
    dc._table = None


@pytest.fixture
def dynamodb_table():
    """Moto-backed DynamoDB table — same name as TABLE_NAME env var."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.create_table(
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
                    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                },
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        yield table


# ──── Tests ───────────────────────────────────────────────────────────────────


class TestPostConfirmationHandler:
    """Tests for the post_confirmation_handler.handler function."""

    def test_returns_event_unchanged(self, dynamodb_table: Any) -> None:
        """Handler must always return the event object (Cognito requirement)."""
        import api.registration.postConfirmationHandler as h

        event = _make_event()
        result = h.handler(event, None)

        assert result is event

    def test_creates_user_record(self, dynamodb_table: Any) -> None:
        """User record with status=active should be created in DynamoDB."""
        import api.registration.postConfirmationHandler as h
        from api.common.user.dynamodbUserRepository import DynamoDBUserRepository
        from api.common.valueObjects.email import Email

        h.handler(_make_event(), None)

        user = DynamoDBUserRepository().find_by_email(Email.create(EMAIL))
        assert user is not None
        assert user.status == "active"
        assert user.cognito_sub == COGNITO_SUB
        assert user.default_tenant_id == TENANT_ID

    def test_creates_membership_record(self, dynamodb_table: Any) -> None:
        """TenantMembership record should be created with status=active."""
        import api.registration.postConfirmationHandler as h
        from api.common.user.dynamodbUserRepository import DynamoDBUserRepository
        from api.common.valueObjects.email import Email

        h.handler(_make_event(), None)

        user = DynamoDBUserRepository().find_by_email(Email.create(EMAIL))
        assert user is not None

        response = dynamodb_table.get_item(
            Key={
                "PK": f"TENANT#{TENANT_ID}#USER#{user.user_id}",
                "SK": "MEMBERSHIP",
            }
        )
        item = response.get("Item")
        assert item is not None
        assert item["status"] == "active"
        assert item["tenant_id"] == TENANT_ID

    def test_creates_member_record(self, dynamodb_table: Any) -> None:
        """Member record with registration_type=self and status=active."""
        import api.registration.postConfirmationHandler as h
        from api.common.user.dynamodbUserRepository import DynamoDBUserRepository
        from api.member.dynamodbMemberRepository import DynamoDBMemberRepository
        from api.common.valueObjects.email import Email

        h.handler(_make_event(), None)

        user = DynamoDBUserRepository().find_by_email(Email.create(EMAIL))
        assert user is not None

        member = DynamoDBMemberRepository().find_by_user_in_tenant(
            tenant_id=TENANT_ID,
            user_id=user.user_id,
        )
        assert member is not None
        assert member.status == "active"
        assert member.registration_type == "self"
        assert member.account_type == ACCOUNT_TYPE
        assert member.email == EMAIL

    def test_creates_viewer_role(self, dynamodb_table: Any) -> None:
        """Default viewer role should be assigned to the new user."""
        import api.registration.postConfirmationHandler as h
        from api.common.user.dynamodbUserRepository import DynamoDBUserRepository
        from api.common.valueObjects.email import Email

        h.handler(_make_event(), None)

        user = DynamoDBUserRepository().find_by_email(Email.create(EMAIL))
        assert user is not None

        roles = DynamoDBUserRepository().get_roles_for_tenant(
            user_id=user.user_id,
            tenant_id=TENANT_ID,
        )
        assert len(roles) == 1
        assert roles[0].role_name == "viewer"

    def test_ignores_non_confirm_trigger_sources(self, dynamodb_table: Any) -> None:
        """Handler should skip record creation for non-ConfirmSignUp events."""
        import api.registration.postConfirmationHandler as h
        from api.common.user.dynamodbUserRepository import DynamoDBUserRepository
        from api.common.valueObjects.email import Email

        event = _make_event(trigger_source="PostConfirmation_ConfirmForgotPassword")
        h.handler(event, None)

        user = DynamoDBUserRepository().find_by_email(Email.create(EMAIL))
        assert user is None

    def test_missing_tenant_id_skips_creation(self, dynamodb_table: Any) -> None:
        """Handler should not crash or create records when tenant_id is missing."""
        import api.registration.postConfirmationHandler as h
        from api.common.user.dynamodbUserRepository import DynamoDBUserRepository
        from api.common.valueObjects.email import Email

        event = _make_event(tenant_id="")
        result = h.handler(event, None)

        assert result is event
        user = DynamoDBUserRepository().find_by_email(Email.create(EMAIL))
        assert user is None

    def test_idempotent_on_retry(self, dynamodb_table: Any) -> None:
        """Second invocation with same data should not raise (attribute_not_exists guard)."""
        import api.registration.postConfirmationHandler as h

        # First invocation — creates records
        h.handler(_make_event(), None)

        # Second invocation — handler swallows the ConditionalCheckFailed and logs
        result = h.handler(_make_event(), None)
        assert result is not None

    def test_full_name_falls_back_to_email_prefix_when_name_missing(self, dynamodb_table: Any) -> None:
        """When 'name' attribute is absent, full_name defaults to email prefix."""
        import api.registration.postConfirmationHandler as h
        from api.common.user.dynamodbUserRepository import DynamoDBUserRepository
        from api.common.valueObjects.email import Email

        event: dict[str, Any] = {
            "triggerSource": "PostConfirmation_ConfirmSignUp",
            "request": {
                "userAttributes": {
                    "sub": COGNITO_SUB,
                    "email": EMAIL,
                    # "name" intentionally omitted
                    "custom:tenant_id": TENANT_ID,
                    "custom:account_type": ACCOUNT_TYPE,
                }
            },
        }
        h.handler(event, None)

        user = DynamoDBUserRepository().find_by_email(Email.create(EMAIL))
        assert user is not None
        assert user.full_name.value == EMAIL.split("@")[0]
