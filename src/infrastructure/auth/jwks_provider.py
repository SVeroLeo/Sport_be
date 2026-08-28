"""Per-issuer JWKS provider for Cognito RS256 token verification.

In a multi-region Cognito deployment each User Pool replica is a distinct pool
with its own issuer, signing keys (``kid``) and JWKS endpoint. This provider
fetches ``{iss}/.well-known/jwks.json`` for a given issuer, caches the parsed
keys per issuer with a TTL, and resolves the public signing key for a given
``kid`` on demand.

Cache behavior:
- Keys are cached per issuer for ``cache_ttl`` seconds.
- A cache hit within the TTL avoids any network fetch.
- When a requested ``kid`` is not present in the cached key set, the provider
  refetches the issuer's JWKS once (handling Cognito key rotation) before
  giving up.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jwt import PyJWK

logger = logging.getLogger(__name__)

# A fetcher takes a JWKS URL and returns the decoded JWKS document (a dict with
# a top-level ``keys`` list). Injectable so tests can avoid real HTTP calls.
JWKSFetcher = Callable[[str], dict[str, Any]]

# Returns the current time in seconds. Injectable so tests can drive TTL expiry.
Clock = Callable[[], float]


def _jwks_uri_for_issuer(issuer: str) -> str:
    """Build the JWKS document URL for a Cognito issuer.

    Args:
        issuer: The issuer URL, e.g.
            ``https://cognito-idp.{region}.amazonaws.com/{userPoolId}``.

    Returns:
        The JWKS endpoint URL for that issuer.
    """
    return f"{issuer.rstrip('/')}/.well-known/jwks.json"


def _default_fetcher(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch and decode a JWKS document over HTTPS using the standard library.

    Args:
        url: The JWKS endpoint URL.
        timeout: HTTP timeout in seconds.

    Returns:
        The decoded JWKS document.
    """
    with urllib.request.urlopen(url, timeout=timeout) as response:
        document: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return document


@dataclass(slots=True)
class _CacheEntry:
    """A cached JWKS key set for a single issuer.

    Attributes:
        keys: Mapping of ``kid`` to the parsed ``PyJWK`` signing key.
        fetched_at: The clock time (seconds) when this entry was fetched.
    """

    keys: dict[str, PyJWK]
    fetched_at: float


class JWKSProvider:
    """Resolves RS256 signing keys per Cognito issuer, with a TTL cache.

    Maintains one cached key set per issuer. Each entry is considered fresh for
    ``cache_ttl`` seconds; an expired entry (or an unknown ``kid``) triggers a
    refetch of that issuer's JWKS document.
    """

    __slots__ = ("_cache", "_cache_ttl", "_clock", "_fetcher")

    def __init__(
        self,
        *,
        cache_ttl: float = 300.0,
        fetcher: JWKSFetcher | None = None,
        clock: Clock | None = None,
    ) -> None:
        """Initialize the JWKS provider.

        Args:
            cache_ttl: How long (seconds) a fetched key set is cached before it
                is considered stale and refetched. Defaults to 300s.
            fetcher: Callable that fetches the JWKS document for a URL. Defaults
                to a stdlib HTTPS fetcher. Injectable for testing.
            clock: Callable returning the current time in seconds. Defaults to
                ``time.monotonic``. Injectable for testing TTL expiry.
        """
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl
        self._fetcher: JWKSFetcher = fetcher or _default_fetcher
        self._clock: Clock = clock or time.monotonic

    def _fetch_keys(self, issuer: str) -> dict[str, PyJWK]:
        """Fetch the issuer's JWKS document and parse it into keys by ``kid``.

        Args:
            issuer: The token issuer URL.

        Returns:
            Mapping of ``kid`` to parsed ``PyJWK``. Keys that fail to parse are
            skipped so that a single malformed key does not break the set.
        """
        document = self._fetcher(_jwks_uri_for_issuer(issuer))
        keys: dict[str, PyJWK] = {}
        for jwk_data in document.get("keys", []):
            kid = jwk_data.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = PyJWK.from_dict(jwk_data)
            except Exception:
                logger.warning("JWKS: skipping unparseable key kid=%s at issuer=%s", kid, issuer)
        return keys

    def _refresh(self, issuer: str) -> dict[str, PyJWK]:
        """Refetch and cache the key set for an issuer.

        Args:
            issuer: The token issuer URL.

        Returns:
            The freshly fetched key set (also stored in the cache).
        """
        keys = self._fetch_keys(issuer)
        self._cache[issuer] = _CacheEntry(keys=keys, fetched_at=self._clock())
        return keys

    def _is_fresh(self, entry: _CacheEntry) -> bool:
        """Return whether a cache entry is still within its TTL.

        Args:
            entry: The cache entry to check.

        Returns:
            ``True`` if the entry has not yet expired.
        """
        return (self._clock() - entry.fetched_at) < self._cache_ttl

    def get_signing_key(self, issuer: str, kid: str) -> PyJWK | None:
        """Resolve the public signing key for a given issuer and key id.

        Uses the cached key set when it is fresh and contains ``kid``. When the
        cache is stale, missing, or does not contain ``kid`` (key rotation), the
        issuer's JWKS document is refetched once before giving up.

        Args:
            issuer: The token issuer URL (must be a known/allowed issuer;
                enforced by the caller before this method is used).
            kid: The key id from the token header.

        Returns:
            The matching ``PyJWK`` signing key, or ``None`` if the key cannot be
            resolved (unknown ``kid`` even after refresh, or the JWKS document
            could not be fetched).
        """
        try:
            entry = self._cache.get(issuer)

            # Cache hit: fresh entry that already knows this kid.
            if entry is not None and self._is_fresh(entry) and kid in entry.keys:
                return entry.keys[kid]

            # Stale cache: refresh before looking up the kid.
            if entry is None or not self._is_fresh(entry):
                keys = self._refresh(issuer)
                if kid in keys:
                    return keys[kid]
                return None

            # Fresh cache but unknown kid: refresh once to pick up rotated keys.
            keys = self._refresh(issuer)
            return keys.get(kid)
        except Exception:
            logger.exception("JWKS: failed to resolve signing key for issuer=%s", issuer)
            return None


# Module-level singleton — one provider reused across warm Lambda invocations.
_provider: JWKSProvider | None = None


def get_jwks_provider() -> JWKSProvider:
    """Get the singleton JWKS provider.

    Creates the provider on first call (Lambda cold start) and reuses it on
    subsequent calls (warm invocations), so JWKS documents stay cached across
    requests.

    Returns:
        The shared ``JWKSProvider`` instance.
    """
    global _provider
    if _provider is None:
        _provider = JWKSProvider()
    return _provider
