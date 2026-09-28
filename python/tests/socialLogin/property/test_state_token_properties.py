"""Property-based tests for the state token module.

**Validates: Requirements 2.4, 3.2, 8.1, 8.2**

Properties tested:
- Feature: social-login, Property 1: State token HMAC integrity round-trip
- Feature: social-login, Property 2: State token TTL enforcement
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from api.socialLogin.stateToken import generate_state, validate_state
from api.common.errors.validationError import ValidationError

# ─── Constants ───────────────────────────────────────────────────────────────

SECRET = "test-social-state-secret-value"

# The 10-minute TTL window enforced by the module (rejected when >= 600s).
_TTL_SECONDS = 600


# ─── Strategies ──────────────────────────────────────────────────────────────

# Arbitrary timezone-aware UTC timestamps. Bounds are well within datetime's
# representable range so isoformat / fromisoformat round-trips cleanly.
_utc_datetimes = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
).map(lambda dt: dt.replace(tzinfo=UTC))


# ─── Property 1: State token HMAC integrity round-trip ───────────────────────


class TestStateTokenHmacIntegrity:
    """Feature: social-login, Property 1: State token HMAC integrity round-trip.

    For ANY UTC timestamp within the valid window, a freshly generated token
    validates successfully against the same secret and instant. Mutating a
    single character of the signature half ALWAYS causes validation to fail.

    **Validates: Requirements 2.4, 3.2, 8.1**
    """

    @given(ts=_utc_datetimes)
    @settings(max_examples=200)
    def test_generated_token_validates_within_window(self, ts: datetime) -> None:
        """A token generated at ``ts`` validates at the same instant.

        **Validates: Requirements 2.4, 3.2, 8.1**
        """
        token = generate_state(SECRET, now=ts)

        # Should not raise — the signature matches and TTL is 0 seconds.
        validate_state(token, SECRET, now=ts)

    @given(ts=_utc_datetimes, mutate_index=st.integers(min_value=0))
    @settings(max_examples=200)
    def test_mutated_signature_rejected(self, ts: datetime, mutate_index: int) -> None:
        """Mutating one character of the signature half raises ValidationError.

        **Validates: Requirements 2.4, 3.2, 8.1**
        """
        token = generate_state(SECRET, now=ts)
        encoded_ts, _, signature = token.partition(".")

        # Pick a deterministic position within the signature to mutate.
        pos = mutate_index % len(signature)
        original_char = signature[pos]
        # Hex signature — flip to a guaranteed-different hex digit.
        replacement = "0" if original_char != "0" else "1"
        mutated_signature = signature[:pos] + replacement + signature[pos + 1 :]

        assert mutated_signature != signature
        tampered_token = f"{encoded_ts}.{mutated_signature}"

        with pytest.raises(ValidationError):
            validate_state(tampered_token, SECRET, now=ts)


# ─── Property 2: State token TTL enforcement ─────────────────────────────────


class TestStateTokenTtlEnforcement:
    """Feature: social-login, Property 2: State token TTL enforcement.

    A token generated at time ``T`` validates at ``T + delta`` if and only if
    ``delta`` is strictly less than the 10-minute (600 second) TTL. At or beyond
    the TTL boundary, validation ALWAYS raises ValidationError.

    **Validates: Requirements 8.2**
    """

    @given(
        ts=_utc_datetimes,
        delta=st.timedeltas(
            min_value=timedelta(seconds=0),
            max_value=timedelta(hours=24),
        ),
    )
    @settings(max_examples=200)
    def test_validation_passes_iff_within_ttl(
        self,
        ts: datetime,
        delta: timedelta,
    ) -> None:
        """Validation succeeds iff ``delta.total_seconds() < 600``.

        **Validates: Requirements 8.2**
        """
        token = generate_state(SECRET, now=ts)
        validate_at = ts + delta

        if delta.total_seconds() < _TTL_SECONDS:
            # Within TTL — must not raise.
            validate_state(token, SECRET, now=validate_at)
        else:
            # At or beyond TTL — must raise.
            with pytest.raises(ValidationError):
                validate_state(token, SECRET, now=validate_at)
