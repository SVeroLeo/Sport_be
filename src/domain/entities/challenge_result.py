"""ChallengeResult entity — bimodal result of responding to an auth challenge."""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities.token_pair import TokenPair


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    """Bimodal result of ``respond_to_challenge``.

    Invariant: exactly one of the two modes is populated.
    - Authenticated:  ``token_pair`` set, ``next_challenge_name``/``next_session`` None.
    - Next challenge: ``next_challenge_name`` + ``next_session`` set, ``token_pair`` None.

    Use :meth:`is_authenticated` to distinguish the two cases, which guarantees
    the XOR property between the authenticated and next-challenge shapes.
    """

    token_pair: TokenPair | None = None
    next_challenge_name: str | None = None
    next_session: str | None = None

    def is_authenticated(self) -> bool:
        """Return True when this result carries an authenticated token pair."""
        return self.token_pair is not None

    @classmethod
    def authenticated(cls, token_pair: TokenPair) -> ChallengeResult:
        """Build an authenticated result carrying the issued token pair."""
        return cls(token_pair=token_pair)

    @classmethod
    def next_challenge(cls, challenge_name: str, session: str) -> ChallengeResult:
        """Build a next-challenge result carrying the challenge name and session."""
        return cls(next_challenge_name=challenge_name, next_session=session)
