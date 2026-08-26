"""Login output DTO — authentication result returned to the caller."""

from pydantic import BaseModel


class LoginOutputDTO(BaseModel):
    """Application-layer output contract for a successful login.

    Returns the Cognito token set along with the user's roles
    within the specified tenant.
    """

    access_token: str
    id_token: str
    refresh_token: str
    expires_in: int
    roles: list[str]
