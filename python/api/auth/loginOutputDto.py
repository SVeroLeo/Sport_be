"""Login output DTO — authentication result returned to the caller."""

from pydantic import BaseModel


class LoginOutputDTO(BaseModel):
    """Application-layer output contract for a successful login.

    Returns the Cognito token set along with the user's roles in their
    default (active) tenant. ``default_tenant_id`` is included as informational
    context for the client only — the access token itself is tenant-agnostic and
    every authenticated request re-resolves the active tenant server-side.
    """

    access_token: str
    id_token: str
    refresh_token: str
    expires_in: int
    default_tenant_id: str
    roles: list[str]
