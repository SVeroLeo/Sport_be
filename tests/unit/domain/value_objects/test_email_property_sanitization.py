"""Property-based tests for Email sanitization.

Feature: social-login, Property 6: Email sanitization preserves canonical form

**Validates: Requirements 8.4**

Requirement 8.4 states the Social_Login_Service must sanitize the email
received from the social provider using the existing `Email` value object
before persisting it. The `Email.create` factory normalizes an accepted raw
value to its canonical form by trimming surrounding whitespace and
lowercasing (`value.strip().lower()`).

Property 6 asserts that for ANY accepted raw email string — including ones
wrapped in arbitrary leading/trailing whitespace and using mixed case — the
resulting `Email.value` equals the canonical `raw.strip().lower()`.
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from domain.value_objects.email import Email

# ─── Generators ───────────────────────────────────────────────────────────────

# Characters allowed in the local part by the Email regex (excluding a leading
# separator to keep generated values obviously valid). We deliberately avoid
# starting/ending with characters that could combine oddly; any valid local
# part per the regex is acceptable.
_LOCAL_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.!#$%&'*+/=?^_`{|}~-"

# Domain labels must start and end with an alphanumeric and may contain hyphens
# in between. Whitespace is not allowed anywhere in the address body.
_LABEL_START_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_LABEL_MID_CHARS = _LABEL_START_CHARS + "-"

# Whitespace characters that str.strip() removes, used only around the address.
_WHITESPACE = " \t\n\r\f\v"


@st.composite
def _local_parts(draw: st.DrawFn) -> str:
    """Generate a valid local part (1-32 chars from the allowed set)."""
    return draw(st.text(alphabet=_LOCAL_CHARS, min_size=1, max_size=32))


@st.composite
def _domain_labels(draw: st.DrawFn) -> str:
    """Generate a single valid DNS-like label.

    Starts and ends with an alphanumeric; may contain hyphens in the middle.
    """
    first = draw(st.sampled_from(_LABEL_START_CHARS))
    # 0-1 chars middle keeps total short; label length 1-10.
    length = draw(st.integers(min_value=1, max_value=10))
    if length == 1:
        return first
    middle = draw(st.text(alphabet=_LABEL_MID_CHARS, min_size=0, max_size=length - 2))
    last = draw(st.sampled_from(_LABEL_START_CHARS))
    return first + middle + last


@st.composite
def _domains(draw: st.DrawFn) -> str:
    """Generate a valid domain with at least two labels (contains a dot)."""
    label_count = draw(st.integers(min_value=2, max_value=4))
    labels = [draw(_domain_labels()) for _ in range(label_count)]
    return ".".join(labels)


@st.composite
def _valid_emails(draw: st.DrawFn) -> str:
    """Generate a normalized valid email of the form local@domain."""
    local = draw(_local_parts())
    domain = draw(_domains())
    email = f"{local}@{domain}"
    # Keep well under the 254-char limit so all generated values are accepted.
    return email


@st.composite
def _mixed_case_wrapped_emails(draw: st.DrawFn) -> str:
    """Generate a valid email with random casing and surrounding whitespace."""
    email = draw(_valid_emails())

    # Apply arbitrary per-character casing to exercise the lowercasing step.
    cased = "".join(
        c.upper() if draw(st.booleans()) else c.lower() for c in email
    )

    leading = draw(st.text(alphabet=_WHITESPACE, min_size=0, max_size=5))
    trailing = draw(st.text(alphabet=_WHITESPACE, min_size=0, max_size=5))
    return f"{leading}{cased}{trailing}"


# ─── Property 6 ─────────────────────────────────────────────────────────────


class TestEmailSanitizationCanonicalForm:
    """Property 6 — Email sanitization preserves canonical form.

    For ANY accepted raw email string (mixed case, arbitrary leading/trailing
    whitespace), `Email.create(raw).value` equals `raw.strip().lower()`.

    **Validates: Requirements 8.4**
    """

    @given(raw=_mixed_case_wrapped_emails())
    @settings(max_examples=200)
    def test_create_value_equals_strip_lower(self, raw: str) -> None:
        """Accepted inputs normalize to their trimmed, lowercased canonical form.

        **Validates: Requirements 8.4**
        """
        email = Email.create(raw)

        assert email.value == raw.strip().lower()

    @given(raw=_mixed_case_wrapped_emails())
    @settings(max_examples=200)
    def test_create_is_idempotent(self, raw: str) -> None:
        """Re-sanitizing an already-canonical value is a no-op.

        Sanitizing the canonical form again yields the same value, confirming
        the canonical form is a fixed point of the normalization.

        **Validates: Requirements 8.4**
        """
        canonical = Email.create(raw).value

        assert Email.create(canonical).value == canonical
