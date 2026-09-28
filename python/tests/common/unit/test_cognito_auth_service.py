"""Unit tests for CognitoAuthService using moto mock."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from api.common.errors.conflictError import ConflictError
from api.common.errors.invalidCredentialsError import InvalidCredentialsError
from api.common.errors.validationError import ValidationError
from api.common.auth.cognitoAuthService import CognitoAuthService


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


# ──── Tests: Social Login (exchange_code_for_tokens) ──────────────────────────


TEST_USER_POOL_ID = "us-east-1_test123"
TEST_CLIENT_ID = "test-client-id"
TEST_HOSTED_UI_DOMAIN = "sport-dev.auth.us-east-1.amazoncognito.com"
TEST_REDIRECT_URI = "https://api.example.com/auth/social/callback"
TEST_CODE = "auth-code-123"


@pytest.fixture
def mock_client():
    """A MagicMock standing in for the boto3 cognito-idp client."""
    from unittest.mock import MagicMock

    return MagicMock()


@pytest.fixture
def social_service(mock_client) -> CognitoAuthService:
    """CognitoAuthService wired to a MagicMock Cognito client for social tests."""
    return CognitoAuthService(
        user_pool_id=TEST_USER_POOL_ID,
        client_id=TEST_CLIENT_ID,
        region=REGION,
        client=mock_client,
    )


class _FakeHTTPResponse:
    """Minimal context-manager stand-in for urllib's HTTP response."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_returns_token_pair(social_service, monkeypatch):
    """Should parse a successful token endpoint response into a TokenPair."""
    import json as _json

    body = _json.dumps(
        {
            "access_token": "access-abc",
            "id_token": "id-abc",
            "refresh_token": "refresh-abc",
            "expires_in": 3600,
        }
    ).encode("utf-8")

    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["data"] = request.data
        captured["headers"] = request.headers
        return _FakeHTTPResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = await social_service.exchange_code_for_tokens(
        TEST_CODE, TEST_REDIRECT_URI, TEST_HOSTED_UI_DOMAIN
    )

    assert result.access_token == "access-abc"
    assert result.id_token == "id-abc"
    assert result.refresh_token == "refresh-abc"
    assert result.expires_in == 3600

    # Verify the request targeted the Hosted UI token endpoint with the
    # authorization_code grant and form-urlencoded body.
    assert captured["url"] == f"https://{TEST_HOSTED_UI_DOMAIN}/oauth2/token"
    assert captured["method"] == "POST"
    decoded = captured["data"].decode("utf-8")
    assert "grant_type=authorization_code" in decoded
    assert f"code={TEST_CODE}" in decoded
    assert f"client_id={TEST_CLIENT_ID}" in decoded
    assert "redirect_uri=" in decoded


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_defaults_missing_refresh_token(social_service, monkeypatch):
    """Should default refresh_token to empty string when absent."""
    import json as _json

    body = _json.dumps(
        {"access_token": "a", "id_token": "i", "expires_in": 3600}
    ).encode("utf-8")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request: _FakeHTTPResponse(body)
    )

    result = await social_service.exchange_code_for_tokens(
        TEST_CODE, TEST_REDIRECT_URI, TEST_HOSTED_UI_DOMAIN
    )

    assert result.refresh_token == ""


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_raises_on_non_2xx_status(social_service, monkeypatch):
    """Should raise token_exchange_failed when urlopen returns a non-2xx status.

    Covers the explicit status-code guard in the adapter (a response that
    opens successfully but carries a non-2xx status, distinct from an
    ``HTTPError`` being raised).
    """
    import json as _json

    body = _json.dumps(
        {
            "access_token": "a",
            "id_token": "i",
            "refresh_token": "r",
            "expires_in": 3600,
        }
    ).encode("utf-8")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request: _FakeHTTPResponse(body, status=500),
    )

    with pytest.raises(ValidationError) as exc_info:
        await social_service.exchange_code_for_tokens(
            TEST_CODE, TEST_REDIRECT_URI, TEST_HOSTED_UI_DOMAIN
        )
    assert exc_info.value.message == "token_exchange_failed"


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_raises_on_http_error(social_service, monkeypatch):
    """Should raise token_exchange_failed on a non-2xx HTTP error."""
    import urllib.error

    def raise_http_error(request):
        raise urllib.error.HTTPError(
            url=request.full_url, code=400, msg="Bad Request", hdrs=None, fp=None
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)

    with pytest.raises(ValidationError) as exc_info:
        await social_service.exchange_code_for_tokens(
            TEST_CODE, TEST_REDIRECT_URI, TEST_HOSTED_UI_DOMAIN
        )
    assert exc_info.value.message == "token_exchange_failed"


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_raises_on_network_error(social_service, monkeypatch):
    """Should raise token_exchange_failed on a network/URL error."""
    import urllib.error

    def raise_url_error(request):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    with pytest.raises(ValidationError) as exc_info:
        await social_service.exchange_code_for_tokens(
            TEST_CODE, TEST_REDIRECT_URI, TEST_HOSTED_UI_DOMAIN
        )
    assert exc_info.value.message == "token_exchange_failed"


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_raises_on_malformed_json(social_service, monkeypatch):
    """Should raise token_exchange_failed when the response is not valid JSON."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request: _FakeHTTPResponse(b"not-json"),
    )

    with pytest.raises(ValidationError) as exc_info:
        await social_service.exchange_code_for_tokens(
            TEST_CODE, TEST_REDIRECT_URI, TEST_HOSTED_UI_DOMAIN
        )
    assert exc_info.value.message == "token_exchange_failed"


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_raises_on_missing_fields(social_service, monkeypatch):
    """Should raise token_exchange_failed when required token fields are absent."""
    import json as _json

    body = _json.dumps({"access_token": "a"}).encode("utf-8")  # missing id_token, expires_in
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request: _FakeHTTPResponse(body)
    )

    with pytest.raises(ValidationError) as exc_info:
        await social_service.exchange_code_for_tokens(
            TEST_CODE, TEST_REDIRECT_URI, TEST_HOSTED_UI_DOMAIN
        )
    assert exc_info.value.message == "token_exchange_failed"


# ──── Tests: Social Login (admin_link_provider_for_user) ──────────────────────


@pytest.mark.asyncio
async def test_admin_link_provider_for_user_calls_cognito(social_service, mock_client):
    """Should call Cognito AdminLinkProviderForUser with destination and source users."""
    await social_service.admin_link_provider_for_user(
        destination_cognito_sub="cognito-sub-1",
        provider_name="Google",
        provider_user_id="google-sub-9",
    )

    mock_client.admin_link_provider_for_user.assert_called_once()
    kwargs = mock_client.admin_link_provider_for_user.call_args.kwargs
    assert kwargs["UserPoolId"] == TEST_USER_POOL_ID
    assert kwargs["DestinationUser"]["ProviderName"] == "Cognito"
    assert kwargs["DestinationUser"]["ProviderAttributeValue"] == "cognito-sub-1"
    assert kwargs["SourceUser"]["ProviderName"] == "Google"
    assert kwargs["SourceUser"]["ProviderAttributeValue"] == "google-sub-9"


@pytest.mark.asyncio
async def test_admin_link_provider_for_user_raises_conflict_on_failure(social_service, mock_client):
    """Should raise ConflictError with provider_link_failed on a Cognito error."""
    from botocore.exceptions import ClientError

    mock_client.admin_link_provider_for_user.side_effect = ClientError(
        {"Error": {"Code": "InvalidParameterException", "Message": "bad"}},
        "AdminLinkProviderForUser",
    )

    with pytest.raises(ConflictError) as exc_info:
        await social_service.admin_link_provider_for_user(
            destination_cognito_sub="cognito-sub-1",
            provider_name="Facebook",
            provider_user_id="fb-id-3",
        )
    assert exc_info.value.message == "provider_link_failed"


# ──── Tests: Social Login (admin_update_user_attributes) ──────────────────────


@pytest.mark.asyncio
async def test_admin_update_user_attributes_calls_cognito(social_service, mock_client):
    """Should map the attributes dict into Cognito's Name/Value attribute list."""
    await social_service.admin_update_user_attributes(
        cognito_sub="cognito-sub-1",
        attributes={"custom:provider": "google"},
    )

    mock_client.admin_update_user_attributes.assert_called_once()
    kwargs = mock_client.admin_update_user_attributes.call_args.kwargs
    assert kwargs["UserPoolId"] == TEST_USER_POOL_ID
    assert kwargs["Username"] == "cognito-sub-1"
    assert {"Name": "custom:provider", "Value": "google"} in kwargs["UserAttributes"]

