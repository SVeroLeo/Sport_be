"""Unit tests for CognitoAuthService using moto mock."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from domain.errors.conflict_error import ConflictError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from infrastructure.auth.cognito_auth_service import CognitoAuthService


# ──── Constants ───────────────────────────────────────────────────────────────

REGION = "us-east-1"
USER_POOL_NAME = "test-pool"
TEST_EMAIL = "user@example.com"
TEST_PASSWORD = "TestPass1!"
TEST_FULL_NAME = "John Doe"


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def cognito_setup():
    """Create a mocked Cognito User Pool and App Client with moto."""
    with mock_aws():
        client = boto3.client("cognito-idp", region_name=REGION)

        # Create User Pool
        pool_response = client.create_user_pool(
            PoolName=USER_POOL_NAME,
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
            ],
        )
        user_pool_id = pool_response["UserPool"]["Id"]

        # Create App Client
        client_response = client.create_user_pool_client(
            UserPoolId=user_pool_id,
            ClientName="test-client",
            ExplicitAuthFlows=["ADMIN_NO_SRP_AUTH"],
        )
        client_id = client_response["UserPoolClient"]["ClientId"]

        yield {
            "client": client,
            "user_pool_id": user_pool_id,
            "client_id": client_id,
        }


@pytest.fixture
def service(cognito_setup) -> CognitoAuthService:
    """Create a CognitoAuthService instance with mocked client."""
    return CognitoAuthService(
        user_pool_id=cognito_setup["user_pool_id"],
        client_id=cognito_setup["client_id"],
        region=REGION,
        client=cognito_setup["client"],
    )


def _create_confirmed_user(cognito_setup, email: str = TEST_EMAIL, password: str = TEST_PASSWORD) -> str:
    """Helper: create and confirm a user in the mocked Cognito pool."""
    client = cognito_setup["client"]
    user_pool_id = cognito_setup["user_pool_id"]

    # Admin-create and confirm the user
    client.admin_create_user(
        UserPoolId=user_pool_id,
        Username=email,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ],
        TemporaryPassword=password,
    )
    # Set permanent password to avoid FORCE_CHANGE_PASSWORD state
    client.admin_set_user_password(
        UserPoolId=user_pool_id,
        Username=email,
        Password=password,
        Permanent=True,
    )
    # Get the sub
    user_response = client.admin_get_user(
        UserPoolId=user_pool_id,
        Username=email,
    )
    for attr in user_response["UserAttributes"]:
        if attr["Name"] == "sub":
            return attr["Value"]
    return email


# ──── Tests: initiate_auth ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initiate_auth_returns_token_pair_on_success(cognito_setup, service):
    """Should return a TokenPair when credentials are valid."""
    _create_confirmed_user(cognito_setup)

    result = await service.initiate_auth(TEST_EMAIL, TEST_PASSWORD)

    assert result.access_token != ""
    assert result.id_token != ""
    assert result.refresh_token != ""
    assert result.expires_in > 0


@pytest.mark.asyncio
async def test_initiate_auth_raises_invalid_credentials_on_wrong_password(cognito_setup, service):
    """Should raise InvalidCredentialsError for wrong password."""
    _create_confirmed_user(cognito_setup)

    with pytest.raises(InvalidCredentialsError):
        await service.initiate_auth(TEST_EMAIL, "WrongPass1!")


@pytest.mark.asyncio
async def test_initiate_auth_raises_invalid_credentials_for_nonexistent_user(cognito_setup, service):
    """Should raise InvalidCredentialsError when user does not exist."""
    with pytest.raises(InvalidCredentialsError):
        await service.initiate_auth("nobody@example.com", TEST_PASSWORD)


# ──── Tests: sign_up ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sign_up_returns_cognito_sub(cognito_setup, service):
    """Should return the Cognito user sub on successful sign-up."""
    result = await service.sign_up(TEST_EMAIL, TEST_PASSWORD, TEST_FULL_NAME)

    # The sub should be a non-empty string (UUID format from moto)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_sign_up_raises_conflict_error_on_duplicate_email(cognito_setup, service):
    """Should raise ConflictError when email is already registered."""
    await service.sign_up(TEST_EMAIL, TEST_PASSWORD, TEST_FULL_NAME)

    with pytest.raises(ConflictError) as exc_info:
        await service.sign_up(TEST_EMAIL, TEST_PASSWORD, "Another Name")

    assert exc_info.value.resource == "user"
    assert "already registered" in exc_info.value.message.lower()


# ──── Tests: admin_create_user ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_create_user_returns_cognito_sub(cognito_setup, service):
    """Should return the Cognito user sub on successful admin creation."""
    result = await service.admin_create_user(TEST_EMAIL, TEST_FULL_NAME)

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_admin_create_user_raises_conflict_on_duplicate(cognito_setup, service):
    """Should raise ConflictError when email already exists."""
    await service.admin_create_user(TEST_EMAIL, TEST_FULL_NAME)

    with pytest.raises(ConflictError) as exc_info:
        await service.admin_create_user(TEST_EMAIL, "Duplicate User")

    assert exc_info.value.resource == "user"


# ──── Tests: admin_disable_user ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_disable_user_disables_authentication(cognito_setup, service):
    """Should disable the user, preventing future authentication."""
    _create_confirmed_user(cognito_setup)

    # In practice, admin_disable_user is called with the Cognito username (email)
    # since that's how Cognito AdminDisableUser works (Username = email in our pool)
    await service.admin_disable_user(TEST_EMAIL)

    # Verify user is disabled by checking their status
    user_response = cognito_setup["client"].admin_get_user(
        UserPoolId=cognito_setup["user_pool_id"],
        Username=TEST_EMAIL,
    )
    assert user_response["Enabled"] is False


# ──── Tests: admin_enable_user ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_enable_user_restores_authentication(cognito_setup, service):
    """Should re-enable a disabled user."""
    _create_confirmed_user(cognito_setup)

    # Disable first
    await service.admin_disable_user(TEST_EMAIL)

    # Re-enable
    await service.admin_enable_user(TEST_EMAIL)

    # Verify user is enabled
    user_response = cognito_setup["client"].admin_get_user(
        UserPoolId=cognito_setup["user_pool_id"],
        Username=TEST_EMAIL,
    )
    assert user_response["Enabled"] is True
