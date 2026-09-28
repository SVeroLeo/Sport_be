"""Unit tests for the state token module.

**Validates: Requirements 2.4, 8.1, 8.2**

Covers specific examples and edge cases for ``generate_state`` and
``validate_state``:
- Valid token round-trip within the TTL.
- Expired token rejection.
- Tampered signature rejection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from api.socialLogin.stateToken import generate_state, validate_state
from api.common.errors.validationError import ValidationError

# ─── Constants ───────────────────────────────────────────────────────────────

SECRET = "unit-test-social-state-secret"
FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


# ─── Valid round-trip ────────────────────────────────────────────────────────


class TestValidRoundTrip:
    """A token validates against the same secret while within the TTL."""

    def test_round_trip_at_same_instant(self) -> None:
        """A token generated and validated at the same instant passes.

        **Validates: Requirements 2.4, 8.1**
        """
        token = generate_state(SECRET, now=FIXED_NOW)

        # Should not raise.
        validate_state(token, SECRET, now=FIXED_NOW)

    def test_round_trip_just_within_ttl(self) -> None:
        """A token validated just under the 10-minute TTL passes.

        **Validates: Requirements 8.2**
        """
        token = generate_state(SECRET, now=FIXED_NOW)
        later = FIXED_NOW + timedelta(minutes=10) - timedelta(seconds=1)

        # 599 seconds — strictly under the 600s TTL, must not raise.
        validate_state(token, SECRET, now=later)

    def test_token_has_expected_two_part_format(self) -> None:
        """A generated token is ``base64url(ts) + "." + hex(hmac)``.

        **Validates: Requirements 8.1**
        """
        token = generate_state(SECRET, now=FIXED_NOW)

        encoded_ts, separator, signature = token.partition(".")
        assert separator == "."
        assert encoded_ts
        assert signature
        # HMAC-SHA256 hex digest is always 64 characters.
        assert len(signature) == 64


# ─── Expired token ───────────────────────────────────────────────────────────


class TestExpiredToken:
    """A token older than the TTL is rejected."""

    def test_expired_token_raises(self) -> None:
        """A token validated after the TTL raises ValidationError.

        **Validates: Requirements 8.2**
        """
        token = generate_state(SECRET, now=FIXED_NOW)
        later = FIXED_NOW + timedelta(minutes=11)

        with pytest.raises(ValidationError):
            validate_state(token, SECRET, now=later)

    def test_token_at_exact_ttl_boundary_raises(self) -> None:
        """A token exactly at the 10-minute boundary raises (>= TTL rejected).

        **Validates: Requirements 8.2**
        """
        token = generate_state(SECRET, now=FIXED_NOW)
        boundary = FIXED_NOW + timedelta(minutes=10)

        with pytest.raises(ValidationError):
            validate_state(token, SECRET, now=boundary)


# ─── Tampered signature ──────────────────────────────────────────────────────


class TestTamperedSignature:
    """A token whose signature does not match the secret is rejected."""

    def test_tampered_signature_raises(self) -> None:
        """Flipping a signature character raises ValidationError.

        **Validates: Requirements 2.4, 8.1**
        """
        token = generate_state(SECRET, now=FIXED_NOW)
        encoded_ts, _, signature = token.partition(".")

        flipped = "0" if signature[0] != "0" else "1"
        tampered = f"{encoded_ts}.{flipped}{signature[1:]}"

        with pytest.raises(ValidationError):
            validate_state(tampered, SECRET, now=FIXED_NOW)

    def test_wrong_secret_raises(self) -> None:
        """Validating with a different secret raises ValidationError.

        **Validates: Requirements 2.4, 8.1**
        """
        token = generate_state(SECRET, now=FIXED_NOW)

        with pytest.raises(ValidationError):
            validate_state(token, "a-completely-different-secret", now=FIXED_NOW)

    def test_malformed_token_without_separator_raises(self) -> None:
        """A token missing the ``.`` separator raises ValidationError.

        **Validates: Requirements 8.1**
        """
        with pytest.raises(ValidationError):
            validate_state("no-separator-here", SECRET, now=FIXED_NOW)
