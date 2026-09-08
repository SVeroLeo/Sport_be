"""Shared email validation for auth input DTOs.

Centralizes the email syntax rule required by the password-recovery
endpoints so ``ForgotPasswordInputDTO`` and ``ConfirmForgotPasswordInputDTO``
apply an identical check (single ``@``, non-empty local and domain parts,
total length 3-254). The validator raises ``ValueError`` on failure so that
Pydantic surfaces a ``ValidationError`` and the controller maps it to HTTP 400.
"""


def validate_email(value: str) -> str:
    """Validate and normalize a syntactically valid email address.

    Rules (per acceptance criteria):
      - exactly one ``@``
      - non-empty local and domain parts
      - total length between 3 and 254 characters (inclusive)

    The value is stripped of surrounding whitespace before validation, and the
    stripped value is returned. Empty, whitespace-only, too-long, or malformed
    values raise ``ValueError``.
    """
    stripped = (value or "").strip()
    if not (3 <= len(stripped) <= 254) or stripped.count("@") != 1:
        raise ValueError("invalid email")
    local, _, domain = stripped.partition("@")
    if not local or not domain:
        raise ValueError("invalid email")
    return stripped
