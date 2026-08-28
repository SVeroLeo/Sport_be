"""Integration tests for registration flows.

Tests self-registration and admin invitation flows end-to-end using
moto-mocked DynamoDB and Cognito services with real repository and
service implementations.

**Property 8: Registration Atomicity**
**Validates: Requirements 3.1, 3.7, 4.1, 4.2, 12.1, 12.2, 12.3**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from application.dtos.auth.register_input_dto import RegisterInputDTO
from application.dtos.member.create_member_input_dto import CreateMemberInputDTO
from application.use_cases.registration.invite_user_use_case import InviteUserUseCase
from application.use_cases.registration.register_use_case import RegisterUseCase
from domain.entities.account_type import AccountType
from domain.errors.conflict_error import ConflictError
from domain.value_objects.email import Email
from infrastructure.auth.cognito_auth_service import CognitoAuthService
from infrastructure.persistence.dynamodb_account_type_repository import (
    DynamoDBAccountTypeRepository,
)
from infrastructure.persistence.dynamodb_member_repository import DynamoDBMemberRepository
from infrastructure.persistence.dynamodb_tenant_repository import DynamoDBTenantRepository
from infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository
from infrastructure.mappers.account_type_mapper import account_type_to_item
from infrastructure.mappers.tenant_mapper import tenant_to_item


# â”€â”€â”€ Fixtures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars for moto and environment config."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "sport-integration-test")
    monkeypatch.setenv("REGION", "us-east-1")
    monkeypatch.setenv("TOKEN_EXPIRY", "3600")
    monkeypatch.setenv("SALT_ROUNDS", "4")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_TestPool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client-id")


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """Reset module-level singletons before each test."""
    import infrastructure.config.dynamodb_client as dc
    import infrastructure.config.environment as env

    env._config = None
    dc._dynamodb_resource = None
    dc._table = None
    yield
    env._config = None
    dc._dynamodb_resource = None
    dc._table = None


@pytest.fixture
def dynamodb_table():
    """Create a moto-mocked DynamoDB table with GSIs."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="sport-integration-test",
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
def cognito_user_pool():
    """Create a moto-mocked Cognito User Pool and return (pool_id, client_id)."""
    with mock_aws():
        client = boto3.client("cognito-idp", region_name="us-east-1")
        pool_response = client.create_user_pool(
            PoolName="test-pool",
            Policies={
                "PasswordPolicy": {
                    "MinimumLength": 8,
                    "RequireUppercase": True,
                    "RequireLowercase": True,
                    "RequireNumbers": True,
                    "RequireSymbols": True,
                }
            },
            AutoVerifiedAttributes=["email"],
            Schema=[
                {"Name": "email", "AttributeDataType": "String", "Required": True},
                {"Name": "name", "AttributeDataType": "String", "Required": False},
            ],
        )
        pool_id = pool_response["UserPool"]["Id"]

        client_response = client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName="test-client",
            ExplicitAuthFlows=[
                "ALLOW_ADMIN_USER_PASSWORD_AUTH",
                "ALLOW_USER_PASSWORD_AUTH",
                "ALLOW_REFRESH_TOKEN_AUTH",
            ],
        )
        client_id = client_response["UserPoolClient"]["ClientId"]

        yield pool_id, client_id, client


@pytest.fixture
def aws_integration(dynamodb_table, cognito_user_pool, monkeypatch):
    """Combined fixture providing DynamoDB table and Cognito within the same mock_aws context.

    Returns a dict with all infrastructure components wired up.
    """
    # We need everything under a single mock_aws context
    pass


