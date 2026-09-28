"""Unit tests for SocialCallbackUseCase.

Example-based tests covering the OAuth callback orchestration (the named
property tests for this use case — Properties covered by tasks 9.4-9.6 — live
in their own files; these are standard pytest example tests):

* An invalid/tampered ``state`` token raises ``ValidationError("invalid_state")``
  before the code is exchanged (Req 3.2, 3.3, 8.1, 8.2).
* An expired ``state`` token (older than the 10-minute TTL) raises
  ``ValidationError("invalid_state")`` (Req 3.3).
* A missing/invalid provider email raises
  ``ValidationError("invalid_provider_email")`` and creates no DynamoDB records
  (Req 8.4, 8.5).
* A brand-new social user (no cognito_sub match, no email match) routes to
  provisioning and is returned as ``requires_tenant_selection=True`` (Req 3.7,
  4.5, 7.4).
* An existing native user (email match) routes to provider linking and is not
  re-provisioned (Req 3.8, 6).
* A returning social user (cognito_sub match) is fast-pathed straight to their
  tokens without linking or provisioning (Req 3.7).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.socialLogin.socialLoginDtos import SocialLoginOutputDTO
from api.socialLogin import stateToken as state_token
from api.socialLogin.socialCallbackUseCase import SocialCallbackUseCase
from api.auth.tokenPair import TokenPair
from api.common.user.users import User
from api.common.errors.validationError import ValidationError

# ──── Constants ───────────────────────────────────────────────────────────────

STATE_SECRET = "test-state-secret-value"
REDIRECT_URI = "https://app.example.com/auth/social/callback"
HOSTED_UI_DOMAIN = "https://auth.example.com"
AUTH_CODE = "auth-code-abc123"

COGNITO_SUB = "google_1234567890abcdef"
USER_EMAIL = "social.user@example.com"
FULL_NAME = "Social User"
PROVIDER = "google"

EXISTING_USER_ID = "9f0c6a2e-1c3b-4d5e-8f7a-0b1c2d3e4f5a"
EXISTING_NATIVE_SUB = "native-cognito-sub-xyz"


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _b64url(data: bytes) -> str:
    """Base64url-encode without padding, matching the JWT payload convention."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_id_token(
    sub: str = COGNITO_SUB,
    email: str | None = USER_EMAIL,
    name: str = FULL_NAME,
    provider: str = PROVIDER,
) -> str:
    """Build a fake unsigned id_token (header.payload.sig) for the use case.

    The use case decodes only the middle (payload) segment as base64url JSON and
    ignores the signature, so a dummy header/signature is sufficient. When
    ``email`` is None the claim is omitted entirely to exercise the missing-email
    path.
    """
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode("utf-8"))
    claims: dict[str, object] = {
        "sub": sub,
        "name": name,
        "custom:provider": provider,
    }
    if email is not None:
        claims["email"] = email
    payload = _b64url(json.dumps(claims).encode("utf-8"))
    return f"{header}.{payload}.dummy-signature"


def build_token_pair(id_token: str) -> TokenPair:
    """Build the TokenPair returned by exchange_code_for_tokens."""
    return TokenPair(
        access_token="access-token-value",
        id_token=id_token,
        refresh_token="refresh-token-value",
        expires_in=3600,
    )


def make_user(
    *,
    user_id: str = EXISTING_USER_ID,
    email: str = USER_EMAIL,
    cognito_sub: str = EXISTING_NATIVE_SUB,
    status: str = "active",
    registration_type: str = "native",
    default_tenant_id: str | None = "550e8400-e29b-41d4-a716-446655440000",
) -> User:
    """Reconstitute a User entity for the existing-user routing paths."""
    return User.reconstitute(
        user_id=user_id,
        email=email,
        cognito_sub=cognito_sub,
        full_name="Existing User",
        status=status,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        default_tenant_id=default_tenant_id,
        registration_type=registration_type,
    )


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def user_repository() -> MagicMock:
    """Mock IUserRepository (sync methods).

    Defaults: no user found by cognito_sub or email (the new-user path). Tests
    override the return values as needed.
    """
    mock = MagicMock()
    mock.find_by_cognito_sub.return_value = None
    mock.find_by_email.return_value = None
    return mock


@pytest.fixture
def cognito_service() -> AsyncMock:
    """Mock ICognitoService (async methods)."""
    mock = AsyncMock()
    mock.exchange_code_for_tokens.return_value = build_token_pair(build_id_token())
    return mock


@pytest.fixture
def tenant_repository() -> MagicMock:
    """Mock ITenantRepository (unused in these routing paths)."""
    return MagicMock()


