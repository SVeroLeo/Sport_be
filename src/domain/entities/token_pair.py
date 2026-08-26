"""TokenPair entity — represents the set of tokens returned from Cognito authentication."""

from __future__ import annotations


class TokenPair:
    """Immutable domain entity representing a Cognito authentication token set.

    Contains the access_token, id_token, and refresh_token returned after
    successful authentication, along with the token expiration time.
    """

    __slots__ = (
        "_access_token",
        "_expires_in",
        "_id_token",
        "_refresh_token",
    )

    _access_token: str
    _id_token: str
    _refresh_token: str
    _expires_in: int

    def __init__(
        self,
        access_token: str,
        id_token: str,
        refresh_token: str,
        expires_in: int,
    ) -> None:
        object.__setattr__(self, "_access_token", access_token)
        object.__setattr__(self, "_id_token", id_token)
        object.__setattr__(self, "_refresh_token", refresh_token)
        object.__setattr__(self, "_expires_in", expires_in)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    # ──── Properties ──────────────────────────────────────────────────────────

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def id_token(self) -> str:
        return self._id_token

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    @property
    def expires_in(self) -> int:
        """Token expiration time in seconds."""
        return self._expires_in

    # ──── Equality & Representation ───────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TokenPair):
            return NotImplemented
        return (
            self._access_token == other._access_token
            and self._id_token == other._id_token
            and self._refresh_token == other._refresh_token
        )

    def __hash__(self) -> int:
        return hash((self._access_token, self._id_token, self._refresh_token))

    def __repr__(self) -> str:
        return (
            f"TokenPair(access_token={self._access_token[:8]}..., "
            f"id_token={self._id_token[:8]}..., "
            f"expires_in={self._expires_in})"
        )
