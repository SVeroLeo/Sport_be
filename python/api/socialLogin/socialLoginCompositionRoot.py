"""Composition Root for the social-login (OAuth) Lambda.

Wires all dependencies for the ``OAuthHandlerFn`` and returns a fully
constructed :class:`OAuthController`. This is the ONLY place in the social-login
interface layer where concrete infrastructure implementations are referenced;
every other layer depends on abstract ports.

Why a separate composition root (not ``composition_root.get_container()``)?
    The ``OAuthHandlerFn`` intentionally has a *different* environment-variable
    surface than the main API Lambda. It additionally needs
    ``COGNITO_HOSTED_UI_DOMAIN``, ``COGNITO_CALLBACK_URL`` and
    ``SOCIAL_STATE_SECRET`` (the last sourced from Secrets Manager). Mirroring the
    ``post_confirmation_handler`` approach, this module reads its environment
    variables directly and wires repositories/services locally so the CDK stack
    can grant this Lambda its own env/permissions without creating a circular
    dependency between the User Pool and the Lambda that references it.

Lazy singleton: the container is built once on Lambda cold start and reused on
warm invocations.

Environment variables read:
    - ``TABLE_NAME``                — DynamoDB table (used by the repositories).
    - ``REGION``                    — AWS region for boto3 clients.
    - ``COGNITO_USER_POOL_ID``      — User Pool for admin Cognito operations.
    - ``COGNITO_CLIENT_ID``         — App Client id for the Hosted UI OAuth flow.
    - ``COGNITO_HOSTED_UI_DOMAIN``  — Hosted UI domain (authorize / token host).
    - ``COGNITO_CALLBACK_URL``      — OAuth ``redirect_uri`` for authorize/token.
    - ``SOCIAL_STATE_SECRET``       — HMAC secret for CSRF ``state`` tokens.
    - ``COGNITO_ISSUERS`` / ``COGNITO_CLIENT_IDS`` — optional multi-region
      allow-lists for token verification; derived from the singular variables
      above when absent (same rule as ``EnvironmentConfig.load``).

Requirements satisfied: 8.6, 9.4
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from api.socialLogin.socialAuthorizeUseCase import SocialAuthorizeUseCase
from api.socialLogin.socialCallbackUseCase import SocialCallbackUseCase
from api.socialLogin.tenantAssociationUseCase import TenantAssociationUseCase
from api.common.auth.cognitoAuthService import CognitoAuthService
from api.common.auth.jwksProvider import get_jwks_provider
from api.accountType.dynamodbAccountTypeRepository import (
    DynamoDBAccountTypeRepository,
)
from api.member.dynamodbMemberRepository import (
    DynamoDBMemberRepository,
)
from api.common.tenant.dynamodbTenantRepository import (
    DynamoDBTenantRepository,
)
from api.common.user.dynamodbUserRepository import (
    DynamoDBUserRepository,
)
from api.socialLogin.oauthController import OAuthController
from api.common.http.authGuardMiddleware import AuthGuardMiddleware

logger = logging.getLogger(__name__)


# ──── Container Dataclass ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SocialLoginContainer:
    """Holds the wired dependencies for the social-login Lambda.

    Handlers only need the :class:`OAuthController`; all internal wiring
    (repositories, services, use cases, middleware) is encapsulated.
    """

    oauth_controller: OAuthController


# ──── Environment parsing (mirrors EnvironmentConfig.load) ────────────────────


def _parse_list(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated env value into a tuple of trimmed, non-empty items.

    Args:
        raw: The raw environment variable value (comma-separated).

    Returns:
        A tuple of non-empty, trimmed string items.
    """
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _issuer_for_pool(region: str, user_pool_id: str) -> str:
    """Build the Cognito issuer URL for a region and User Pool.

    Args:
        region: AWS region of the User Pool.
        user_pool_id: The Cognito User Pool ID.

    Returns:
        ``https://cognito-idp.{region}.amazonaws.com/{user_pool_id}``.
    """
    return f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"


# ──── Factory Function ────────────────────────────────────────────────────────


