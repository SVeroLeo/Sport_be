"""Register output DTO — registration result returned to the caller."""

from pydantic import BaseModel


class RegisterOutputDTO(BaseModel):
    """Application-layer output contract for a successful registration.

    Returns the user info with a confirmation-pending status,
    indicating the user must verify their email via Cognito.
    """

    user_id: str
    email: str
    full_name: str
    status: str
    message: str
