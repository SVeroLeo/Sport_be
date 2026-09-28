"""Respond-to-challenge input DTO — data required to answer a Cognito challenge."""

from pydantic import BaseModel, field_validator

# Cognito-supported challenge names accepted by this endpoint.
SUPPORTED_CHALLENGES = {
    "NEW_PASSWORD_REQUIRED",
    "SMS_MFA",
    "SOFTWARE_TOKEN_MFA",
    "CUSTOM_CHALLENGE",
}


class RespondToChallengeInputDTO(BaseModel):
    """Application-layer input contract for answering an authentication challenge.

    All fields are validated so that an invalid value raises a Pydantic
    ``ValidationError`` and the controller returns HTTP 400 without calling
    Cognito:

      - ``challenge_name``: must be one of ``SUPPORTED_CHALLENGES``.
      - ``session``: non-empty, length 1-2048.
      - ``challenge_responses``: a non-empty map (at least one key-value pair).
    """

    challenge_name: str
    session: str
    challenge_responses: dict[str, str]

    @field_validator("challenge_name")
    @classmethod
    def _validate_challenge_name(cls, v: str) -> str:
        if v not in SUPPORTED_CHALLENGES:
            raise ValueError("invalid challenge_name")
        return v

    @field_validator("session")
    @classmethod
    def _validate_session(cls, v: str) -> str:
        stripped = (v or "").strip()
        if not (1 <= len(stripped) <= 2048):
            raise ValueError("session is required")
        return stripped

    @field_validator("challenge_responses")
    @classmethod
    def _validate_challenge_responses(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("challenge_responses is required")
        return v
