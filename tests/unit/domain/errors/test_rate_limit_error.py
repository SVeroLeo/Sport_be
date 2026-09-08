"""Unit tests for the RateLimitError domain error.

Validates: Requirements 1.6, 2.10
"""

from __future__ import annotations

from domain.errors.domain_error import DomainError
from domain.errors.rate_limit_error import RateLimitError


class TestRateLimitError:
    def test_is_domain_error_subtype(self) -> None:
        assert issubclass(RateLimitError, DomainError)

    def test_instance_is_domain_error(self) -> None:
        assert isinstance(RateLimitError(), DomainError)

    def test_has_default_message(self) -> None:
        error = RateLimitError()

        assert error.message == "Too many requests, please try again later"
        assert str(error) == "Too many requests, please try again later"

    def test_accepts_custom_message(self) -> None:
        error = RateLimitError("Slow down")

        assert error.message == "Slow down"
        assert str(error) == "Slow down"
