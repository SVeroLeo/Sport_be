"""AWS Cognito implementation of ICognitoService.

Wraps boto3's cognito-idp client to provide user registration,
authentication, and user management operations. All credential
verification is delegated to Cognito — plain-text passwords are
never stored or logged by this service.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from application.ports.i_cognito_service import ICognitoService
from domain.entities.challenge_result import ChallengeResult
from domain.entities.token_pair import TokenPair
from domain.errors.conflict_error import ConflictError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.errors.rate_limit_error import RateLimitError
from domain.errors.validation_error import ValidationError

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

    # ──── Social Login ────────────────────────────────────────────────────────

    async def exchange_code_for_tokens(
        self,
        code: str,
        redirect_uri: str,
        hosted_ui_domain: str,
    ) -> TokenPair:
        """Exchange an OAuth authorization code for a token set.

        Calls the Cognito Hosted UI ``POST /oauth2/token`` endpoint with the
        ``authorization_code`` grant. The request body is form-urlencoded per
        the OAuth 2.0 spec. The response JSON is parsed into a TokenPair.

        The standard library ``urllib`` is used for the HTTP call so no extra
        runtime dependency (requests/httpx) is required in the Lambda bundle.

        Args:
            code: The authorization code returned by the Hosted UI.
            redirect_uri: The redirect URI registered with the App Client;
                must match the one used to obtain the code.
            hosted_ui_domain: The Cognito Hosted UI domain (e.g.
                ``sport-dev.auth.us-east-1.amazoncognito.com``) used to build
                the token endpoint URL.

        Returns:
            A TokenPair containing access_token, id_token,
            refresh_token, and expires_in.

        Raises:
            ValidationError: With code ``"token_exchange_failed"`` on any
                failure — non-2xx HTTP response, network error, malformed
                JSON, or a response missing required token fields.
        """
        token_endpoint = f"https://{hosted_ui_domain}/oauth2/token"
        form_body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
            }
        ).encode("utf-8")

        request = urllib.request.Request(  # noqa: S310 - https URL built from trusted domain
            token_endpoint,
            data=form_body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310
                status_code = getattr(response, "status", 200)
                if status_code < 200 or status_code >= 300:
                    logger.error("Token exchange returned non-2xx status: %s", status_code)
                    raise ValidationError("token_exchange_failed")
                payload = json.loads(response.read().decode("utf-8"))
        except ValidationError:
            raise
        except urllib.error.HTTPError as e:
            logger.error("Token exchange HTTP error: %s", e.code)
            raise ValidationError("token_exchange_failed") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.error("Token exchange network error: %s", type(e).__name__)
            raise ValidationError("token_exchange_failed") from e
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Token exchange returned malformed JSON")
            raise ValidationError("token_exchange_failed") from e

        try:
            return TokenPair(
                access_token=payload["access_token"],
                id_token=payload["id_token"],
                refresh_token=payload.get("refresh_token", ""),
                expires_in=payload["expires_in"],
            )
        except (KeyError, TypeError) as e:
            logger.error("Token exchange response missing required fields")
            raise ValidationError("token_exchange_failed") from e

    async def admin_link_provider_for_user(
        self,
        destination_cognito_sub: str,
        provider_name: str,
        provider_user_id: str,
    ) -> None:
        """Link a social identity provider to an existing Cognito user.

        Calls Cognito ``AdminLinkProviderForUser`` so a federated identity
        (Google/Facebook) resolves to an existing native Cognito account.

        Args:
            destination_cognito_sub: The Cognito sub of the existing user the
                provider identity should be linked to.
            provider_name: The identity provider name ("Google" or "Facebook").
            provider_user_id: The provider-specific user identifier (the
                ``sub`` from Google or ``id`` from Facebook).

        Raises:
            ConflictError: With code ``"provider_link_failed"`` if the Cognito
                link operation fails.
        """
        try:
            self._client.admin_link_provider_for_user(
                UserPoolId=self._user_pool_id,
                DestinationUser={
                    "ProviderName": "Cognito",
                    "ProviderAttributeValue": destination_cognito_sub,
                },
                SourceUser={
                    "ProviderName": provider_name,
                    "ProviderAttributeName": "Cognito_Subject",
                    "ProviderAttributeValue": provider_user_id,
                },
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            logger.error("Cognito error during admin_link_provider_for_user: %s", error_code)
            raise ConflictError(
                message="provider_link_failed",
                resource="user",
            ) from e

    async def admin_update_user_attributes(
        self,
        cognito_sub: str,
        attributes: dict[str, str],
    ) -> None:
        """Update custom or standard attributes on a Cognito user.

        Calls Cognito ``AdminUpdateUserAttributes`` to set the given
        attributes (e.g. ``custom:provider``) on the user record.

        Args:
            cognito_sub: The Cognito sub (user ID) whose attributes are updated.
            attributes: A mapping of attribute name to value to set.
        """
        self._client.admin_update_user_attributes(
            UserPoolId=self._user_pool_id,
            Username=cognito_sub,
            UserAttributes=[
                {"Name": name, "Value": value} for name, value in attributes.items()
            ],
        )

    # ──── Password Recovery ───────────────────────────────────────────────────

    async def forgot_password(self, email: str) -> None:
        """Initiate a password reset via Cognito ForgotPassword.

        Triggers Cognito to email a confirmation code to the user. To prevent
        user enumeration (Req 1.3), ``UserNotFoundException`` is swallowed and
        treated as a silent success so callers cannot distinguish a registered
        email from an unregistered one. The email is NOT logged in that branch.

        Args:
            email: The user's email address (used as Cognito username).

        Raises:
            RateLimitError: If Cognito reports a rate limit condition
                (``LimitExceededException`` or ``TooManyRequestsException``).
        """
        # SECRET_HASH-conditional extension point (Req 1.8): the current App
        # Client has no client secret, so SECRET_HASH is omitted. If a secret
        # is configured in the future, add
        #   SecretHash=_secret_hash(email, self._client_id, self._client_secret)
        # to the call below using the same HMAC derivation as the other methods.
        try:
            self._client.forgot_password(
                ClientId=self._client_id,
                Username=email,
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "UserNotFoundException":
                # Anti-enumeration: swallow silently, do not log the email.
                return None
            if error_code in ("LimitExceededException", "TooManyRequestsException"):
                raise RateLimitError() from e
            logger.error("Unexpected Cognito error during forgot_password: %s", error_code)
            raise
        return None

    async def confirm_forgot_password(
        self,
        email: str,
        confirmation_code: str,
        new_password: str,
    ) -> None:
        """Complete a password reset via Cognito ConfirmForgotPassword.

        Uses the confirmation code emailed to the user plus the chosen new
        password to finalize the reset. No tokens are returned; the user must
        log in afterward. The password and confirmation code are NEVER logged.

        Args:
            email: The user's email address.
            confirmation_code: The one-time code emailed to the user.
            new_password: The user's chosen new password.

        Raises:
            ValidationError: If the new password violates the password policy
                (``InvalidPasswordException`` — the Cognito message is used as
                the reason, Req 2.7), the confirmation code does not match
                (``CodeMismatchException``), or has expired
                (``ExpiredCodeException``).
            RateLimitError: If Cognito reports a rate limit condition
                (``LimitExceededException`` or ``TooManyRequestsException``).
        """
        # SECRET_HASH-conditional extension point (Req 2.12): omitted today
        # (App Client has no secret). If a secret is configured, add
        #   SecretHash=_secret_hash(email, self._client_id, self._client_secret)
        # to the call below using the same HMAC derivation as the other methods.
        try:
            self._client.confirm_forgot_password(
                ClientId=self._client_id,
                Username=email,
                ConfirmationCode=confirmation_code,
                Password=new_password,
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "InvalidPasswordException":
                # Convey the Cognito-reported policy reason (Req 2.7).
                raise ValidationError(e.response["Error"]["Message"]) from e
            if error_code == "CodeMismatchException":
                raise ValidationError("Invalid confirmation code") from e
            if error_code == "ExpiredCodeException":
                raise ValidationError("Confirmation code has expired") from e
            if error_code in ("LimitExceededException", "TooManyRequestsException"):
                raise RateLimitError() from e
            logger.error(
                "Unexpected Cognito error during confirm_forgot_password: %s", error_code
            )
            raise

    async def respond_to_challenge(
        self,
        challenge_name: str,
        session: str,
        challenge_responses: dict[str, str],
    ) -> ChallengeResult:
        """Respond to a Cognito authentication challenge.

        Calls Cognito RespondToAuthChallenge to resolve a pending challenge
        (e.g. ``NEW_PASSWORD_REQUIRED``, ``SMS_MFA``) identified by the
        challenge session issued during login. The session and any returned
        tokens are NEVER logged.

        Args:
            challenge_name: The Cognito challenge type being answered.
            session: The opaque challenge session token issued by Cognito.
            challenge_responses: The key-value pairs required to resolve the
                specific challenge.

        Returns:
            A ChallengeResult carrying EITHER a TokenPair when the challenge
            completes authentication, OR the next challenge (challenge_name and
            session) when Cognito requires a further step.

        Raises:
            InvalidCredentialsError: If the challenge session is invalid or
                expired (``NotAuthorizedException`` or ``CodeMismatchException``).
            ValidationError: If the new password supplied for a
                ``NEW_PASSWORD_REQUIRED`` challenge violates the password policy
                (``InvalidPasswordException`` — the Cognito message is used as
                the reason, Req 3.8).
        """
        # SECRET_HASH-conditional extension point (Req 3.10): omitted today
        # (App Client has no secret). If a secret is configured, inject it into
        # the challenge responses:
        #   challenge_responses["SECRET_HASH"] = _secret_hash(
        #       username, self._client_id, self._client_secret)
        # using the same HMAC derivation as the other methods.
        try:
            resp = self._client.respond_to_auth_challenge(
                ClientId=self._client_id,
                ChallengeName=challenge_name,
                Session=session,
                ChallengeResponses=challenge_responses,
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("NotAuthorizedException", "CodeMismatchException"):
                raise InvalidCredentialsError() from e
            if error_code == "InvalidPasswordException":
                raise ValidationError(e.response["Error"]["Message"]) from e
            logger.error(
                "Unexpected Cognito error during respond_to_challenge: %s", error_code
            )
            raise

        if "AuthenticationResult" in resp:
            auth_result: dict[str, Any] = resp["AuthenticationResult"]
            token_pair = TokenPair(
                access_token=auth_result["AccessToken"],
                id_token=auth_result["IdToken"],
                refresh_token=auth_result.get("RefreshToken", ""),
                expires_in=auth_result["ExpiresIn"],
            )
            return ChallengeResult.authenticated(token_pair)

        return ChallengeResult.next_challenge(resp["ChallengeName"], resp["Session"])
