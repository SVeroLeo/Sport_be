"""Social login DTOs — input/output contracts for the federated login flow.

These DTOs cover the three social-login endpoints:

* ``GET /auth/social/authorize`` returns a :class:`SocialAuthorizeOutputDTO`.
* ``GET /auth/social/callback`` returns a :class:`SocialLoginOutputDTO`.
* ``POST /auth/social/select-tenant`` accepts a :class:`SelectTenantInputDTO`
  and returns a :class:`TenantAssociationOutputDTO`.

They follow the same Pydantic ``BaseModel`` convention used by the rest of the
application DTOs (see ``application/dtos/auth``).
"""

from pydantic import BaseModel


class SocialAuthorizeOutputDTO(BaseModel):
    """Output contract for the social authorize endpoint.

    Wraps the fully-built Cognito Hosted UI authorization URL that the frontend
    redirects the browser to in order to begin the OAuth flow.
    """

    authorization_url: str


class SocialLoginOutputDTO(BaseModel):
    """Output contract for a completed social login callback.

    Returns the Cognito token set for the authenticated user. ``expires_in`` and
    the token fields mirror the shape of the native ``LoginOutputDTO``.
    ``requires_tenant_selection`` is ``True`` only when the user still needs to
    pick a tenant (``status == "pending_tenant"``), signalling the frontend to
    route to the select-tenant step before granting full access.
    """

    access_token: str
    id_token: str
    refresh_token: str
    expires_in: int
    user_id: str
    requires_tenant_selection: bool = False


class SelectTenantInputDTO(BaseModel):
    """Input contract for the select-tenant endpoint.

    Supplies the tenant a pending-tenant social user chooses to associate with.
    The calling user's identity is resolved from the access token, never from
    the request body.
    """

    tenant_id: str


class TenantAssociationOutputDTO(BaseModel):
    """Output contract returned after a successful tenant association.

    Reflects the updated user state once the tenant membership, member record,
    and role have been provisioned and the user transitions out of the
    ``pending_tenant`` status.
    """

    user_id: str
    email: str
    default_tenant_id: str
    status: str