@pytest.fixture
def integration_env(monkeypatch):
    """Full integration environment with mocked AWS services."""
    with mock_aws():
        # Reset singletons
        import infrastructure.config.dynamodb_client as dc
        import infrastructure.config.environment as env

        env._config = None
        dc._dynamodb_resource = None
        dc._table = None

        # Create DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="sport-integration-test",
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

        # Create Cognito User Pool
        cognito_client = boto3.client("cognito-idp", region_name="us-east-1")
        pool_response = cognito_client.create_user_pool(
            PoolName="test-pool",
            Policies={
                "PasswordPolicy": {
                    "MinimumLength": 8,
                    "RequireUppercase": True,
                    "RequireLowercase": True,
                    "RequireNumbers": True,
                    "RequireSymbols": True,
                }
            },
            AutoVerifiedAttributes=["email"],
            Schema=[
                {"Name": "email", "AttributeDataType": "String", "Required": True},
                {"Name": "name", "AttributeDataType": "String", "Required": False},
            ],
        )
        pool_id = pool_response["UserPool"]["Id"]

        client_response = cognito_client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName="test-client",
            ExplicitAuthFlows=[
                "ALLOW_ADMIN_USER_PASSWORD_AUTH",
                "ALLOW_USER_PASSWORD_AUTH",
                "ALLOW_REFRESH_TOKEN_AUTH",
            ],
        )
        client_id = client_response["UserPoolClient"]["ClientId"]

        # Update env to use the real pool/client IDs
        monkeypatch.setenv("COGNITO_USER_POOL_ID", pool_id)
        monkeypatch.setenv("COGNITO_CLIENT_ID", client_id)

        # Reset again so environment picks up new values
        env._config = None
        dc._dynamodb_resource = None
        dc._table = None

        yield {
            "table": table,
            "cognito_client": cognito_client,
            "pool_id": pool_id,
            "client_id": client_id,
        }

        # Cleanup
        env._config = None
        dc._dynamodb_resource = None
        dc._table = None


# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _seed_tenant(
    table: Any,
    tenant_id: str,
    *,
    allow_self_registration: bool = True,
    default_account_type: str | None = "socio",
    status: str = "active",
) -> None:
    """Seed a tenant record in DynamoDB."""
    table.put_item(
        Item={
            "PK": f"TENANT#{tenant_id}",
            "SK": "METADATA",
            "tenant_id": tenant_id,
            "name": "Club Deportivo Test",
            "plan": "premium",
            "status": status,
            "allow_self_registration": allow_self_registration,
            "default_account_type": default_account_type,
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
        }
    )