# ──── Tests: forgot_password (Task 5.1) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_forgot_password_calls_cognito_with_client_id_and_username(social_service, mock_client):
    """Should call Cognito ForgotPassword with the App Client ID and username."""
    result = await social_service.forgot_password(TEST_EMAIL)

    assert result is None
    mock_client.forgot_password.assert_called_once()
    kwargs = mock_client.forgot_password.call_args.kwargs
    assert kwargs["ClientId"] == TEST_CLIENT_ID
    assert kwargs["Username"] == TEST_EMAIL


@pytest.mark.asyncio
async def test_forgot_password_swallows_user_not_found(social_service, mock_client):
    """Should treat UserNotFoundException as success (anti-enumeration) and return None."""
    from botocore.exceptions import ClientError

    mock_client.forgot_password.side_effect = ClientError(
        {"Error": {"Code": "UserNotFoundException", "Message": "not found"}},
        "ForgotPassword",
    )

    result = await social_service.forgot_password("nobody@example.com")

    assert result is None


@pytest.mark.asyncio
async def test_forgot_password_raises_rate_limit_on_limit_exceeded(social_service, mock_client):
    """Should raise RateLimitError when Cognito reports LimitExceededException."""
    from botocore.exceptions import ClientError

    from api.common.errors.rateLimitError import RateLimitError

    mock_client.forgot_password.side_effect = ClientError(
        {"Error": {"Code": "LimitExceededException", "Message": "slow down"}},
        "ForgotPassword",
    )

    with pytest.raises(RateLimitError):
        await social_service.forgot_password(TEST_EMAIL)


