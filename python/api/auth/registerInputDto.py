"""Register input DTO — data required for user self-registration."""

from pydantic import BaseModel


class RegisterInputDTO(BaseModel):
    """Application-layer input contract for self-registration.

    Contains the user data and tenant context needed to register
    a new user via Cognito and create their membership.

    ``full_name`` and ``tenant_id`` are optional: the native register flow only
    collects email + password. When absent, ``full_name`` is derived from the
    email local-part and ``tenant_id`` falls back to the environment's default
    tenant (``DEFAULT_TENANT_ID``), both resolved in RegisterUseCase.
    """

    email: str
    password: str
    full_name: str | None = None
    tenant_id: str | None = None
    account_type: str | None = None
