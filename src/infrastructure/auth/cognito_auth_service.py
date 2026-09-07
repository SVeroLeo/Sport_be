"""AWS Cognito implementation of ICognitoService.

Wraps boto3's cognito-idp client to provide user registration,
authentication, and user management operations. All credential
verification is delegated to Cognito — plain-text passwords are
never stored or logged by this service.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from application.ports.i_cognito_service import ICognitoService
from domain.entities.token_pair import TokenPair
from domain.errors.conflict_error import ConflictError
from domain.errors.invalid_credentials_error import InvalidCredentialsError

if TYPE_CHECKING:
    from mypy_boto3_cognito_idp import CognitoIdentityProviderClient

logger = logging.getLogger(__name__)


class CognitoAuthService(ICognitoService):
    """AWS Cognito-backed authentication service.

    Implements all ICognitoService port operations using the boto3
    cognito-idp client. The async signatures are for interface
    compatibility — actual boto3 calls are synchronous since Lambda
    is single-threaded.
    """

    def __init__(
        self,
        user_pool_id: str,
        client_id: str,
        *,
        region: str = "us-east-1",
        client: "CognitoIdentityProviderClient | None" = None,
    ) -> None:
        """Initialize the Cognito auth service.

        Args:
            user_pool_id: The Cognito User Pool ID.
            client_id: The Cognito App Client ID.
            region: AWS region for the Cognito service.
            client: Optional pre-configured cognito-idp client
                    (useful for testing with moto).
        """
        self._user_pool_id = user_pool_id
        self._client_id = client_id
        self._client: "CognitoIdentityProviderClient" = client or boto3.client(
            "cognito-idp", region_name=region
        )

    # ──── Authentication ──────────────────────────────────────────────────────

    async def initiate_auth(self, email: str, password: str) -> TokenPair:
        """Authenticate a user via Cognito AdminInitiateAuth.

        Uses ADMIN_NO_SRP_AUTH flow with USERNAME and PASSWORD parameters.

        Args:
            email: The user's email address (used as Cognito username).
            password: The user's password — forwarded to Cognito only,
                      never stored or logged.

        Returns:
            A TokenPair containing access_token, id_token,
            refresh_token, and expires_in.

        Raises:
            InvalidCredentialsError: If authentication fails for any reason
                (invalid email, wrong password, user not found, user disabled).
        """
        try:
            response = self._client.admin_initiate_auth(
                UserPoolId=self._user_pool_id,
                ClientId=self._client_id,
                AuthFlow="ADMIN_NO_SRP_AUTH",
                AuthParameters={
                    "USERNAME": email,
                    "PASSWORD": password,
                },
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in (
                "NotAuthorizedException",
                "UserNotFoundException",
                "UserNotConfirmedException",
            ):
                raise InvalidCredentialsError() from e
            logger.error("Unexpected Cognito error during initiate_auth: %s", error_code)
            raise

        auth_result: dict[str, Any] = response["AuthenticationResult"]
        return TokenPair(
            access_token=auth_result["AccessToken"],
            id_token=auth_result["IdToken"],
            refresh_token=auth_result["RefreshToken"],
            expires_in=auth_result["ExpiresIn"],
        )

    # ──── User Registration ───────────────────────────────────────────────────

    async def sign_up(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        account_type: str,
    ) -> str:
        """Register a new user in Cognito via the SignUp flow.

        Used for self-registration. Cognito sends a verification
        email to the user after successful sign-up. The tenant_id and
        account_type are stored as custom attributes so the Post
        Confirmation Lambda trigger can create DynamoDB records without
        a separate lookup.

        Args:
            email: The user's email address.
            password: The user's chosen password — forwarded to Cognito only.
            full_name: The user's full name (stored as Cognito attribute).
            tenant_id: UUID of the tenant the user is registering into.
            account_type: Resolved account type name (e.g. "usuario").

        Returns:
            The Cognito user sub (unique user ID in Cognito).

        Raises:
            ConflictError: If the email is already registered in Cognito.
        """
        try:
            response = self._client.sign_up(
                ClientId=self._client_id,
                Username=email,
                Password=password,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "name", "Value": full_name},
                    {"Name": "custom:tenant_id", "Value": tenant_id},
                    {"Name": "custom:account_type", "Value": account_type},
                ],
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "UsernameExistsException":
                raise ConflictError(
                    message="Email already registered",
                    resource="user",
                ) from e
            logger.error("Unexpected Cognito error during sign_up: %s", error_code)
            raise

        return response["UserSub"]

    async def admin_create_user(self, email: str, full_name: str) -> str:
        """Create a user via Cognito AdminCreateUser with a temporary password.

        Used for admin-invited member creation. Cognito sends an
        invitation email with a temporary password to the user.

        Args:
            email: The user's email address.
            full_name: The user's full name.

        Returns:
            The Cognito user sub (unique user ID in Cognito).

        Raises:
            ConflictError: If the email is already registered in Cognito.
        """
        try:
            response = self._client.admin_create_user(
                UserPoolId=self._user_pool_id,
                Username=email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": full_name},
                ],
                DesiredDeliveryMediums=["EMAIL"],
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "UsernameExistsException":
                raise ConflictError(
                    message="Email already registered",
                    resource="user",
                ) from e
            logger.error("Unexpected Cognito error during admin_create_user: %s", error_code)
            raise

        # Extract the sub from the created user's attributes
        user_attributes: list[dict[str, str]] = response["User"]["Attributes"]
        for attr in user_attributes:
            if attr["Name"] == "sub":
                return attr["Value"]

        # Fallback — should never happen with a properly configured pool
        return response["User"]["Username"]

    # ──── Token Refresh ───────────────────────────────────────────────────────

    async def refresh_auth(self, refresh_token: str) -> TokenPair:
        """Refresh tokens using Cognito REFRESH_TOKEN_AUTH flow.

        Args:
            refresh_token: The refresh token previously issued by Cognito.

        Returns:
            A TokenPair with updated access_token, id_token, and expires_in.

        Raises:
            InvalidCredentialsError: If the refresh token is invalid or expired.
        """
        try:
            response = self._client.admin_initiate_auth(
                UserPoolId=self._user_pool_id,
                ClientId=self._client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={
                    "REFRESH_TOKEN": refresh_token,
                },
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in (
                "NotAuthorizedException",
                "UserNotFoundException",
            ):
                raise InvalidCredentialsError() from e
            logger.error("Unexpected Cognito error during refresh_auth: %s", error_code)
            raise

        auth_result: dict[str, Any] = response["AuthenticationResult"]
        return TokenPair(
            access_token=auth_result["AccessToken"],
            id_token=auth_result["IdToken"],
            # Cognito may not return a new refresh token on refresh
            refresh_token=auth_result.get("RefreshToken", ""),
            expires_in=auth_result["ExpiresIn"],
        )

    # ──── Logout ──────────────────────────────────────────────────────────────

    async def global_sign_out(self, access_token: str) -> None:
        """Sign out a user globally by invalidating all Cognito tokens.

        Args:
            access_token: A valid access token for the user.

        Raises:
            InvalidCredentialsError: If the access token is invalid or expired.
        """
        try:
            self._client.global_sign_out(AccessToken=access_token)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in (
                "NotAuthorizedException",
                "InvalidParameterException",
            ):
                raise InvalidCredentialsError() from e
            logger.error("Unexpected Cognito error during global_sign_out: %s", error_code)
            raise

    # ──── User Management ─────────────────────────────────────────────────────

    async def admin_disable_user(self, cognito_sub: str) -> None:
        """Disable a user in Cognito to revoke all tokens.

        Used when deactivating a member to immediately invalidate
        all active sessions and tokens.

        Args:
            cognito_sub: The Cognito sub (user ID) to disable.
        """
        self._client.admin_disable_user(
            UserPoolId=self._user_pool_id,
            Username=cognito_sub,
        )

    async def admin_enable_user(self, cognito_sub: str) -> None:
        """Re-enable a previously disabled user in Cognito.

        Used when reactivating a member to restore their ability
        to authenticate.

        Args:
            cognito_sub: The Cognito sub (user ID) to enable.
        """
        self._client.admin_enable_user(
            UserPoolId=self._user_pool_id,
            Username=cognito_sub,
        )