@pytest.fixture
def use_case(
    user_repository: MagicMock,
    cognito_service: AsyncMock,
    tenant_repository: MagicMock,
) -> SocialCallbackUseCase:
    """Create a SocialCallbackUseCase with mocked dependencies."""
    return SocialCallbackUseCase(
        user_repository=user_repository,
        cognito_service=cognito_service,
        tenant_repository=tenant_repository,
        redirect_uri=REDIRECT_URI,
        hosted_ui_domain=HOSTED_UI_DOMAIN,
        state_secret=STATE_SECRET,
    )


@pytest.fixture
def valid_state() -> str:
    """A freshly-signed, in-TTL state token for the happy-path tests."""
    return state_token.generate_state(STATE_SECRET)


# ──── Test: State Validation Rejection (Req 3.2, 3.3, 8.1, 8.2) ──────────────


class TestStateValidationRejection:
    """A tampered or expired state token is rejected before code exchange."""

    @pytest.mark.asyncio
    async def test_tampered_state_raises_validation_error(
        self,
        use_case: SocialCallbackUseCase,
    ) -> None:
        """A garbage/tampered state fails HMAC validation with 'invalid_state'."""
        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(code=AUTH_CODE, state="not-a-valid-token")

        assert exc_info.value.message == "invalid_state"

    @pytest.mark.asyncio
    async def test_tampered_signature_raises_validation_error(
        self,
        use_case: SocialCallbackUseCase,
        valid_state: str,
    ) -> None:
        """A valid timestamp with a corrupted signature is rejected."""
        encoded_ts, _, _ = valid_state.partition(".")
        tampered = f"{encoded_ts}.deadbeef"

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(code=AUTH_CODE, state=tampered)

        assert exc_info.value.message == "invalid_state"

    @pytest.mark.asyncio
    async def test_invalid_state_does_not_exchange_code(
        self,
        use_case: SocialCallbackUseCase,
        cognito_service: AsyncMock,
    ) -> None:
        """State validation short-circuits before the token exchange (Req 3.2)."""
        with pytest.raises(ValidationError):
            await use_case.execute(code=AUTH_CODE, state="garbage")

        cognito_service.exchange_code_for_tokens.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_state_raises_validation_error(
        self,
        use_case: SocialCallbackUseCase,
        cognito_service: AsyncMock,
    ) -> None:
        """A state older than the 10-minute TTL is rejected as 'invalid_state'."""
        # Sign a token stamped 11 minutes in the past; validate_state uses the
        # current time (no `now` override in the use case), so it is expired.
        past = datetime.now(UTC) - timedelta(minutes=11)
        expired_state = state_token.generate_state(STATE_SECRET, now=past)

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(code=AUTH_CODE, state=expired_state)

        assert exc_info.value.message == "invalid_state"
        cognito_service.exchange_code_for_tokens.assert_not_awaited()


# ──── Test: Provider Email Validation (Req 8.4, 8.5) ─────────────────────────


