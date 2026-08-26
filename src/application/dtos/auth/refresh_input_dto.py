"""Refresh input DTO — data required to refresh an access token."""

from pydantic import BaseModel


class RefreshInputDTO(BaseModel):
    """Application-layer input contract for token refresh.

    Although token refresh is primarily delegated to Cognito directly,
    this DTO supports any API-level refresh endpoint if needed.
    """

    refresh_token: str
