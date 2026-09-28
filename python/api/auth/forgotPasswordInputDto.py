"""Forgot-password input DTO — data required to start password recovery."""

from pydantic import BaseModel, field_validator

from api.auth._email import validate_email


class ForgotPasswordInputDTO(BaseModel):
    """Application-layer input contract for initiating password recovery.

    Carries the email that identifies the account for which a reset code
    should be sent. The email is validated syntactically (single ``@``,
    non-empty local/domain parts, total length 3-254); an invalid value
    raises a Pydantic ``ValidationError`` so the controller returns HTTP 400
    without calling Cognito.
    """

    email: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        return validate_email(v)