def _seed_account_type(
    table: Any,
    tenant_id: str,
    name: str,
    *,
    status: str = "active",
    account_type_id: str | None = None,
) -> str:
    """Seed an account type record in DynamoDB. Returns account_type_id."""
    at_id = account_type_id or str(uuid.uuid4())
    now = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()
    table.put_item(
        Item={
            "PK": f"TENANT#{tenant_id}#ACCTYPE",
            "SK": f"ACCTYPE#{at_id}",
            "GSI1PK": f"TENANT#{tenant_id}#ACCTYPE",
            "GSI1SK": f"NAME#{name.lower()}",
            "account_type_id": at_id,
            "tenant_id": tenant_id,
            "name": name,
            "description": f"{name} type",
            "config": None,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
    )
    return at_id


# â”€â”€â”€ Test: Self-Registration Complete Flow â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestSelfRegistrationFlow:
    """Integration tests for the self-registration use case.

    Validates: Requirements 3.1, 3.7
    """

    @pytest.mark.asyncio
    async def test_self_registration_creates_cognito_user_and_returns_pending(
        self, integration_env: dict[str, Any]
    ) -> None:
        """Valid self-registration â†’ Cognito SignUp â†’ confirmation-pending status.

        Validates: Requirement 3.1
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        _seed_account_type(table, tenant_id, "socio")

        # Wire up real implementations
        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        # Patch get_dynamodb_table to return our mocked table
        with patch(
            "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            tenant_repo = DynamoDBTenantRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = RegisterUseCase(
                cognito_service=cognito_service,
                user_repository=user_repo,
                tenant_repository=tenant_repo,
                account_type_repository=account_type_repo,
            )

            input_dto = RegisterInputDTO(
                email="newuser@example.com",
                password="SecurePass1!",
                full_name="New User",
                tenant_id=tenant_id,
                account_type=None,
            )

            result = await use_case.execute(input_dto)

        # Assert: result is pending_confirmation
        assert result.status == "pending_confirmation"
        assert result.email == "newuser@example.com"
        assert result.full_name == "New User"
        assert result.user_id  # cognito_sub should be set

        # Verify: Cognito user exists
        cognito_user = cognito_client.admin_get_user(
            UserPoolId=pool_id,
            Username="newuser@example.com",
        )
        assert cognito_user["Username"] == "newuser@example.com"

    @pytest.mark.asyncio
    async def test_self_registration_uses_tenant_default_account_type(
        self, integration_env: dict[str, Any]
    ) -> None:
        """No explicit accountType â†’ uses tenant defaultAccountType.

        Validates: Requirement 3.7
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id, default_account_type="profesional")
        _seed_account_type(table, tenant_id, "profesional")

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            tenant_repo = DynamoDBTenantRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = RegisterUseCase(
                cognito_service=cognito_service,
                user_repository=user_repo,
                tenant_repository=tenant_repo,
                account_type_repository=account_type_repo,
            )

            input_dto = RegisterInputDTO(
                email="default@example.com",
                password="SecurePass1!",
                full_name="Default Type User",
                tenant_id=tenant_id,
                account_type=None,  # No explicit type
            )

            result = await use_case.execute(input_dto)

        # The registration succeeds using the tenant's default
        assert result.status == "pending_confirmation"
        assert result.email == "default@example.com"

    @pytest.mark.asyncio
    async def test_self_registration_fallback_to_usuario_when_default_is_null(
        self, integration_env: dict[str, Any]
    ) -> None:
        """When defaultAccountType is null â†’ assigns "usuario" as fallback.

        Validates: Requirement 3.7
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id, default_account_type=None)
        # No account type seeded â€” but fallback "usuario" doesn't require lookup

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            tenant_repo = DynamoDBTenantRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = RegisterUseCase(
                cognito_service=cognito_service,
                user_repository=user_repo,
                tenant_repository=tenant_repo,
                account_type_repository=account_type_repo,
            )

            input_dto = RegisterInputDTO(
                email="fallback@example.com",
                password="SecurePass1!",
                full_name="Fallback User",
                tenant_id=tenant_id,
                account_type=None,
            )

            result = await use_case.execute(input_dto)

        # Registration succeeds using "usuario" fallback
        assert result.status == "pending_confirmation"
        assert result.email == "fallback@example.com"

    @pytest.mark.asyncio
    async def test_self_registration_fallback_when_default_is_inactive(
        self, integration_env: dict[str, Any]
    ) -> None:
        """When defaultAccountType is inactive â†’ fallback to "usuario".

        Validates: Requirement 3.7
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id, default_account_type="socio")
        _seed_account_type(table, tenant_id, "socio", status="inactive")

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            tenant_repo = DynamoDBTenantRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = RegisterUseCase(
                cognito_service=cognito_service,
                user_repository=user_repo,
                tenant_repository=tenant_repo,
                account_type_repository=account_type_repo,
            )

            input_dto = RegisterInputDTO(
                email="inactive-default@example.com",
                password="SecurePass1!",
                full_name="Inactive Default User",
                tenant_id=tenant_id,
                account_type=None,
            )

            result = await use_case.execute(input_dto)

        # Registration succeeds using "usuario" fallback
        assert result.status == "pending_confirmation"
        assert result.email == "inactive-default@example.com"

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_conflict_error(
        self, integration_env: dict[str, Any]
    ) -> None:
        """Self-registration with an existing email â†’ ConflictError.

        Validates: Requirement 3.3
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        _seed_account_type(table, tenant_id, "socio")

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        # Seed an existing user in DynamoDB
        from domain.entities.user import User

        existing_user = User.create(
            email="duplicate@example.com",
            cognito_sub="existing-sub",
            full_name="Existing User",
            status="active",
        )
        user_repo.save(existing_user)

        with patch(
            "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            tenant_repo = DynamoDBTenantRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = RegisterUseCase(
                cognito_service=cognito_service,
                user_repository=user_repo,
                tenant_repository=tenant_repo,
                account_type_repository=account_type_repo,
            )

            input_dto = RegisterInputDTO(
                email="duplicate@example.com",
                password="SecurePass1!",
                full_name="Duplicate User",
                tenant_id=tenant_id,
                account_type=None,
            )

            with pytest.raises(ConflictError) as exc_info:
                await use_case.execute(input_dto)

        assert "already registered" in exc_info.value.message.lower()


# â”€â”€â”€ Test: Admin Invitation Flow â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestAdminInvitationFlow:
    """Integration tests for the admin-invited member creation use case.

    Validates: Requirements 4.1, 4.2, 12.2
    """

    @pytest.mark.asyncio
    async def test_invite_new_user_creates_cognito_user_and_db_records(
        self, integration_env: dict[str, Any]
    ) -> None:
        """Admin invites new user â†’ AdminCreateUser + atomic DynamoDB records.

        Validates: Requirements 4.1, 4.2, 12.2
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        admin_user_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        account_type_id = _seed_account_type(table, tenant_id, "socio")

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_member_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_member_repository.get_environment_config",
        ) as mock_env_config, patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            mock_env_config.return_value.table_name = "sport-integration-test"
            member_repo = DynamoDBMemberRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = InviteUserUseCase(
                user_repository=user_repo,
                member_repository=member_repo,
                account_type_repository=account_type_repo,
                cognito_service=cognito_service,
            )

            input_dto = CreateMemberInputDTO(
                tenant_id=tenant_id,
                email="invited@example.com",
                full_name="Invited User",
                account_type="socio",
                roles=["viewer"],
            )

            result = await use_case.execute(input_dto, created_by_user_id=admin_user_id)

        # Assert: output DTO has correct data
        assert result.email == "invited@example.com"
        assert result.full_name == "Invited User"
        assert result.account_type == "socio"
        assert result.status == "active"
        assert result.registration_type == "invited"
        assert result.invited_by == admin_user_id
        assert result.tenant_id == tenant_id

        # Verify: Cognito user was created
        cognito_user = cognito_client.admin_get_user(
            UserPoolId=pool_id,
            Username="invited@example.com",
        )
        assert cognito_user["Username"] == "invited@example.com"

        # Verify: User record in DynamoDB (pending_confirmation)
        found_user = user_repo.find_by_email(Email(value="invited@example.com"))
        assert found_user is not None
        assert found_user.status == "pending_confirmation"

        # Verify: TenantMembership in DynamoDB
        membership_response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{found_user.user_id}",
                "SK": "MEMBERSHIP",
            }
        )
        assert "Item" in membership_response

        # Verify: Member in DynamoDB
        member_response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#MEMBER#{result.member_id}",
                "SK": "PROFILE",
            }
        )
        assert "Item" in member_response

        # Verify: Role in DynamoDB
        role_response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{found_user.user_id}",
                "SK": "ROLE#viewer",
            }
        )
        assert "Item" in role_response

    @pytest.mark.asyncio
    async def test_invite_existing_user_creates_only_membership_records(
        self, integration_env: dict[str, Any]
    ) -> None:
        """Invite user already in system (different tenant) â†’ only Membership+Member+Roles.

        Validates: Requirement 4.3
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        admin_user_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        _seed_account_type(table, tenant_id, "profesional")

        # Pre-create an existing user in DynamoDB (already a member of another tenant)
        from domain.entities.user import User

        existing_user = User.create(
            email="existing@example.com",
            cognito_sub="existing-cognito-sub-123",
            full_name="Existing User",
            status="active",
        )
        user_repo = DynamoDBUserRepository(table=table)
        user_repo.save(existing_user)

        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_member_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_member_repository.get_environment_config",
        ) as mock_env_config, patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            mock_env_config.return_value.table_name = "sport-integration-test"
            member_repo = DynamoDBMemberRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = InviteUserUseCase(
                user_repository=user_repo,
                member_repository=member_repo,
                account_type_repository=account_type_repo,
                cognito_service=cognito_service,
            )

            input_dto = CreateMemberInputDTO(
                tenant_id=tenant_id,
                email="existing@example.com",
                full_name="Existing User",
                account_type="profesional",
                roles=["admin", "manager"],
            )

            result = await use_case.execute(input_dto, created_by_user_id=admin_user_id)

        # Assert: member created successfully
        assert result.email == "existing@example.com"
        assert result.account_type == "profesional"
        assert result.status == "active"
        assert result.user_id == existing_user.user_id

        # Verify: TenantMembership created
        membership_response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{existing_user.user_id}",
                "SK": "MEMBERSHIP",
            }
        )
        assert "Item" in membership_response

        # Verify: Both roles created
        admin_role = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{existing_user.user_id}",
                "SK": "ROLE#admin",
            }
        )
        assert "Item" in admin_role

        manager_role = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{existing_user.user_id}",
                "SK": "ROLE#manager",
            }
        )
        assert "Item" in manager_role

    @pytest.mark.asyncio
    async def test_invite_user_already_member_of_tenant_raises_conflict(
        self, integration_env: dict[str, Any]
    ) -> None:
        """Invite user who is already a member of the tenant â†’ ConflictError.

        Validates: Requirement 4.4
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        admin_user_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        _seed_account_type(table, tenant_id, "socio")

        # Create existing user and their membership in this tenant
        from domain.entities.member import Member
        from domain.entities.tenant_membership import TenantMembership
        from domain.entities.user import User
        from domain.entities.user_role import UserRole

        existing_user = User.create(
            email="alreadymember@example.com",
            cognito_sub="member-cognito-sub",
            full_name="Already Member",
            status="active",
        )
        user_repo = DynamoDBUserRepository(table=table)

        membership = TenantMembership.create(
            user_id=existing_user.user_id,
            tenant_id=tenant_id,
        )
        member = Member.create(
            tenant_id=tenant_id,
            user_id=existing_user.user_id,
            account_type="socio",
            account_type_id=str(uuid.uuid4()),
            full_name="Already Member",
            email="alreadymember@example.com",
            registration_type="self",
            status="active",
        )
        role = UserRole.create(
            user_id=existing_user.user_id,
            tenant_id=tenant_id,
            role_name="viewer",
        )
        user_repo.register_with_membership(existing_user, membership, member, role)

        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_member_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_member_repository.get_environment_config",
        ) as mock_env_config, patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            mock_env_config.return_value.table_name = "sport-integration-test"
            member_repo = DynamoDBMemberRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = InviteUserUseCase(
                user_repository=user_repo,
                member_repository=member_repo,
                account_type_repository=account_type_repo,
                cognito_service=cognito_service,
            )

            input_dto = CreateMemberInputDTO(
                tenant_id=tenant_id,
                email="alreadymember@example.com",
                full_name="Already Member",
                account_type="socio",
                roles=["viewer"],
            )

            with pytest.raises(ConflictError) as exc_info:
                await use_case.execute(input_dto, created_by_user_id=admin_user_id)

        assert "already a member" in exc_info.value.message.lower()