def build_oauth_controller() -> OAuthController:
    """Build and return a fully wired :class:`OAuthController`.

    Reads configuration from environment variables, instantiates the DynamoDB
    repositories and the Cognito auth service, constructs the three social-login
    use cases and the shared :class:`AuthGuardMiddleware`, and returns the
    controller with everything injected.

    Returns:
        A wired :class:`OAuthController` ready to serve the social-login routes.
    """
    # ── Configuration — read directly from the environment (Req 8.6, 9.4) ────
    region = os.environ.get("REGION", "us-east-1")
    cognito_user_pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    cognito_client_id = os.environ.get("COGNITO_CLIENT_ID", "")
    hosted_ui_domain = os.environ.get("COGNITO_HOSTED_UI_DOMAIN", "")
    callback_url = os.environ.get("COGNITO_CALLBACK_URL", "")
    state_secret = os.environ.get("SOCIAL_STATE_SECRET", "")

    # Token-verification allow-lists (used by AuthGuardMiddleware). Prefer the
    # multi-region allow-lists; fall back to deriving them from the singular
    # single-region variables, matching EnvironmentConfig.load().
    cognito_issuers = _parse_list(os.environ.get("COGNITO_ISSUERS", ""))
    cognito_client_ids = _parse_list(os.environ.get("COGNITO_CLIENT_IDS", ""))
    if not cognito_issuers and cognito_user_pool_id:
        cognito_issuers = (_issuer_for_pool(region, cognito_user_pool_id),)
    if not cognito_client_ids and cognito_client_id:
        cognito_client_ids = (cognito_client_id,)

    # ── Infrastructure Layer — Concrete Implementations ──────────────────────

    # Repositories (read TABLE_NAME / REGION from the environment internally,
    # consistent with the main composition root and post_confirmation_handler).
    user_repository = DynamoDBUserRepository()
    tenant_repository = DynamoDBTenantRepository()
    member_repository = DynamoDBMemberRepository()
    account_type_repository = DynamoDBAccountTypeRepository()

    # Cognito auth service — admin operations (link provider, update attributes)
    # and the Hosted UI token exchange.
    cognito_service = CognitoAuthService(
        user_pool_id=cognito_user_pool_id,
        client_id=cognito_client_id,
        region=region,
    )

    # ── Application Layer — Use Cases ─────────────────────────────────────────

    social_authorize_use_case = SocialAuthorizeUseCase(
        client_id=cognito_client_id,
        redirect_uri=callback_url,
        hosted_ui_domain=hosted_ui_domain,
        state_secret=state_secret,
    )

    social_callback_use_case = SocialCallbackUseCase(
        user_repository=user_repository,
        cognito_service=cognito_service,
        tenant_repository=tenant_repository,
        redirect_uri=callback_url,
        hosted_ui_domain=hosted_ui_domain,
        state_secret=state_secret,
    )

    tenant_association_use_case = TenantAssociationUseCase(
        user_repository=user_repository,
        tenant_repository=tenant_repository,
        member_repository=member_repository,
        account_type_repository=account_type_repository,
    )

    # ── Interface Adapters Layer — Middleware ─────────────────────────────────

    auth_guard = AuthGuardMiddleware(
        allowed_issuers=cognito_issuers,
        allowed_client_ids=cognito_client_ids,
        user_repository=user_repository,
        jwks_provider=get_jwks_provider(),
    )

    # ── Interface Adapters Layer — Controller ─────────────────────────────────

    oauth_controller = OAuthController(
        social_authorize_use_case=social_authorize_use_case,
        social_callback_use_case=social_callback_use_case,
        tenant_association_use_case=tenant_association_use_case,
        auth_guard=auth_guard,
    )

    logger.info("Social-login composition root initialized successfully")
    return oauth_controller


# ──── Lazy Singleton ──────────────────────────────────────────────────────────

_container: SocialLoginContainer | None = None


def get_social_login_container() -> SocialLoginContainer:
    """Get the singleton social-login dependency container.

    Builds the container on first call (Lambda cold start) and returns the
    cached instance on subsequent calls (warm invocations).

    Returns:
        The :class:`SocialLoginContainer` singleton with the wired controller.
    """
    global _container  # noqa: PLW0603
    if _container is None:
        _container = SocialLoginContainer(oauth_controller=build_oauth_controller())
    return _container
