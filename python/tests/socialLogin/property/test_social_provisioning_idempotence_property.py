"""Property-based tests for SocialCallbackUseCase._provision_new_user.

Feature: social-login, Property 5: Social user provisioning idempotence and
field correctness.

Validates: Requirements 4.1, 4.2, 4.3, 4.6, 4.7, 9.1, 9.2

Property 5 states that provisioning a brand-new social user is idempotent and
writes the User record with the correct fields. Concretely, for any
(cognito_sub, email, full_name) triple:

* Calling ``_provision_new_user`` N times (N in 1..5) never raises — duplicate
  writes are silently absorbed by the repository's idempotent
  ``register_social_user`` (which swallows the DynamoDB ConditionalCheckFailed
  on the second and later calls). The use case therefore issues one
  ``register_social_user`` call per invocation and does not surface an error.
* Every ``User`` handed to ``register_social_user`` carries
  ``registration_type="social"`` (Req 4.1, 4.2), the exact ``cognito_sub`` that
  was passed in (Req 4.3, 9.1), and the normalized provider email (Req 4.6,
  4.7, 9.2). It is created in the ``pending_tenant`` status with no default
  tenant (Req 4.5), and the membership/member/role records are omitted
  (passed as ``None``) since no tenant is resolved.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api.socialLogin.socialCallbackUseCase import SocialCallbackUseCase
from api.common.user.user import User
from api.common.valueObjects.email import Email

# ──── Generators ───────────────────────────────────────────────────────────────

# Local part of an email using a safe subset of RFC 5322 characters that always
# survives Email.create normalization (trim + lowercase) unchanged after we
# lowercase it ourselves.
_local_part = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=1,
    max_size=20,
)

# A single DNS label: starts and ends alphanumeric, hyphens allowed inside.
_domain_label = st.from_regex(r"[a-z0-9](?:[a-z0-9-]{0,10}[a-z0-9])?", fullmatch=True)


@st.composite
def _emails(draw: st.DrawFn) -> str:
    """Generate raw email strings that pass Email.create validation."""
    local = draw(_local_part)
    labels = draw(st.lists(_domain_label, min_size=2, max_size=3))
    domain = ".".join(labels)
    # Constrain total length well under the 254-char cap.
    return f"{local}@{domain}"


# cognito_sub: non-empty printable identifier (Cognito subs are UUID-like, but
# the use case treats them as opaque strings, so exercise a broader space).
_cognito_subs = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=1,
    max_size=40,
)

# full_name: non-empty after trimming, <= 200 chars (FullName constraints).
_full_names = st.text(min_size=1, max_size=50).filter(lambda s: bool(s.strip()))

_providers = st.sampled_from(["google", "facebook"])

# Number of times provisioning is invoked for the same identity.
_call_counts = st.integers(min_value=1, max_value=5)


def _build_use_case() -> tuple[SocialCallbackUseCase, MagicMock, AsyncMock]:
    """Construct the use case with a mocked (idempotent, no-op) repository.

    The repository's ``register_social_user`` is a plain MagicMock no-op: this
    represents the idempotent write, where the underlying
    ConditionalCheckFailedException on duplicate calls is swallowed and never
    reaches the use case.
    """
    user_repository = MagicMock()
    # Idempotent write: the real repository swallows ConditionalCheckFailed on
    # duplicate calls, so from the use case's perspective it is a silent no-op.
    user_repository.register_social_user = MagicMock(return_value=None)

    cognito_service = AsyncMock()
    tenant_repository = MagicMock()

    use_case = SocialCallbackUseCase(
        user_repository=user_repository,
        cognito_service=cognito_service,
        tenant_repository=tenant_repository,
        redirect_uri="https://app.example.com/callback",
        hosted_ui_domain="auth.example.com",
        state_secret="test-secret",
    )
    return use_case, user_repository, cognito_service


@pytest.mark.asyncio
@given(
    raw_email=_emails(),
    cognito_sub=_cognito_subs,
    full_name=_full_names,
    provider=_providers,
    call_count=_call_counts,
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_social_provisioning_is_idempotent_and_fields_correct(
    raw_email: str,
    cognito_sub: str,
    full_name: str,
    provider: str,
    call_count: int,
) -> None:
    """Property 5: provisioning is idempotent and writes correct fields.

    Feature: social-login, Property 5: Social user provisioning idempotence and
    field correctness.

    Validates: Requirements 4.1, 4.2, 4.3, 4.6, 4.7, 9.1, 9.2
    """
    use_case, user_repository, cognito_service = _build_use_case()
    email = Email.create(raw_email)

    # Invoke provisioning N times for the SAME identity. The idempotent
    # repository absorbs duplicate writes, so no call raises (Req 4.6, 4.7).
    returned_users: list[User] = []
    for _ in range(call_count):
        user = await use_case._provision_new_user(
            cognito_sub=cognito_sub,
            email=email,
            full_name=full_name,
            provider=provider,
        )
        returned_users.append(user)

    # register_social_user is invoked once per call, and every duplicate is
    # silently skipped (no exception surfaces) — idempotence holds.
    assert user_repository.register_social_user.call_count == call_count

    # Field correctness: inspect the User passed to every register_social_user
    # call. Each must be a social registration with the exact cognito_sub and
    # the normalized email (Req 4.1, 4.2, 4.3, 9.1, 9.2).
    for call in user_repository.register_social_user.call_args_list:
        written_user: User = call.kwargs["user"]
        assert written_user.registration_type == "social"
        assert written_user.cognito_sub == cognito_sub
        assert written_user.email.value == email.value
        assert written_user.email.value == raw_email.strip().lower()
        # No tenant resolved -> pending_tenant, no default tenant (Req 4.5).
        assert written_user.status == "pending_tenant"
        assert written_user.default_tenant_id is None
        # Membership/member/role omitted since no tenant is resolved.
        assert call.kwargs["membership"] is None
        assert call.kwargs["member"] is None
        assert call.kwargs["role"] is None

    # Every returned user reflects the same correct fields.
    for written_user in returned_users:
        assert written_user.registration_type == "social"
        assert written_user.cognito_sub == cognito_sub
        assert written_user.email.value == email.value
