"""Unit tests for the per-issuer JWKS provider.

Covers the three cache behaviors required by the multi-region RS256 design:
cache hit (no refetch within TTL), TTL expiry (refetch when stale), and
unknown-``kid`` refresh (refetch once on key rotation). An injectable fetcher
and clock keep the tests network-free and deterministic.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from api.common.auth.jwksProvider import (
    JWKSProvider,
    _jwks_uri_for_issuer,
    get_jwks_provider,
)

# ──── Constants ───────────────────────────────────────────────────────────────

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123"
ISSUER_EU = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_xyz789"


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_jwk(kid: str) -> dict[str, Any]:
    """Generate an RSA public JWK dict with the given ``kid``."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk_json = RSAAlgorithm.to_jwk(private_key.public_key())
    jwk: dict[str, Any] = json.loads(jwk_json)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return jwk


def _jwks_document(*kids: str) -> dict[str, Any]:
    """Build a JWKS document containing keys for the given ``kids``."""
    return {"keys": [_make_jwk(kid) for kid in kids]}


class _RecordingFetcher:
    """A fetcher stub that returns a scripted document and counts calls."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.call_count = 0
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict[str, Any]:
        self.call_count += 1
        self.urls.append(url)
        return self.document


class _MutableClock:
    """A controllable clock for driving TTL expiry deterministically."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ──── URL construction ────────────────────────────────────────────────────────


def test_jwks_uri_for_issuer_appends_well_known_path() -> None:
    assert _jwks_uri_for_issuer(ISSUER) == f"{ISSUER}/.well-known/jwks.json"


def test_jwks_uri_for_issuer_strips_trailing_slash() -> None:
    assert _jwks_uri_for_issuer(ISSUER + "/") == f"{ISSUER}/.well-known/jwks.json"


# ──── Cache hit ───────────────────────────────────────────────────────────────


def test_first_lookup_fetches_and_returns_key() -> None:
    fetcher = _RecordingFetcher(_jwks_document("kid-1"))
    provider = JWKSProvider(fetcher=fetcher, clock=_MutableClock())

    key = provider.get_signing_key(ISSUER, "kid-1")

    assert key is not None
    assert key.key_id == "kid-1"
    assert fetcher.call_count == 1
    assert fetcher.urls == [_jwks_uri_for_issuer(ISSUER)]


def test_cache_hit_within_ttl_does_not_refetch() -> None:
    fetcher = _RecordingFetcher(_jwks_document("kid-1"))
    clock = _MutableClock()
    provider = JWKSProvider(cache_ttl=300.0, fetcher=fetcher, clock=clock)

    provider.get_signing_key(ISSUER, "kid-1")
    clock.advance(299.0)  # still within TTL
    key = provider.get_signing_key(ISSUER, "kid-1")

    assert key is not None
    assert key.key_id == "kid-1"
    assert fetcher.call_count == 1  # served from cache, no second fetch


def test_cache_is_isolated_per_issuer() -> None:
    fetcher = _RecordingFetcher(_jwks_document("kid-1"))
    provider = JWKSProvider(fetcher=fetcher, clock=_MutableClock())

    provider.get_signing_key(ISSUER, "kid-1")
    provider.get_signing_key(ISSUER_EU, "kid-1")

    # Each distinct issuer is fetched independently.
    assert fetcher.call_count == 2
    assert fetcher.urls == [
        _jwks_uri_for_issuer(ISSUER),
        _jwks_uri_for_issuer(ISSUER_EU),
    ]


# ──── TTL expiry ──────────────────────────────────────────────────────────────


def test_expired_cache_triggers_refetch() -> None:
    fetcher = _RecordingFetcher(_jwks_document("kid-1"))
    clock = _MutableClock()
    provider = JWKSProvider(cache_ttl=300.0, fetcher=fetcher, clock=clock)

    provider.get_signing_key(ISSUER, "kid-1")
    clock.advance(301.0)  # past TTL
    key = provider.get_signing_key(ISSUER, "kid-1")

    assert key is not None
    assert fetcher.call_count == 2  # stale entry refetched


# ──── Unknown kid refresh (key rotation) ──────────────────────────────────────


def test_unknown_kid_within_ttl_triggers_single_refresh() -> None:
    # Cache starts with kid-1; rotation introduces kid-2 in the fresh document.
    initial = _jwks_document("kid-1")
    rotated = _jwks_document("kid-1", "kid-2")

    class _RotatingFetcher:
        def __init__(self) -> None:
            self.call_count = 0

        def __call__(self, url: str) -> dict[str, Any]:
            self.call_count += 1
            return initial if self.call_count == 1 else rotated

    fetcher = _RotatingFetcher()
    provider = JWKSProvider(cache_ttl=300.0, fetcher=fetcher, clock=_MutableClock())

    # Warm the cache with the initial document.
    assert provider.get_signing_key(ISSUER, "kid-1") is not None
    assert fetcher.call_count == 1

    # Unknown kid within TTL forces a refresh that discovers the rotated key.
    key = provider.get_signing_key(ISSUER, "kid-2")
    assert key is not None
    assert key.key_id == "kid-2"
    assert fetcher.call_count == 2


def test_unknown_kid_returns_none_after_refresh_when_still_absent() -> None:
    fetcher = _RecordingFetcher(_jwks_document("kid-1"))
    provider = JWKSProvider(cache_ttl=300.0, fetcher=fetcher, clock=_MutableClock())

    provider.get_signing_key(ISSUER, "kid-1")  # warm cache
    key = provider.get_signing_key(ISSUER, "missing-kid")

    assert key is None
    # One refresh attempt was made to rule out key rotation.
    assert fetcher.call_count == 2


# ──── Failure handling ────────────────────────────────────────────────────────


def test_fetch_failure_returns_none() -> None:
    def _boom(url: str) -> dict[str, Any]:
        raise ConnectionError("network down")

    provider = JWKSProvider(fetcher=_boom, clock=_MutableClock())

    assert provider.get_signing_key(ISSUER, "kid-1") is None


def test_unparseable_key_is_skipped() -> None:
    document = _jwks_document("good-kid")
    document["keys"].append({"kid": "bad-kid", "kty": "RSA"})  # missing params → unparseable
    fetcher = _RecordingFetcher(document)
    provider = JWKSProvider(fetcher=fetcher, clock=_MutableClock())

    assert provider.get_signing_key(ISSUER, "good-kid") is not None
    assert provider.get_signing_key(ISSUER, "bad-kid") is None


# ──── Singleton accessor ──────────────────────────────────────────────────────


def test_get_jwks_provider_returns_singleton() -> None:
    import api.common.auth.jwksProvider as module

    module._provider = None
    try:
        first = get_jwks_provider()
        second = get_jwks_provider()
        assert first is second
    finally:
        module._provider = None