@pytest.mark.asyncio
async def test_forgot_password_reraises_unexpected_error(social_service, mock_client):
    """Should re-raise the ClientError for an unexpected Cognito error code."""
    from botocore.exceptions import ClientError

    mock_client.forgot_password.side_effect = ClientError(
        {"Error": {"Code": "InternalErrorException", "Message": "boom"}},
        "ForgotPassword",
    )

    with pytest.raises(ClientError):
        await social_service.forgot_password(TEST_EMAIL)


# ──── Tests: confirm_forgot_password (Task 5.2) ───────────────────────────────

TEST_CONFIRMATION_CODE = "123456"
TEST_NEW_PASSWORD = "NewPass1!"


@pytest.mark.asyncio
async def test_confirm_forgot_password_calls_cognito_on_success(social_service, mock_client):
    """Should call Cognito ConfirmForgotPassword with the supplied values."""
    await social_service.confirm_forgot_password(
        TEST_EMAIL, TEST_CONFIRMATION_CODE, TEST_NEW_PASSWORD
    )

    mock_client.confirm_forgot_password.assert_called_once()
    kwargs = mock_client.confirm_forgot_password.call_args.kwargs
    assert kwargs["ClientId"] == TEST_CLIENT_ID
    assert kwargs["Username"] == TEST_EMAIL
    assert kwargs["ConfirmationCode"] == TEST_CONFIRMATION_CODE
    assert kwargs["Password"] == TEST_NEW_PASSWORD


@pytest.mark.asyncio
async def test_confirm_forgot_password_raises_validation_on_invalid_password(social_service, mock_client):
    """Should raise ValidationError conveying the Cognito policy message."""
    from botocore.exceptions import ClientError

    mock_client.confirm_forgot_password.side_effect = ClientError(
        {"Error": {"Code": "InvalidPasswordException", "Message": "Password too short"}},
        "ConfirmForgotPassword",
    )

    with pytest.raises(ValidationError) as exc_info:
        await social_service.confirm_forgot_password(
            TEST_EMAIL, TEST_CONFIRMATION_CODE, "short"
        )
    assert exc_info.value.message == "Password too short"


@pytest.mark.asyncio
async def test_confirm_forgot_password_raises_validation_on_code_mismatch(social_service, mock_client):
    """Should raise ValidationError when the confirmation code does not match."""
    from botocore.exceptions import ClientError

    mock_client.confirm_forgot_password.side_effect = ClientError(
        {"Error": {"Code": "CodeMismatchException", "Message": "wrong code"}},
        "ConfirmForgotPassword",
    )

    with pytest.raises(ValidationError) as exc_info:
        await social_service.confirm_forgot_password(
            TEST_EMAIL, "000000", TEST_NEW_PASSWORD
        )
    assert exc_info.value.message == "Invalid confirmation code"


