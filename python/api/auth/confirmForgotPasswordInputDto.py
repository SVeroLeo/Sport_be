"""Confirm-forgot-password input DTO — data required to complete a reset."""

from pydantic import BaseModel, field_validator

from api.auth._email import validate_email


class ConfirmForgotPasswordInputDTO(BaseModel):
    """Application-layer input contract for completing a password reset.

    Carries the email plus the confirmation code emailed to the user and the
    new password. All fields are validated so that an invalid value raises a
    Pydantic ``ValidationError`` and the controller returns HTTP 400 without
    calling Cognito:

      - ``email``: same syntax rule as ``ForgotPasswordInputDTO``.
      - ``confirmation_code``: non-empty/non-whitespace, length 1-2048.
      - ``new_password``: non-empty/non-whitespace, length 1-256.
    """

    email: str
    confirmation_code: str
    new_password: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        return validate_email(v)

    @field_validator("confirmation_code")
    @classmethod
    def _validate_confirmation_code(cls, v: str) -> str:
        stripped = (v or "").strip()
        if not (1 <= len(stripped) <= 2048):
            raise ValueError("confirmation_code is required")
        return stripped

    @field_validator("new_password")
    @classmethod
    def _validate_new_password(cls, v: str) -> str:
        # Do not strip the password: leading/trailing characters may be
        # significant. Only reject empty or whitespace-only values, and
        # enforce the length bound on the original value.
        if not (v or "").strip() or not (1 <= len(v) <= 256):
            raise ValueError("new_password is required")
        return v
