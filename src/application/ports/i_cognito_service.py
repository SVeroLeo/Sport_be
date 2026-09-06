"""ICognitoService port — defines the contract for AWS Cognito operations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.token_pair import TokenPair


class ICognitoService(ABC):
    """Abstract port defining AWS Cognito service operations.

    This port wraps all interactions with AWS Cognito for user
    registration, authentication, and user management. Infrastructure
    implementations handle the actual Cognito API calls.
    """

    @abstractmethod
    async def sign_up(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        account_type: str,
    ) -> str:
        """Register a new user in Cognito via SignUp flow.

        Used for self-registration. Cognito will send a verification
        email to the user. The tenant_id and account_type are stored as
        custom attributes so the Post Confirmation trigger can create the
        DynamoDB records without a separate lookup.

        Args:
            email: The user's email address.
            password: The user's chosen password (already validated).
            full_name: The user's full name.
            tenant_id: UUID of the tenant the user is registering into.
            account_type: Resolved account type name (e.g. "usuario").

        Returns:
            The Cognito sub (user ID in Cognito).

        Raises:
            ConflictError: If the email is already registered in Cognito.
        """

    @abstractmethod
    async def admin_create_user(self, email: str, full_name: str) -> str:
        """Create a user via Cognito AdminCreateUser with a temporary password.

        Used for admin-invited member creation. Cognito sends an
        invitation email with a temporary password to the user.

        Args:
            email: The user's email address.
            full_name: The user's full name.

        Returns:
            The Cognito sub (user ID in Cognito).

        Raises:
            ConflictError: If the email is already registered in Cognito.
        """

    @abstractmethod
    async def initiate_auth(self, email: str, password: str) -> TokenPair:
        """Authenticate a user via Cognito AdminInitiateAuth.

        Delegates credential verification to Cognito and returns the
        full token set on success.

        Args:
            email: The user's email address.
            password: The user's password.

        Returns:
            A TokenPair containing access_token, id_token,
            refresh_token, and expires_in.

        Raises:
            InvalidCredentialsError: If authentication fails (invalid
                email or password).
        """

    @abstractmethod
    async def refresh_auth(self, refresh_token: str) -> TokenPair:
        """Refresh tokens using a Cognito refresh_token.

        Calls Cognito with REFRESH_TOKEN_AUTH flow to obtain a new
        access_token and id_token without re-entering credentials.

        Args:
            refresh_token: The refresh token previously issued by Cognito.

        Returns:
            A TokenPair containing the new access_token, id_token,
            and expires_in. The refresh_token field may be empty
            since Cognito does not always issue a new one.

        Raises:
            InvalidCredentialsError: If the refresh token is invalid,
                expired, or the user has been disabled.
        """

    @abstractmethod
    async def global_sign_out(self, access_token: str) -> None:
        """Sign out a user globally by invalidating all tokens.

        Calls Cognito GlobalSignOut to revoke all tokens associated
        with the user's session.

        Args:
            access_token: A valid access token for the user to sign out.

        Raises:
            InvalidCredentialsError: If the access token is invalid or expired.
        """

    @abstractmethod
    async def admin_disable_user(self, cognito_sub: str) -> None:
        """Disable a user in Cognito to revoke all tokens.

        Used when deactivating a member to immediately invalidate
        all active sessions and tokens.

        Args:
            cognito_sub: The Cognito sub (user ID) to disable.
        """

    @abstractmethod
    async def admin_enable_user(self, cognito_sub: str) -> None:
        """Re-enable a previously disabled user in Cognito.

        Used when reactivating a member to restore their ability
        to authenticate.

        Args:
            cognito_sub: The Cognito sub (user ID) to enable.
        """