@pytest.mark.asyncio
async def test_confirm_forgot_password_raises_validation_on_expired_code(social_service, mock_client):
    """Should raise ValidationError when the confirmation code has expired."""
    from botocore.exceptions import ClientError

    mock_client.confirm_forgot_password.side_effect = ClientError(
        {"Error": {"Code": "ExpiredCodeException", "Message": "expired"}},
        "ConfirmForgotPassword",
    )

    with pytest.raises(ValidationError) as exc_info:
        await social_service.confirm_forgot_password(
            TEST_EMAIL, TEST_CONFIRMATION_CODE, TEST_NEW_PASSWORD
        )
    assert exc_info.value.message == "Confirmation code has expired"


@pytest.mark.asyncio
async def test_confirm_forgot_password_raises_rate_limit_on_limit_exceeded(social_service, mock_client):
    """Should raise RateLimitError when Cognito reports LimitExceededException."""
    from botocore.exceptions import ClientError

    from api.common.errors.rateLimitError import RateLimitError

    mock_client.confirm_forgot_password.side_effect = ClientError(
        {"Error": {"Code": "LimitExceededException", "Message": "slow down"}},
        "ConfirmForgotPassword",
    )

    with pytest.raises(RateLimitError):
        await social_service.confirm_forgot_password(
            TEST_EMAIL, TEST_CONFIRMATION_CODE, TEST_NEW_PASSWORD
        )


# ──── Tests: respond_to_challenge (Task 5.3) ──────────────────────────────────

TEST_SESSION = "opaque-session-token"


@pytest.mark.asyncio
async def test_respond_to_challenge_returns_authenticated_result(social_service, mock_client):
    """Should return an authenticated ChallengeResult when tokens are returned."""
    mock_client.respond_to_auth_challenge.return_value = {
        "AuthenticationResult": {
            "AccessToken": "access-xyz",
            "IdToken": "id-xyz",
            "RefreshToken": "refresh-xyz",
            "ExpiresIn": 3600,
        }
    }

    result = await social_service.respond_to_challenge(
        "NEW_PASSWORD_REQUIRED", TEST_SESSION, {"NEW_PASSWORD": "NewPass1!"}
    )

    assert result.is_authenticated() is True
    assert result.token_pair is not None
    assert result.token_pair.access_token == "access-xyz"
    assert result.token_pair.id_token == "id-xyz"
    assert result.token_pair.refresh_token == "refresh-xyz"
    assert result.token_pair.expires_in == 3600
    assert result.next_challenge_name is None
    assert result.next_session is None


@pytest.mark.asyncio
async def test_respond_to_challenge_returns_next_challenge_result(social_service, mock_client):
    """Should return a next-challenge ChallengeResult when Cognito returns another challenge."""
    mock_client.respond_to_auth_challenge.return_value = {
        "ChallengeName": "SMS_MFA",
        "Session": "next-session-token",
    }

    result = await social_service.respond_to_challenge(
        "NEW_PASSWORD_REQUIRED", TEST_SESSION, {"NEW_PASSWORD": "NewPass1!"}
    )

    assert result.is_authenticated() is False
    assert result.token_pair is None
    assert result.next_challenge_name == "SMS_MFA"
    assert result.next_session == "next-session-token"


@pytest.mark.asyncio
async def test_respond_to_challenge_raises_invalid_credentials_on_not_authorized(social_service, mock_client):
    """Should raise InvalidCredentialsError when the challenge session is invalid/expired."""
    from botocore.exceptions import ClientError

    mock_client.respond_to_auth_challenge.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException", "Message": "invalid session"}},
        "RespondToAuthChallenge",
    )

    with pytest.raises(InvalidCredentialsError):
        await social_service.respond_to_challenge(
            "NEW_PASSWORD_REQUIRED", TEST_SESSION, {"NEW_PASSWORD": "NewPass1!"}
        )


@pytest.mark.asyncio
async def test_respond_to_challenge_raises_validation_on_invalid_password(social_service, mock_client):
    """Should raise ValidationError conveying the Cognito policy message on InvalidPassword."""
    from botocore.exceptions import ClientError

    mock_client.respond_to_auth_challenge.side_effect = ClientError(
        {"Error": {"Code": "InvalidPasswordException", "Message": "Password does not meet policy"}},
        "RespondToAuthChallenge",
    )

    with pytest.raises(ValidationError) as exc_info:
        await social_service.respond_to_challenge(
            "NEW_PASSWORD_REQUIRED", TEST_SESSION, {"NEW_PASSWORD": "weak"}
        )
    assert exc_info.value.message == "Password does not meet policy"