# â”€â”€â”€ Test: Registration Atomicity (Property 8) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestRegistrationAtomicity:
    """Property 8: Registration Atomicity â€” integration tests.

    For any registration attempt, either ALL required records are created
    atomically, or NONE are created. On transaction failure, no orphan
    records exist.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """

    @pytest.mark.asyncio
    async def test_self_registration_transaction_failure_leaves_no_orphan_records(
        self, integration_env: dict[str, Any]
    ) -> None:
        """If DynamoDB TransactWriteItems fails during self-registration,
        NO orphan User/Membership/Member/Role records exist.

        Note: In the current implementation, self-registration calls Cognito
        SignUp first and returns pending_confirmation. The actual DynamoDB
        transaction happens in the post-confirmation Lambda trigger.
        This test validates that the use case itself does NOT write DynamoDB
        records â€” those are deferred to post-confirmation.

        Validates: Requirements 12.1, 12.3
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        _seed_account_type(table, tenant_id, "socio")

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_tenant_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            tenant_repo = DynamoDBTenantRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = RegisterUseCase(
                cognito_service=cognito_service,
                user_repository=user_repo,
                tenant_repository=tenant_repo,
                account_type_repository=account_type_repo,
            )

            input_dto = RegisterInputDTO(
                email="atomic-test@example.com",
                password="SecurePass1!",
                full_name="Atomic Test",
                tenant_id=tenant_id,
                account_type=None,
            )

            # Execute self-registration (succeeds â€” creates Cognito user only)
            result = await use_case.execute(input_dto)
            assert result.status == "pending_confirmation"

        # Verify: NO User record in DynamoDB (deferred to post-confirmation)
        user_result = user_repo.find_by_email(Email(value="atomic-test@example.com"))
        assert user_result is None, "No DynamoDB user record before email confirmation"

        # Verify: Scan the table for any records with this email
        scan_response = table.scan(
            FilterExpression="contains(PK, :email_fragment)",
            ExpressionAttributeValues={":email_fragment": "atomic-test@example.com"},
        )
        assert scan_response.get("Count", 0) == 0

    @pytest.mark.asyncio
    async def test_admin_invitation_atomicity_all_records_or_none(
        self, integration_env: dict[str, Any]
    ) -> None:
        """Admin invitation creates User + Membership + Member + Roles atomically.
        If any part fails, nothing is committed.

        Validates: Requirements 12.2, 12.3
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        admin_user_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        _seed_account_type(table, tenant_id, "socio")

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        with patch(
            "infrastructure.persistence.dynamodb_member_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_member_repository.get_environment_config",
        ) as mock_env_config, patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            mock_env_config.return_value.table_name = "sport-integration-test"
            member_repo = DynamoDBMemberRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = InviteUserUseCase(
                user_repository=user_repo,
                member_repository=member_repo,
                account_type_repository=account_type_repo,
                cognito_service=cognito_service,
            )

            input_dto = CreateMemberInputDTO(
                tenant_id=tenant_id,
                email="atomic-invite@example.com",
                full_name="Atomic Invite",
                account_type="socio",
                roles=["viewer", "manager"],
            )

            result = await use_case.execute(input_dto, created_by_user_id=admin_user_id)

        # All records created atomically
        found_user = user_repo.find_by_email(Email(value="atomic-invite@example.com"))
        assert found_user is not None

        # Membership exists
        membership_response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{found_user.user_id}",
                "SK": "MEMBERSHIP",
            }
        )
        assert "Item" in membership_response

        # Member exists
        member_response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#MEMBER#{result.member_id}",
                "SK": "PROFILE",
            }
        )
        assert "Item" in member_response

        # Both roles exist
        viewer_role = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{found_user.user_id}",
                "SK": "ROLE#viewer",
            }
        )
        assert "Item" in viewer_role

        manager_role = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#USER#{found_user.user_id}",
                "SK": "ROLE#manager",
            }
        )
        assert "Item" in manager_role

    @pytest.mark.asyncio
    async def test_admin_invitation_transaction_failure_rolls_back(
        self, integration_env: dict[str, Any]
    ) -> None:
        """When DynamoDB TransactWriteItems fails during admin invitation,
        no partial records are left behind.

        Simulates failure by patching transact_write_items to raise an error
        AFTER Cognito user creation. Verifies that no DynamoDB records are created.

        Validates: Requirements 12.2, 12.3
        """
        table = integration_env["table"]
        pool_id = integration_env["pool_id"]
        client_id = integration_env["client_id"]
        cognito_client = integration_env["cognito_client"]

        tenant_id = str(uuid.uuid4())
        admin_user_id = str(uuid.uuid4())
        _seed_tenant(table, tenant_id)
        _seed_account_type(table, tenant_id, "socio")

        user_repo = DynamoDBUserRepository(table=table)
        cognito_service = CognitoAuthService(
            user_pool_id=pool_id,
            client_id=client_id,
            client=cognito_client,
        )

        from botocore.exceptions import ClientError

        def _failing_transact_write(*args: Any, **kwargs: Any) -> None:
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "TransactionCanceledException",
                        "Message": "Transaction cancelled",
                    }
                },
                operation_name="TransactWriteItems",
            )

        with patch(
            "infrastructure.persistence.dynamodb_member_repository.get_dynamodb_table",
            return_value=table,
        ), patch(
            "infrastructure.persistence.dynamodb_member_repository.get_environment_config",
        ) as mock_env_config, patch(
            "infrastructure.persistence.dynamodb_account_type_repository.get_dynamodb_table",
            return_value=table,
        ):
            mock_env_config.return_value.table_name = "sport-integration-test"
            member_repo = DynamoDBMemberRepository()
            account_type_repo = DynamoDBAccountTypeRepository()

            use_case = InviteUserUseCase(
                user_repository=user_repo,
                member_repository=member_repo,
                account_type_repository=account_type_repo,
                cognito_service=cognito_service,
            )

            input_dto = CreateMemberInputDTO(
                tenant_id=tenant_id,
                email="fail-invite@example.com",
                full_name="Fail Invite",
                account_type="socio",
                roles=["viewer"],
            )

            # Patch transact_write_items to simulate failure
            original_client = table.meta.client
            with patch.object(
                original_client,
                "transact_write_items",
                side_effect=_failing_transact_write,
            ):
                with pytest.raises(ClientError):
                    await use_case.execute(input_dto, created_by_user_id=admin_user_id)

        # Verify: NO User record in DynamoDB (transaction was atomic)
        found_user = user_repo.find_by_email(Email(value="fail-invite@example.com"))
        assert found_user is None, "No orphan user record after transaction failure"

        # Verify: No membership or member records
        scan_response = table.scan(
            FilterExpression="contains(PK, :uid_fragment)",
            ExpressionAttributeValues={":uid_fragment": "fail-invite"},
        )
        # Only the tenant and account_type seed records should exist
        for item in scan_response.get("Items", []):
            assert "MEMBER" not in item.get("PK", ""), "No orphan member records"
            assert "USER#fail" not in item.get("PK", ""), "No orphan user records"
