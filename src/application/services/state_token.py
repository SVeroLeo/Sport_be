"""State token service — CSRF-protection tokens for the social login OAuth flow.

A state token is a signed, timestamped value passed through the OAuth
authorize/callback round-trip. It provides CSRF protection and a bounded
lifetime without requiring any external store.

Format::

    state = base64url(timestamp_utc_iso8601) + "." + hex(hmac_sha256(secret, timestamp_utc_iso8601))

Validation recomputes the HMAC in constant time and enforces a 10-minute TTL.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from domain.errors.validation_error import ValidationError

# Maximum age of a state token before it is considered expired.
_STATE_TTL = timedelta(minutes=10)

# Error code raised for any tampered, malformed, or expired token.
_INVALID_STATE = "invalid_state"


def _sign(secret: str, timestamp_iso: str) -> str:
    """Return the hex-encoded HMAC-SHA256 of ``timestamp_iso`` keyed by ``secret``."""
    return hmac.new(
        secret.encode("utf-8"),
        timestamp_iso.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_state(secret: str, now: datetime | None = None) -> str:
    """Generate a signed state token for the OAuth authorize step.

    Args:
        secret: HMAC signing key (``SOCIAL_STATE_SECRET``).
        now: UTC timestamp to embed. Defaults to the current UTC time.

    Returns:
        A ``base64url(timestamp) + "." + hex(hmac)`` state token.
    """
    if now is None:
        now = datetime.now(UTC)

    timestamp_iso = now.isoformat()
    encoded_ts = base64.urlsafe_b64encode(timestamp_iso.encode("utf-8")).decode("ascii")
    signature = _sign(secret, timestamp_iso)
    return f"{encoded_ts}.{signature}"


def validate_state(token: str, secret: str, now: datetime | None = None) -> None:
    """Validate a state token's signature and TTL.

    Args:
        token: The state token returned from the OAuth callback.
        secret: HMAC signing key (``SOCIAL_STATE_SECRET``).
        now: UTC timestamp to validate against. Defaults to the current UTC time.

    Raises:
        ValidationError: With code ``"invalid_state"`` if the token is
            malformed, the signature does not match, or the token is older
            than the 10-minute TTL.
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Split into the encoded timestamp and signature halves.
    encoded_ts, separator, signature = token.partition(".")
    if not separator or not encoded_ts or not signature:
        raise ValidationError(_INVALID_STATE)

    # 2. Decode the timestamp half.
    try:
        timestamp_iso = base64.urlsafe_b64decode(encoded_ts.encode("ascii")).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(_INVALID_STATE) from exc

    # 3. Recompute the expected HMAC and compare in constant time.
    expected_signature = _sign(secret, timestamp_iso)
    if not hmac.compare_digest(expected_signature, signature):
        raise ValidationError(_INVALID_STATE)

    # 4. Parse the timestamp and enforce the TTL.
    try:
        timestamp = datetime.fromisoformat(timestamp_iso)
    except ValueError as exc:
        raise ValidationError(_INVALID_STATE) from exc

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    if now - timestamp >= _STATE_TTL:
        raise ValidationError(_INVALID_STATE)
