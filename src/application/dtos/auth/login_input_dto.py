"""Login input DTO — data required to authenticate a user."""

from pydantic import BaseModel


class LoginInputDTO(BaseModel):
    """Application-layer input contract for user login.

    Contains the credentials and tenant context needed to authenticate
    a user via Cognito and retrieve their tenant membership.
    """

    email: str
    password: str
    tenant_id: str
