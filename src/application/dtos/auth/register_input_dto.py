"""Register input DTO — data required for user self-registration."""

from pydantic import BaseModel


class RegisterInputDTO(BaseModel):
    """Application-layer input contract for self-registration.

    Contains the user data and tenant context needed to register
    a new user via Cognito and create their membership.
    """

    email: str
    password: str
    full_name: str
    tenant_id: str
    account_type: str | None = None
