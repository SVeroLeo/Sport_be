"""Login input DTO — data required to authenticate a user."""

from pydantic import BaseModel


class LoginInputDTO(BaseModel):
    """Application-layer input contract for user login.

    Login is tenant-agnostic: the user authenticates with just their email and
    password. The active tenant is resolved from the user's default_tenant_id
    (stored in DynamoDB), never supplied by the caller.
    """

    email: str
    password: str
