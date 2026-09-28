"""Unit tests for the ChallengeResult domain entity.

Covers the bimodal result of ``respond_to_challenge``:
- ``authenticated()`` populates ``token_pair`` and reports authenticated.
- ``next_challenge()`` populates name/session and reports not authenticated.

Validates: Requirements 3.2, 3.3
"""

from __future__ import annotations

from api.auth.challengeResult import ChallengeResult
from api.auth.tokenPair import TokenPair


def _make_token_pair() -> TokenPair:
    return TokenPair(
        access_token="access-token-value",
        id_token="id-token-value",
        refresh_token="refresh-token-value",
        expires_in=3600,
    )


class TestAuthenticatedFactory:
    def test_sets_token_pair(self) -> None:
        token_pair = _make_token_pair()

        result = ChallengeResult.authenticated(token_pair)

        assert result.token_pair is token_pair

    def test_is_authenticated_true(self) -> None:
        result = ChallengeResult.authenticated(_make_token_pair())

        assert result.is_authenticated() is True

    def test_next_challenge_fields_are_none(self) -> None:
        result = ChallengeResult.authenticated(_make_token_pair())

        assert result.next_challenge_name is None
        assert result.next_session is None


class TestNextChallengeFactory:
    def test_sets_name_and_session(self) -> None:
        result = ChallengeResult.next_challenge("NEW_PASSWORD_REQUIRED", "session-token")

        assert result.next_challenge_name == "NEW_PASSWORD_REQUIRED"
        assert result.next_session == "session-token"

    def test_is_authenticated_false(self) -> None:
        result = ChallengeResult.next_challenge("NEW_PASSWORD_REQUIRED", "session-token")

        assert result.is_authenticated() is False

    def test_token_pair_is_none(self) -> None:
        result = ChallengeResult.next_challenge("NEW_PASSWORD_REQUIRED", "session-token")

        assert result.token_pair is None


class TestImmutability:
    def test_is_frozen(self) -> None:
        result = ChallengeResult.authenticated(_make_token_pair())

        import dataclasses

        try:
            result.next_session = "mutated"  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("ChallengeResult should be immutable")
