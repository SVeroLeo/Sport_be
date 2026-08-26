"""Property-based tests for Password Storage Security.

**Validates: Requirements 13.1, 13.2, 13.4, 4.7**

Property 10: Password Storage Security
- For any password, the system never stores plain-text passwords in DynamoDB.
- The Password value object never reveals the actual password in string representations.
- Passwords outside 8-72 chars are rejected at the domain boundary before reaching Cognito.
- CognitoAuthService only forwards passwords to Cognito for sign_up and initiate_auth;
  admin_create_user does NOT receive a password (Cognito auto-generates one).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from domain.errors.validation_error import ValidationError
from domain.value_objects.password import MAX_LENGTH, MIN_LENGTH, Password
from infrastructure.auth.cognito_auth_service import CognitoAuthService


# ─── Strategies ───────────────────────────────────────────────────────────────

# Passwords within the valid range (8-72 chars)
valid_passwords = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=MIN_LENGTH,
    max_size=MAX_LENGTH,
).filter(lambda s: len(s) >= MIN_LENGTH)

# Passwords that are too short (1-7 chars)
too_short_passwords = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=MIN_LENGTH - 1,
)

# Passwords that are too long (73+ chars, up to 200 for generation limits)
too_long_passwords = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=MAX_LENGTH + 1,
    max_size=200,
)

# Valid email addresses
valid_emails = st.emails().filter(lambda e: len(e.strip()) <= 254)

# Valid full names (non-empty, max 200 chars)
valid_full_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "Zs")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)


# ─── Property: Password is never revealed in string representations ───────────


class TestPasswordNeverRevealedInStringRepresentation:
    """Property: The Password value object NEVER reveals the actual password
    in __repr__ or __str__.

    This prevents accidental leakage in logs, error messages, or debugging output.

    **Validates: Requirements 13.2**
    """

    @given(password_text=valid_passwords)
    @settings(max_examples=200)
    def test_repr_never_contains_password_value(
        self,
        password_text: str,
    ) -> None:
        """For ANY valid password, repr(Password) NEVER contains the actual value.

        **Validates: Requirements 13.2**
        """
        pwd = Password.create(password_text)

        representation = repr(pwd)

        # The repr must be the masked constant, never the actual password
        assert representation == "Password(***)"
        assert password_text not in representation

    @given(password_text=valid_passwords)
    @settings(max_examples=200)
    def test_str_never_contains_password_value(
        self,
        password_text: str,
    ) -> None:
        """For ANY valid password, str(Password) NEVER contains the actual value.

        **Validates: Requirements 13.2**
        """
        pwd = Password.create(password_text)

        string_value = str(pwd)

        # The str must be the masked constant, never the actual password
        assert string_value == "***"
        assert password_text not in string_value

    @given(password_text=valid_passwords)
    @settings(max_examples=200)
    def test_format_never_contains_password_value(
        self,
        password_text: str,
    ) -> None:
        """For ANY valid password, formatting Password in an f-string NEVER
        reveals the actual value.

        **Validates: Requirements 13.2**
        """
        pwd = Password.create(password_text)

        formatted = f"User password: {pwd}"

        assert password_text not in formatted
        assert "***" in formatted


# ─── Property: Password validation boundary ──────────────────────────────────


class TestPasswordValidationBoundary:
    """Property: Passwords outside 8-72 chars are ALWAYS rejected at the domain
    boundary before reaching Cognito. Passwords within 8-72 chars ALWAYS pass.

    **Validates: Requirements 13.1, 13.3 (via design: domain enforces length)**
    """

    @given(password_text=too_short_passwords)
    @settings(max_examples=200)
    def test_passwords_shorter_than_min_are_always_rejected(
        self,
        password_text: str,
    ) -> None:
        """For ANY password shorter than 8 characters, the domain boundary
        ALWAYS raises ValidationError.

        **Validates: Requirements 13.1**
        """
        with pytest.raises(ValidationError) as exc_info:
            Password.create(password_text)

        assert "password" in exc_info.value.field.lower()

    @given(password_text=too_long_passwords)
    @settings(max_examples=200)
    def test_passwords_longer_than_max_are_always_rejected(
        self,
        password_text: str,
    ) -> None:
        """For ANY password longer than 72 characters, the domain boundary
        ALWAYS raises ValidationError.

        **Validates: Requirements 13.1**
        """
        with pytest.raises(ValidationError) as exc_info:
            Password.create(password_text)

        assert "password" in exc_info.value.field.lower()

    @given(password_text=valid_passwords)
    @settings(max_examples=200)
    def test_passwords_within_valid_range_always_pass_domain_boundary(
        self,
        password_text: str,
    ) -> None:
        """For ANY password between 8-72 characters, the domain boundary
        ALWAYS accepts it (returning a Password value object).

        **Validates: Requirements 13.1**
        """
        pwd = Password.create(password_text)

        assert pwd.value == password_text


# ─── Property: Password is never stored in DynamoDB ──────────────────────────


class TestPasswordNeverStoredInDynamoDB:
    """Property: For any valid password, after sign_up via CognitoAuthService,
    the password is forwarded ONLY to Cognito and NEVER appears in any DynamoDB
    write operation.

    **Validates: Requirements 13.2, 13.4**
    """

    @given(
        email=valid_emails,
        password_text=valid_passwords,
        full_name=valid_full_names,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_sign_up_forwards_password_only_to_cognito(
        self,
        email: str,
        password_text: str,
        full_name: str,
    ) -> None:
        """For ANY valid password, sign_up sends the password to Cognito's SignUp
        API only and never to a DynamoDB write operation.

        **Validates: Requirements 13.2, 13.4**
        """
        # Arrange: mock the cognito-idp client
        mock_client = MagicMock()
        mock_client.sign_up.return_value = {"UserSub": "test-sub-123"}

        service = CognitoAuthService(
            user_pool_id="us-east-1_TestPool",
            client_id="test-client-id",
            client=mock_client,
        )

        # Act
        await service.sign_up(email, password_text, full_name)

        # Assert: password was forwarded to Cognito sign_up
        mock_client.sign_up.assert_called_once()
        call_kwargs = mock_client.sign_up.call_args
        assert call_kwargs.kwargs["Password"] == password_text

        # Assert: no DynamoDB operations were invoked (put_item, transact_write_items, etc.)
        # The CognitoAuthService should ONLY interact with Cognito, never with DynamoDB
        assert not hasattr(mock_client, "put_item") or not mock_client.put_item.called
        assert not hasattr(mock_client, "transact_write_items") or not mock_client.transact_write_items.called

    @given(
        email=valid_emails,
        password_text=valid_passwords,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_initiate_auth_forwards_password_only_to_cognito(
        self,
        email: str,
        password_text: str,
    ) -> None:
        """For ANY valid password, initiate_auth sends the password to Cognito's
        AdminInitiateAuth API only and never stores it anywhere.

        **Validates: Requirements 13.2, 13.4**
        """
        # Arrange
        mock_client = MagicMock()
        mock_client.admin_initiate_auth.return_value = {
            "AuthenticationResult": {
                "AccessToken": "access-token",
                "IdToken": "id-token",
                "RefreshToken": "refresh-token",
                "ExpiresIn": 3600,
            }
        }

        service = CognitoAuthService(
            user_pool_id="us-east-1_TestPool",
            client_id="test-client-id",
            client=mock_client,
        )

        # Act
        await service.initiate_auth(email, password_text)

        # Assert: password was forwarded to Cognito
        mock_client.admin_initiate_auth.assert_called_once()
        call_kwargs = mock_client.admin_initiate_auth.call_args
        auth_params = call_kwargs.kwargs["AuthParameters"]
        assert auth_params["PASSWORD"] == password_text

        # Assert: no DynamoDB operations
        assert not hasattr(mock_client, "put_item") or not mock_client.put_item.called
        assert not hasattr(mock_client, "transact_write_items") or not mock_client.transact_write_items.called


# ─── Property: admin_create_user does NOT receive a password ─────────────────


class TestAdminCreateUserNoPasswordForwarded:
    """Property: CognitoAuthService.admin_create_user does NOT accept or forward
    a password parameter. Cognito auto-generates a temporary password.

    **Validates: Requirements 4.7, 13.4**
    """

    @given(
        email=valid_emails,
        full_name=valid_full_names,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_admin_create_user_never_receives_password(
        self,
        email: str,
        full_name: str,
    ) -> None:
        """For ANY admin_create_user call, no password is forwarded to Cognito.
        Cognito generates its own temporary password automatically.

        **Validates: Requirements 4.7, 13.4**
        """
        # Arrange
        mock_client = MagicMock()
        mock_client.admin_create_user.return_value = {
            "User": {
                "Username": email,
                "Attributes": [
                    {"Name": "sub", "Value": "cognito-sub-generated"},
                    {"Name": "email", "Value": email},
                ],
            }
        }

        service = CognitoAuthService(
            user_pool_id="us-east-1_TestPool",
            client_id="test-client-id",
            client=mock_client,
        )

        # Act
        await service.admin_create_user(email, full_name)

        # Assert: admin_create_user was called without a Password parameter
        mock_client.admin_create_user.assert_called_once()
        call_kwargs = mock_client.admin_create_user.call_args

        # The kwargs must NOT contain 'TemporaryPassword' — Cognito generates it
        all_kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert "TemporaryPassword" not in all_kwargs

        # Also check positional args don't sneak a password in
        # The call should only contain UserPoolId, Username, UserAttributes, DesiredDeliveryMediums
        expected_keys = {"UserPoolId", "Username", "UserAttributes", "DesiredDeliveryMediums"}
        assert set(all_kwargs.keys()).issubset(expected_keys)

    @given(
        email=valid_emails,
        full_name=valid_full_names,
        password_text=valid_passwords,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_admin_create_user_signature_does_not_accept_password(
        self,
        email: str,
        full_name: str,
        password_text: str,
    ) -> None:
        """The ICognitoService.admin_create_user port signature only accepts
        email and full_name — there is no password parameter. Any password
        passed by the caller would be a type error.

        **Validates: Requirements 4.7, 13.4**
        """
        import inspect

        from application.ports.i_cognito_service import ICognitoService

        sig = inspect.signature(ICognitoService.admin_create_user)
        params = list(sig.parameters.keys())

        # Should only have self, email, full_name — no password param
        assert "password" not in params
        assert "temp_password" not in params
        assert "temporary_password" not in params

        # Confirm the exact parameters (self, email, full_name)
        assert params == ["self", "email", "full_name"]
