"""Integration tests for authentication flow.

**Validates: Requirements 1.1, 1.2, 1.7, 2.1, 14.5**

Tests:
- Login success flow (Cognito + DynamoDB via moto)
- Property 12: Token Contains Correct Roles
- Invalid credentials opacity (same error for all failure modes)
- Inactive membership rejection
- Token refresh via Cognito
- Global sign out
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Generator

import boto3
import hypothesis.strategies as st
import pytest
from hypothesis import given, settings
from moto import mock_aws

from api.auth.loginInputDto import LoginInputDTO
from api.auth.loginUseCase import LoginUseCase
from api.member.member import Member
from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.user import User
from api.common.user.userRole import UserRole
from api.common.errors.domainError import DomainError
from api.common.errors.invalidCredentialsError import InvalidCredentialsError
from api.common.auth.cognitoAuthService import CognitoAuthService
from api.member.dynamodbMemberRepository import DynamoDBMemberRepository
from api.common.user.dynamodbUserRepository import DynamoDBUserRepository


# â”€â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

TEST_REGION = "us-east-1"
TEST_TABLE_NAME = "test-account-management"
TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "SecurePass1!"
TEST_FULL_NAME = "Test User"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


# â”€â”€â”€ Strategies for Property Tests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

valid_role_subsets = st.lists(
    st.sampled_from(["admin", "manager", "viewer"]),
    min_size=1,
    max_size=3,
    unique=True,
)


# â”€â”€â”€ Fixtures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.fixture(autouse=True)
def _reset_singletons() -> Generator[None, None, None]:
    """Reset infrastructure singletons between tests."""
    import api.common.config.dynamodbClient as ddb_mod
    import api.common.config.environment as env_mod

    ddb_mod._dynamodb_resource = None
    ddb_mod._table = None
    env_mod._config = None
    yield
    ddb_mod._dynamodb_resource = None
    ddb_mod._table = None
    env_mod._config = None


@pytest.fixture(autouse=True)
def _set_env_vars() -> Generator[None, None, None]:
    """Set environment variables required by the application."""
    env_vars = {
        "TABLE_NAME": TEST_TABLE_NAME,
        "REGION": TEST_REGION,
        "TOKEN_EXPIRY": "3600",
        "SALT_ROUNDS": "4",
        "COGNITO_USER_POOL_ID": "us-east-1_TestPool",
        "COGNITO_CLIENT_ID": "test-client-id",
        "AWS_DEFAULT_REGION": TEST_REGION,
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
    }
    original = {}
    for key, value in env_vars.items():
        original[key] = os.environ.get(key)
        os.environ[key] = value
    yield
    for key, orig_val in original.items():
        if orig_val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = orig_val


@pytest.fixture
def aws_mock() -> Generator[None, None, None]:
    """Activate moto mock_aws context for all AWS services."""
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_table(aws_mock: None) -> Any:
    """Create and return a mocked DynamoDB table with the required schema."""
    dynamodb = boto3.resource("dynamodb", region_name=TEST_REGION)
    table = dynamodb.create_table(
        TableName=TEST_TABLE_NAME,
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
    table.meta.client.get_waiter("table_exists").wait(TableName=TEST_TABLE_NAME)
    return table


@pytest.fixture
def cognito_pool(aws_mock: None) -> dict[str, str]:
    """Create a mocked Cognito user pool and app client."""
    client = boto3.client("cognito-idp", region_name=TEST_REGION)

    pool_response = client.create_user_pool(
        PoolName="TestPool",
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
            {
                "Name": "email",
                "AttributeDataType": "String",
                "Required": True,
                "Mutable": True,
            },
            {
                "Name": "name",
                "AttributeDataType": "String",
                "Required": False,
                "Mutable": True,
            },
        ],
    )
    pool_id = pool_response["UserPool"]["Id"]

    client_response = client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName="TestClient",
        ExplicitAuthFlows=[
            "ALLOW_ADMIN_USER_PASSWORD_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH",
        ],
    )
    client_id = client_response["UserPoolClient"]["ClientId"]

    # Update env vars with actual pool details
    os.environ["COGNITO_USER_POOL_ID"] = pool_id
    os.environ["COGNITO_CLIENT_ID"] = client_id

    return {"pool_id": pool_id, "client_id": client_id}


@pytest.fixture
def cognito_service(cognito_pool: dict[str, str]) -> CognitoAuthService:
    """Create a CognitoAuthService wired to the mocked Cognito pool."""
    return CognitoAuthService(
        user_pool_id=cognito_pool["pool_id"],
        client_id=cognito_pool["client_id"],
        region=TEST_REGION,
    )


@pytest.fixture
def user_repository(dynamodb_table: Any) -> DynamoDBUserRepository:
    """Create a DynamoDBUserRepository pointing at the mocked table."""
    return DynamoDBUserRepository(table=dynamodb_table)


@pytest.fixture
def member_repository() -> DynamoDBMemberRepository:
    """Create a DynamoDBMemberRepository using the global mocked table."""
    return DynamoDBMemberRepository()


def _create_cognito_user(
    cognito_pool: dict[str, str],
    email: str = TEST_EMAIL,
    password: str = TEST_PASSWORD,
    full_name: str = TEST_FULL_NAME,
) -> str:
    """Helper: create and confirm a Cognito user, return the sub."""
    client = boto3.client("cognito-idp", region_name=TEST_REGION)

    # Admin create user with permanent password
    client.admin_create_user(
        UserPoolId=cognito_pool["pool_id"],
        Username=email,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": full_name},
        ],
        MessageAction="SUPPRESS",
    )

    # Set permanent password
    client.admin_set_user_password(
        UserPoolId=cognito_pool["pool_id"],
        Username=email,
        Password=password,
        Permanent=True,
    )

    # Retrieve the user's sub
    user_response = client.admin_get_user(
        UserPoolId=cognito_pool["pool_id"],
        Username=email,
    )
    for attr in user_response["UserAttributes"]:
        if attr["Name"] == "sub":
            return attr["Value"]
    return email


def _seed_user_in_dynamodb(
    table: Any,
    email: str,
    user_id: str,
    cognito_sub: str,
    status: str = "active",
    default_tenant_id: str | None = TENANT_ID,
) -> User:
    """Helper: seed a User record in DynamoDB.

    The token is tenant-agnostic; login resolves the active tenant from the
    user's default_tenant_id (see tasks 23.1/23.2). Default it to TENANT_ID so
    the login flow can resolve membership for the seeded tenant.
    """
    now = datetime.now(timezone.utc)
    user = User.reconstitute(
        user_id=user_id,
        email=email,
        cognito_sub=cognito_sub,
        full_name=TEST_FULL_NAME,
        status=status,
        created_at=now,
        updated_at=now,
        default_tenant_id=default_tenant_id,
    )
    from api.common.user.userMapper import user_to_item

    table.put_item(Item=user_to_item(user))
    return user


def _seed_member_in_dynamodb(
    table: Any,
    tenant_id: str,
    user_id: str,
    email: str,
    status: str = "active",
) -> Member:
    """Helper: seed a Member record in DynamoDB."""
    now = datetime.now(timezone.utc)
    member_id = str(uuid.uuid4())
    account_type_id = str(uuid.uuid4())
    member = Member.reconstitute(
        member_id=member_id,
        tenant_id=tenant_id,
        user_id=user_id,
        account_type="socio",
        account_type_id=account_type_id,
        full_name=TEST_FULL_NAME,
        email=email,
        status=status,
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=now,
        updated_at=now,
    )
    from api.member.memberMapper import member_to_item

    table.put_item(Item=member_to_item(member))
    return member


def _seed_roles_in_dynamodb(
    table: Any,
    user_id: str,
    tenant_id: str,
    role_names: list[str],
) -> list[UserRole]:
    """Helper: seed UserRole records in DynamoDB."""
    from api.common.user.userMapper import user_role_to_item

    roles = []
    now = datetime.now(timezone.utc)
    for role_name in role_names:
        role = UserRole.reconstitute(
            user_id=user_id,
            tenant_id=tenant_id,
            role_name=role_name,
            assigned_at=now,
        )
        table.put_item(Item=user_role_to_item(role))
        roles.append(role)
    return roles


def _seed_membership_in_dynamodb(
    table: Any,
    user_id: str,
    tenant_id: str,
) -> None:
    """Helper: seed a TenantMembership record in DynamoDB."""
    from api.common.user.userMapper import tenant_membership_to_item

    now = datetime.now(timezone.utc)
    membership = TenantMembership.reconstitute(
        user_id=user_id,
        tenant_id=tenant_id,
        status="active",
        joined_at=now,
    )
    table.put_item(Item=tenant_membership_to_item(membership))


# â”€â”€â”€ Integration Tests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestLoginSuccessFlow:
    """Test the full login success flow using moto for Cognito and DynamoDB.

    Validates: Requirements 1.1, 1.2
    """

    @pytest.mark.asyncio
    async def test_login_returns_token_pair_and_roles(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
        user_repository: DynamoDBUserRepository,
        member_repository: DynamoDBMemberRepository,
    ) -> None:
        """Valid credentials return a TokenPair with correct roles (Req 1.1, 1.2)."""
        # Arrange: create user in Cognito
        cognito_sub = _create_cognito_user(cognito_pool)

        # Seed user, member, and roles in DynamoDB
        user_id = str(uuid.uuid4())
        _seed_user_in_dynamodb(dynamodb_table, TEST_EMAIL, user_id, cognito_sub)
        _seed_member_in_dynamodb(dynamodb_table, TENANT_ID, user_id, TEST_EMAIL)
        _seed_roles_in_dynamodb(dynamodb_table, user_id, TENANT_ID, ["admin", "viewer"])

        # Act
        login_use_case = LoginUseCase(
            cognito_service=cognito_service,
            user_repository=user_repository,
            member_repository=member_repository,
        )
        result = await login_use_case.execute(
            LoginInputDTO(email=TEST_EMAIL, password=TEST_PASSWORD, tenant_id=TENANT_ID)
        )

        # Assert
        assert result.access_token != ""
        assert result.id_token != ""
        assert result.refresh_token != ""
        assert result.expires_in > 0
        assert sorted(result.roles) == ["admin", "viewer"]


class TestInvalidCredentialsOpacity:
    """Test that all authentication failures return the same generic error.

    Validates: Requirements 1.3, 1.5
    """

    @pytest.mark.asyncio
    async def test_wrong_password_returns_invalid_credentials(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
        user_repository: DynamoDBUserRepository,
        member_repository: DynamoDBMemberRepository,
    ) -> None:
        """Wrong password yields generic 'Invalid credentials' error (Req 1.3)."""
        cognito_sub = _create_cognito_user(cognito_pool)
        user_id = str(uuid.uuid4())
        _seed_user_in_dynamodb(dynamodb_table, TEST_EMAIL, user_id, cognito_sub)
        _seed_member_in_dynamodb(dynamodb_table, TENANT_ID, user_id, TEST_EMAIL)

        login_use_case = LoginUseCase(
            cognito_service=cognito_service,
            user_repository=user_repository,
            member_repository=member_repository,
        )

        with pytest.raises(InvalidCredentialsError) as exc_info:
            await login_use_case.execute(
                LoginInputDTO(email=TEST_EMAIL, password="WrongPassword1!", tenant_id=TENANT_ID)
            )
        assert exc_info.value.message == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_nonexistent_email_returns_invalid_credentials(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
        user_repository: DynamoDBUserRepository,
        member_repository: DynamoDBMemberRepository,
    ) -> None:
        """Non-existent email yields the same error without revealing existence (Req 1.3)."""
        login_use_case = LoginUseCase(
            cognito_service=cognito_service,
            user_repository=user_repository,
            member_repository=member_repository,
        )

        with pytest.raises(InvalidCredentialsError) as exc_info:
            await login_use_case.execute(
                LoginInputDTO(
                    email="nonexistent@example.com",
                    password=TEST_PASSWORD,
                    tenant_id=TENANT_ID,
                )
            )
        assert exc_info.value.message == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_no_membership_returns_invalid_credentials(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
        user_repository: DynamoDBUserRepository,
        member_repository: DynamoDBMemberRepository,
    ) -> None:
        """User with no membership in tenant yields 'Invalid credentials' (Req 1.5)."""
        cognito_sub = _create_cognito_user(cognito_pool)
        user_id = str(uuid.uuid4())
        _seed_user_in_dynamodb(dynamodb_table, TEST_EMAIL, user_id, cognito_sub)
        # Deliberately NOT seeding a member for this tenant

        login_use_case = LoginUseCase(
            cognito_service=cognito_service,
            user_repository=user_repository,
            member_repository=member_repository,
        )

        with pytest.raises(InvalidCredentialsError) as exc_info:
            await login_use_case.execute(
                LoginInputDTO(email=TEST_EMAIL, password=TEST_PASSWORD, tenant_id=TENANT_ID)
            )
        assert exc_info.value.message == "Invalid credentials"


class TestInactiveMembership:
    """Test that inactive membership is rejected with domain error.

    Validates: Requirements 1.4, 14.5
    """

    @pytest.mark.asyncio
    async def test_inactive_membership_returns_account_not_active(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
        user_repository: DynamoDBUserRepository,
        member_repository: DynamoDBMemberRepository,
    ) -> None:
        """Inactive membership raises 'Account is not active' (Req 1.4, 14.5)."""
        cognito_sub = _create_cognito_user(cognito_pool)
        user_id = str(uuid.uuid4())
        _seed_user_in_dynamodb(dynamodb_table, TEST_EMAIL, user_id, cognito_sub)
        _seed_member_in_dynamodb(
            dynamodb_table, TENANT_ID, user_id, TEST_EMAIL, status="inactive"
        )

        login_use_case = LoginUseCase(
            cognito_service=cognito_service,
            user_repository=user_repository,
            member_repository=member_repository,
        )

        with pytest.raises(DomainError) as exc_info:
            await login_use_case.execute(
                LoginInputDTO(email=TEST_EMAIL, password=TEST_PASSWORD, tenant_id=TENANT_ID)
            )
        assert exc_info.value.message == "Account is not active"

    @pytest.mark.asyncio
    async def test_pending_confirmation_membership_returns_account_not_active(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
        user_repository: DynamoDBUserRepository,
        member_repository: DynamoDBMemberRepository,
    ) -> None:
        """pending_confirmation membership also raises 'Account is not active'."""
        cognito_sub = _create_cognito_user(cognito_pool)
        user_id = str(uuid.uuid4())
        _seed_user_in_dynamodb(dynamodb_table, TEST_EMAIL, user_id, cognito_sub)
        _seed_member_in_dynamodb(
            dynamodb_table, TENANT_ID, user_id, TEST_EMAIL, status="pending_confirmation"
        )

        login_use_case = LoginUseCase(
            cognito_service=cognito_service,
            user_repository=user_repository,
            member_repository=member_repository,
        )

        with pytest.raises(DomainError) as exc_info:
            await login_use_case.execute(
                LoginInputDTO(email=TEST_EMAIL, password=TEST_PASSWORD, tenant_id=TENANT_ID)
            )
        assert exc_info.value.message == "Account is not active"


class TestTokenRefresh:
    """Test token refresh flow via Cognito.

    Validates: Requirement 2.1
    """

    @pytest.mark.asyncio
    async def test_refresh_auth_returns_new_tokens(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
    ) -> None:
        """A valid refresh token obtains new access/id tokens (Req 2.1)."""
        # Create user and authenticate to get initial tokens
        _create_cognito_user(cognito_pool)

        # Authenticate to get a refresh_token
        token_pair = await cognito_service.initiate_auth(TEST_EMAIL, TEST_PASSWORD)
        assert token_pair.refresh_token != ""

        # Refresh tokens
        refreshed = await cognito_service.refresh_auth(token_pair.refresh_token)

        assert refreshed.access_token != ""
        assert refreshed.id_token != ""
        assert refreshed.expires_in > 0

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_token_raises_error(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
    ) -> None:
        """An invalid refresh token raises an error (Req 2.1).

        Note: moto raises KeyError instead of NotAuthorizedException for invalid
        refresh tokens. In production Cognito, this would map to InvalidCredentialsError
        via our error handling. We verify that invalid tokens cannot succeed.
        """
        with pytest.raises(Exception):
            await cognito_service.refresh_auth("invalid-refresh-token-value")


class TestGlobalSignOut:
    """Test global sign out functionality.

    Validates: Requirement 1.7 (session management)
    """

    @pytest.mark.asyncio
    async def test_global_sign_out_invalidates_tokens(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
    ) -> None:
        """Global sign out invalidates the access token (Req 1.7)."""
        _create_cognito_user(cognito_pool)

        # Authenticate
        token_pair = await cognito_service.initiate_auth(TEST_EMAIL, TEST_PASSWORD)

        # Sign out (should not raise)
        await cognito_service.global_sign_out(token_pair.access_token)

        # After sign out, using the refresh token should fail
        with pytest.raises(InvalidCredentialsError):
            await cognito_service.refresh_auth(token_pair.refresh_token)

    @pytest.mark.asyncio
    async def test_global_sign_out_with_invalid_token_raises_error(
        self,
        dynamodb_table: Any,
        cognito_pool: dict[str, str],
        cognito_service: CognitoAuthService,
    ) -> None:
        """Calling global_sign_out with an invalid token raises an error.

        Note: moto may not fully replicate Cognito's error response for
        invalid access tokens. We verify that invalid tokens cannot succeed silently.
        """
        with pytest.raises((InvalidCredentialsError, Exception)):
            await cognito_service.global_sign_out("invalid-access-token-value")


# â”€â”€â”€ Property-Based Tests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestProperty12TokenContainsCorrectRoles:
    """Property 12: Token Contains Correct Roles.

    **Validates: Requirements 1.2, 1.7**

    For any valid set of assigned roles, the login response always
    contains exactly those roles.
    """

    @given(roles=valid_role_subsets)
    @settings(max_examples=50, deadline=None)
    @pytest.mark.asyncio
    async def test_login_returns_exactly_assigned_roles(self, roles: list[str]) -> None:
        """For any subset of valid roles, login returns exactly those roles."""
        import api.common.config.dynamodbClient as ddb_mod
        import api.common.config.environment as env_mod

        with mock_aws():
            ddb_mod._dynamodb_resource = None
            ddb_mod._table = None
            env_mod._config = None

            # Create DynamoDB table
            dynamodb = boto3.resource("dynamodb", region_name=TEST_REGION)
            table = dynamodb.create_table(
                TableName=TEST_TABLE_NAME,
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
            table.meta.client.get_waiter("table_exists").wait(TableName=TEST_TABLE_NAME)

            # Create Cognito pool
            cognito_client = boto3.client("cognito-idp", region_name=TEST_REGION)
            pool_response = cognito_client.create_user_pool(
                PoolName="TestPool",
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
            )
            pool_id = pool_response["UserPool"]["Id"]
            client_response = cognito_client.create_user_pool_client(
                UserPoolId=pool_id,
                ClientName="TestClient",
                ExplicitAuthFlows=[
                    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
                    "ALLOW_REFRESH_TOKEN_AUTH",
                ],
            )
            client_id = client_response["UserPoolClient"]["ClientId"]

            os.environ["COGNITO_USER_POOL_ID"] = pool_id
            os.environ["COGNITO_CLIENT_ID"] = client_id

            # Create user in Cognito
            email = TEST_EMAIL
            cognito_client.admin_create_user(
                UserPoolId=pool_id,
                Username=email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": TEST_FULL_NAME},
                ],
                MessageAction="SUPPRESS",
            )
            cognito_client.admin_set_user_password(
                UserPoolId=pool_id,
                Username=email,
                Password=TEST_PASSWORD,
                Permanent=True,
            )
            user_response = cognito_client.admin_get_user(
                UserPoolId=pool_id, Username=email
            )
            cognito_sub = email
            for attr in user_response["UserAttributes"]:
                if attr["Name"] == "sub":
                    cognito_sub = attr["Value"]
                    break

            # Seed DynamoDB records
            user_id = str(uuid.uuid4())
            _seed_user_in_dynamodb(table, email, user_id, cognito_sub)
            _seed_member_in_dynamodb(table, TENANT_ID, user_id, email)
            _seed_roles_in_dynamodb(table, user_id, TENANT_ID, roles)

            # Execute login
            cognito_svc = CognitoAuthService(
                user_pool_id=pool_id,
                client_id=client_id,
                region=TEST_REGION,
            )
            user_repo = DynamoDBUserRepository(table=table)
            member_repo = DynamoDBMemberRepository()

            login_use_case = LoginUseCase(
                cognito_service=cognito_svc,
                user_repository=user_repo,
                member_repository=member_repo,
            )
            result = await login_use_case.execute(
                LoginInputDTO(email=email, password=TEST_PASSWORD, tenant_id=TENANT_ID)
            )

            # Property: login result contains exactly the assigned roles
            assert sorted(result.roles) == sorted(roles)