class TestProviderEmailValidation:
    """A missing or invalid provider email is rejected with no DynamoDB write."""

    @pytest.mark.asyncio
    async def test_missing_email_raises_invalid_provider_email(
        self,
        use_case: SocialCallbackUseCase,
        cognito_service: AsyncMock,
        valid_state: str,
    ) -> None:
        """An id_token without an email claim raises 'invalid_provider_email'."""
        cognito_service.exchange_code_for_tokens.return_value = build_token_pair(
            build_id_token(email=None)
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(code=AUTH_CODE, state=valid_state)

        assert exc_info.value.message == "invalid_provider_email"

    @pytest.mark.asyncio
    async def test_malformed_email_raises_invalid_provider_email(
        self,
        use_case: SocialCallbackUseCase,
        cognito_service: AsyncMock,
        valid_state: str,
    ) -> None:
        """A syntactically invalid email is rejected as 'invalid_provider_email'."""
        cognito_service.exchange_code_for_tokens.return_value = build_token_pair(
            build_id_token(email="not-an-email")
        )

        with pytest.raises(ValidationError) as exc_info:
            await use_case.execute(code=AUTH_CODE, state=valid_state)

        assert exc_info.value.message == "invalid_provider_email"

    @pytest.mark.asyncio
    async def test_invalid_email_does_not_persist(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        cognito_service: AsyncMock,
        valid_state: str,
    ) -> None:
        """No DynamoDB records are created when the provider email is invalid."""
        cognito_service.exchange_code_for_tokens.return_value = build_token_pair(
            build_id_token(email=None)
        )

        with pytest.raises(ValidationError):
            await use_case.execute(code=AUTH_CODE, state=valid_state)

        user_repository.register_social_user.assert_not_called()


# ──── Test: New User Routing -> Provisioning (Req 3.7, 4.5, 7.4) ─────────────


class TestNewUserRouting:
    """No cognito_sub and no email match routes to provisioning."""

    @pytest.mark.asyncio
    async def test_new_user_provisions_and_requires_tenant_selection(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        valid_state: str,
    ) -> None:
        """A new social user is provisioned and flagged for tenant selection."""
        user_repository.find_by_cognito_sub.return_value = None
        user_repository.find_by_email.return_value = None

        result = await use_case.execute(code=AUTH_CODE, state=valid_state)

        assert isinstance(result, SocialLoginOutputDTO)
        # register_social_user is the atomic provisioning write.
        user_repository.register_social_user.assert_called_once()
        # A pending-tenant user must select a tenant before full access.
        assert result.requires_tenant_selection is True

    @pytest.mark.asyncio
    async def test_new_user_provisioned_as_pending_tenant_social(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        valid_state: str,
    ) -> None:
        """The provisioned User is a pending-tenant, social-registration user."""
        await use_case.execute(code=AUTH_CODE, state=valid_state)

        _, kwargs = user_repository.register_social_user.call_args
        provisioned_user = kwargs["user"]
        assert provisioned_user.status == "pending_tenant"
        assert provisioned_user.registration_type == "social"
        assert provisioned_user.default_tenant_id is None
        # No tenant resolved -> membership/member/role omitted (Req 4.5).
        assert kwargs["membership"] is None
        assert kwargs["member"] is None
        assert kwargs["role"] is None

    @pytest.mark.asyncio
    async def test_new_user_does_not_link_provider(
        self,
        use_case: SocialCallbackUseCase,
        cognito_service: AsyncMock,
        valid_state: str,
    ) -> None:
        """The provisioning path never links a provider (that is the native path)."""
        await use_case.execute(code=AUTH_CODE, state=valid_state)

        cognito_service.admin_link_provider_for_user.assert_not_awaited()


# ──── Test: Existing Native User -> Linking (Req 3.8, 6) ─────────────────────


class TestExistingNativeUserRouting:
    """No cognito_sub match but an email match routes to provider linking."""

    @pytest.mark.asyncio
    async def test_existing_native_user_links_provider(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        cognito_service: AsyncMock,
        valid_state: str,
    ) -> None:
        """An existing native user has the social provider linked to their account."""
        native_user = make_user(registration_type="native", status="active")
        user_repository.find_by_cognito_sub.return_value = None
        user_repository.find_by_email.return_value = native_user

        await use_case.execute(code=AUTH_CODE, state=valid_state)

        cognito_service.admin_link_provider_for_user.assert_awaited_once()
        _, kwargs = cognito_service.admin_link_provider_for_user.call_args
        # Link into the EXISTING native user; the federated identity is the source.
        assert kwargs["destination_cognito_sub"] == EXISTING_NATIVE_SUB
        assert kwargs["provider_name"] == "Google"
        assert kwargs["provider_user_id"] == COGNITO_SUB

    @pytest.mark.asyncio
    async def test_existing_native_user_not_reprovisioned(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        valid_state: str,
    ) -> None:
        """Linking creates no new DynamoDB records (Req 6.3)."""
        user_repository.find_by_cognito_sub.return_value = None
        user_repository.find_by_email.return_value = make_user()

        await use_case.execute(code=AUTH_CODE, state=valid_state)

        user_repository.register_social_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_active_native_user_no_tenant_selection(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        valid_state: str,
    ) -> None:
        """An active linked user does not require tenant selection."""
        user_repository.find_by_cognito_sub.return_value = None
        user_repository.find_by_email.return_value = make_user(status="active")

        result = await use_case.execute(code=AUTH_CODE, state=valid_state)

        assert result.requires_tenant_selection is False


# ──── Test: Existing Social User -> Fast Path (Req 3.7) ──────────────────────


class TestExistingSocialUserFastPath:
    """A cognito_sub match fast-paths straight to the tokens."""

    @pytest.mark.asyncio
    async def test_existing_social_user_returns_tokens(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        valid_state: str,
    ) -> None:
        """A returning social user is returned their token set directly."""
        social_user = make_user(
            cognito_sub=COGNITO_SUB,
            registration_type="social",
            status="active",
        )
        user_repository.find_by_cognito_sub.return_value = social_user

        result = await use_case.execute(code=AUTH_CODE, state=valid_state)

        assert isinstance(result, SocialLoginOutputDTO)
        assert result.access_token == "access-token-value"
        assert result.user_id == EXISTING_USER_ID

    @pytest.mark.asyncio
    async def test_existing_social_user_no_link_or_provision(
        self,
        use_case: SocialCallbackUseCase,
        user_repository: MagicMock,
        cognito_service: AsyncMock,
        valid_state: str,
    ) -> None:
        """The fast path neither links a provider nor provisions records."""
        user_repository.find_by_cognito_sub.return_value = make_user(
            cognito_sub=COGNITO_SUB, registration_type="social"
        )

        await use_case.execute(code=AUTH_CODE, state=valid_state)

        cognito_service.admin_link_provider_for_user.assert_not_awaited()
        user_repository.register_social_user.assert_not_called()
        # The email lookup is skipped once the sub match short-circuits.
        user_repository.find_by_email.assert_not_called()
