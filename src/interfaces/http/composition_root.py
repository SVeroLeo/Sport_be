"""Composition Root — wires all dependencies for the application.

Creates infrastructure implementations, use cases, middleware, and controllers
via constructor injection. Uses a lazy singleton pattern: the container is
instantiated once on Lambda cold start and reused on warm invocations.

This is the ONLY place where concrete implementations are referenced.
All other layers depend on abstract ports (interfaces).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from application.use_cases.account_type.create_account_type_use_case import (
    CreateAccountTypeUseCase,
)
from application.use_cases.account_type.delete_account_type_use_case import (
    DeleteAccountTypeUseCase,
)
from application.use_cases.account_type.list_account_types_use_case import (
    ListAccountTypesUseCase,
)
from application.use_cases.account_type.update_account_type_use_case import (
    UpdateAccountTypeUseCase,
)
from application.use_cases.auth.login_use_case import LoginUseCase
from application.use_cases.member.deactivate_member_use_case import (
    DeactivateMemberUseCase,
)
from application.use_cases.member.list_members_use_case import ListMembersUseCase
from application.use_cases.member.update_member_use_case import UpdateMemberUseCase
from application.use_cases.registration.invite_user_use_case import InviteUserUseCase
from application.use_cases.registration.register_use_case import RegisterUseCase
from infrastructure.auth.cognito_auth_service import CognitoAuthService
from infrastructure.config.environment import get_environment_config
from infrastructure.persistence.dynamodb_account_type_repository import (
    DynamoDBAccountTypeRepository,
)
from infrastructure.persistence.dynamodb_member_repository import (
    DynamoDBMemberRepository,
)
from infrastructure.persistence.dynamodb_tenant_repository import (
    DynamoDBTenantRepository,
)
from infrastructure.persistence.dynamodb_user_repository import (
    DynamoDBUserRepository,
)
from interfaces.http.controllers.account_type_controller import AccountTypeController
from interfaces.http.controllers.auth_controller import AuthController
from interfaces.http.controllers.member_controller import MemberController
from interfaces.http.controllers.registration_controller import RegistrationController
from interfaces.http.middleware.tenant_guard_middleware import TenantGuardMiddleware

logger = logging.getLogger(__name__)


# ──── Container Dataclass ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Container:
    """Holds all wired dependencies for the application.

    Exposes controllers and middleware needed by Lambda handlers.
    All internal wiring (repositories, use cases, services) is
    encapsulated — handlers only access what they need.
    """

    # Middleware
    tenant_guard: TenantGuardMiddleware

    # Controllers
    auth_controller: AuthController
    registration_controller: RegistrationController
    account_type_controller: AccountTypeController
    member_controller: MemberController

    # Cognito service exposed for direct operations (refresh, logout)
    cognito_service: CognitoAuthService


# ──── Factory Function ────────────────────────────────────────────────────────


def _create_container() -> Container:
    """Create and wire all application dependencies.

    Instantiates infrastructure implementations, constructs use cases
    with their port dependencies, and wires controllers with use cases.

    Returns:
        A fully wired Container instance.
    """
    config = get_environment_config()

    # ── Infrastructure Layer — Concrete Implementations ───────────────────

    # Repositories
    user_repository = DynamoDBUserRepository()
    member_repository = DynamoDBMemberRepository()
    account_type_repository = DynamoDBAccountTypeRepository()
    tenant_repository = DynamoDBTenantRepository()

    # Cognito auth service
    cognito_service = CognitoAuthService(
        user_pool_id=config.cognito_user_pool_id,
        client_id=config.cognito_client_id,
        region=config.region,
    )

    # ── Application Layer — Use Cases ─────────────────────────────────────

    # Auth use cases
    login_use_case = LoginUseCase(
        cognito_service=cognito_service,
        user_repository=user_repository,
        member_repository=member_repository,
    )

    # Registration use cases
    register_use_case = RegisterUseCase(
        cognito_service=cognito_service,
        user_repository=user_repository,
        tenant_repository=tenant_repository,
        account_type_repository=account_type_repository,
    )

    invite_user_use_case = InviteUserUseCase(
        user_repository=user_repository,
        member_repository=member_repository,
        account_type_repository=account_type_repository,
        cognito_service=cognito_service,
    )

    # Account type use cases
    create_account_type_use_case = CreateAccountTypeUseCase(
        account_type_repository=account_type_repository,
        tenant_repository=tenant_repository,
    )

    list_account_types_use_case = ListAccountTypesUseCase(
        account_type_repository=account_type_repository,
    )

    update_account_type_use_case = UpdateAccountTypeUseCase(
        account_type_repository=account_type_repository,
    )

    delete_account_type_use_case = DeleteAccountTypeUseCase(
        account_type_repository=account_type_repository,
        member_repository=member_repository,
    )

    # Member use cases
    list_members_use_case = ListMembersUseCase(
        member_repository=member_repository,
    )

    update_member_use_case = UpdateMemberUseCase(
        member_repository=member_repository,
        account_type_repository=account_type_repository,
    )

    deactivate_member_use_case = DeactivateMemberUseCase(
        member_repository=member_repository,
        user_repository=user_repository,
        cognito_service=cognito_service,
    )

    # ── Interface Adapters Layer — Middleware ─────────────────────────────

    tenant_guard = TenantGuardMiddleware(jwt_secret=config.jwt_secret)

    # ── Interface Adapters Layer — Controllers ────────────────────────────

    auth_controller = AuthController(
        login_use_case=login_use_case,
        cognito_service=cognito_service,
    )

    registration_controller = RegistrationController(
        register_use_case=register_use_case,
    )

    account_type_controller = AccountTypeController(
        tenant_guard=tenant_guard,
        create_use_case=create_account_type_use_case,
        list_use_case=list_account_types_use_case,
        update_use_case=update_account_type_use_case,
        delete_use_case=delete_account_type_use_case,
    )

    member_controller = MemberController(
        invite_user_use_case=invite_user_use_case,
        list_members_use_case=list_members_use_case,
        update_member_use_case=update_member_use_case,
        deactivate_member_use_case=deactivate_member_use_case,
        tenant_guard=tenant_guard,
    )

    logger.info("Composition root initialized successfully")

    return Container(
        tenant_guard=tenant_guard,
        auth_controller=auth_controller,
        registration_controller=registration_controller,
        account_type_controller=account_type_controller,
        member_controller=member_controller,
        cognito_service=cognito_service,
    )


# ──── Lazy Singleton ──────────────────────────────────────────────────────────

_container: Container | None = None


def get_container() -> Container:
    """Get the singleton dependency container.

    Creates the container on first call (Lambda cold start) and returns
    the cached instance on subsequent calls (warm invocations).

    Returns:
        The Container singleton with all dependencies wired.
    """
    global _container  # noqa: PLW0603
    if _container is None:
        _container = _create_container()
    return _container
