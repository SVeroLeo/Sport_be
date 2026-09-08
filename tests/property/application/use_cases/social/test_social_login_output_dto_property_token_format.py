"""Property-based test for SocialLoginOutputDTO token response format.

**Validates: Requirements 7.1, 7.3**

Property tested:
- Feature: social-login, Property 8: Token response format consistency

This file is intentionally dedicated to Property 8 only, keeping it isolated
from the sibling property tests so the tasks can be implemented independently.

For any ``SocialLoginOutputDTO`` — regardless of the random token strings,
``user_id``, ``expires_in`` value, or ``requires_tenant_selection`` flag — the
serialized JSON body ALWAYS contains the five required keys ``access_token``,
``id_token``, ``refresh_token``, ``expires_in`` and ``user_id``, each with a
non-null value. This mirrors the shape of the existing ``POST /auth/login``
response (Requirement 7.1) plus the internal ``user_id`` (Requirement 7.3).
"""

from __future__ import annotations

import json

import hypothesis.strategies as st
from hypothesis import given, settings

from application.dtos.social_login_dtos import SocialLoginOutputDTO

# ─── Constants ───────────────────────────────────────────────────────────────

# The five keys the social login response body must always carry.
_REQUIRED_KEYS = (
    "access_token",
    "id_token",
    "refresh_token",
    "expires_in",
    "user_id",
)


# ─── Strategies ──────────────────────────────────────────────────────────────

# Arbitrary text (including empty strings, whitespace, and unicode) for the
# token fields and user_id — the format contract must hold for any string.
_tokens = st.text()

# expires_in is an integer count of seconds; allow the full integer range,
# including zero and negatives, since the format contract is about presence
# and non-nullness, not value bounds.
_expires_in = st.integers()

_flags = st.booleans()


# ─── Property 8: Token response format consistency ───────────────────────────


class TestTokenResponseFormatConsistency:
    """Feature: social-login, Property 8: Token response format consistency.

    For ANY ``SocialLoginOutputDTO`` built from arbitrary token strings,
    ``user_id``, ``expires_in`` and ``requires_tenant_selection`` values, the
    serialized JSON ALWAYS contains ``access_token``, ``id_token``,
    ``refresh_token``, ``expires_in`` and ``user_id`` with non-null values.

    **Validates: Requirements 7.1, 7.3**
    """

    @given(
        access_token=_tokens,
        id_token=_tokens,
        refresh_token=_tokens,
        expires_in=_expires_in,
        user_id=_tokens,
        requires_tenant_selection=_flags,
    )
    @settings(max_examples=100)
    def test_serialized_json_contains_required_keys_non_null(
        self,
        access_token: str,
        id_token: str,
        refresh_token: str,
        expires_in: int,
        user_id: str,
        requires_tenant_selection: bool,
    ) -> None:
        """Serialized JSON carries all five keys with non-null values.

        **Validates: Requirements 7.1, 7.3**
        """
        dto = SocialLoginOutputDTO(
            access_token=access_token,
            id_token=id_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user_id=user_id,
            requires_tenant_selection=requires_tenant_selection,
        )

        # Pydantic v2 serialization to a JSON string, then inspect via json.loads.
        body = json.loads(dto.model_dump_json())

        for key in _REQUIRED_KEYS:
            assert key in body, f"missing required key: {key!r}"
            assert body[key] is not None, f"required key is null: {key!r}"
