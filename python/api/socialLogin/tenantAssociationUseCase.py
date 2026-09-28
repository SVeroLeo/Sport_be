"""TenantAssociationUseCase — associates a pending-tenant social user with a tenant.

This completes the social-login flow for users who could not be auto-assigned a
tenant during provisioning (``status == "pending_tenant"``). The user picks a
tenant via ``POST /auth/social/select-tenant`` and this use case validates the
choice, provisions the membership/member/role records atomically, and transitions
the user to ``active``.

Requirements satisfied: 5.2, 5.3, 5.4, 5.5, 5.6
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.socialLogin.socialLoginDtos import TenantAssociationOutputDTO
from api.member.member import Member
from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.userRole import UserRole
from api.common.errors.conflictError import ConflictError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError

if TYPE_CHECKING:
    from api.accountType.iAccountTypeRepository import IAccountTypeRepository
    from api.member.iMemberRepository import IMemberRepository
    from api.common.tenant.iTenantRepository import ITenantRepository
    from api.common.user.iUserRepository import IUserRepository


class TenantAssociationUseCase:
    """Application use case for associating a pending-tenant user with a tenant.

    Orchestrates:
    1. Load the ``User`` by ``user_id`` and confirm it is in ``pending_tenant`` state.
    2. Load the ``Tenant`` by ``tenant_id`` and confirm it exists and is active.
    3. Reject the request if the user is already a member of the tenant.
    4. Build ``TenantMembership``, ``Member`` (``registration_type="social"``), and a
       ``UserRole("viewer")``.
    5. Persist all records atomically via ``user_repository.associate_tenant`` and
       transition the user to ``active`` with the chosen tenant as their default.
    6. Return the updated user state as a ``TenantAssociationOutputDTO``.

    Error mapping (see design "Error Handling" table):
    - Missing/inactive tenant → ``NotFoundError("tenant_not_found")`` (HTTP 404).
    - Already a member → ``ConflictError("already_member")`` (HTTP 409).

    These reuse the existing ``NotFoundError``/``ConflictError`` domain errors so the
    HTTP layer maps them to the 404/409 statuses the design specifies, consistent
    with the rest of the codebase (e.g. ``RegisterUseCase``, ``InviteUserUseCase``).
    """

    _ASSOCIATED_STATUS = "active"
    _DEFAULT_ROLE = "viewer"
    _FALLBACK_ACCOUNT_TYPE = "usuario"

    def __init__(
        self,
        user_repository: IUserRepository,
        tenant_repository: ITenantRepository,
        member_repository: IMemberRepository,
        account_type_repository: IAccountTypeRepository,
    ) -> None:
        self._user_repository = user_repository
        self._tenant_repository = tenant_repository
        self._member_repository = member_repository
        self._account_type_repository = account_type_repository

    async def execute(
        self,
        user_id: str,
        tenant_id: str,
    ) -> TenantAssociationOutputDTO:
        """Execute the tenant association use case.

        Args:
            user_id: UUID string of the authenticated pending-tenant user. The
                caller's identity is verified against the access token at the
                controller level (via ``AuthGuardMiddleware``), not here.
            tenant_id: UUID string of the tenant the user chose to join.

        Returns:
            TenantAssociationOutputDTO reflecting the user's updated state.

        Raises:
            NotFoundError: If the user does not exist, or the tenant does not
                exist / is inactive (code ``"tenant_not_found"``, HTTP 404).
            ValidationError: If the user is not in ``pending_tenant`` status.
            ConflictError: If the user is already a member of the tenant
                (code ``"already_member"``, HTTP 409).
        """
        # 1. Load user and verify pending-tenant state (Req 5.2)
        user = self._user_repository.find_by_id(user_id)
        if user is None:
            raise NotFoundError("user_not_found", resource="user")
        if user.status != "pending_tenant":
            raise ValidationError(
                "User is not awaiting tenant selection",
                field="status",
            )

        # 2. Verify tenant exists and is active (Req 5.4)
        tenant = await self._tenant_repository.find_by_id(tenant_id)
        if tenant is None or not tenant.is_active:
            raise NotFoundError("tenant_not_found", resource="tenant")

        # 3. Reject if the user is already a member of this tenant (Req 5.5)
        existing_member = self._member_repository.find_by_user_in_tenant(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if existing_member is not None:
            raise ConflictError("already_member", resource="member")

        # 4. Resolve the account type for the new member record.
        account_type_name, account_type_id = await self._resolve_account_type(
            tenant_id=tenant_id,
            tenant_default_account_type=tenant.default_account_type,
        )

        # 5. Build the membership, member, and role records (Req 5.3)
        membership = TenantMembership.create(
            user_id=user_id,
            tenant_id=tenant_id,
        )
        member = Member.create(
            tenant_id=tenant_id,
            user_id=user_id,
            account_type=account_type_name,
            account_type_id=account_type_id,
            full_name=user.full_name.value,
            email=user.email.value,
            registration_type="social",
            status="active",
        )
        role = UserRole.create(
            user_id=user_id,
            tenant_id=tenant_id,
            role_name=self._DEFAULT_ROLE,
        )

        # 6. Persist atomically and transition the user to active (Req 5.3, 5.6)
        self._user_repository.associate_tenant(
            user_id=user_id,
            membership=membership,
            member=member,
            role=role,
            new_status=self._ASSOCIATED_STATUS,
            new_default_tenant_id=tenant_id,
        )

        # 7. Return the updated user state (Req 5.6)
        return TenantAssociationOutputDTO(
            user_id=user_id,
            email=user.email.value,
            default_tenant_id=tenant_id,
            status=self._ASSOCIATED_STATUS,
        )

    async def _resolve_account_type(
        self,
        tenant_id: str,
        tenant_default_account_type: str | None,
    ) -> tuple[str, str]:
        """Resolve the account type (name + id) for the new social member.

        Mirrors the resolution order used by ``RegisterUseCase``: prefer the
        tenant's configured default account type when it exists and is active,
        otherwise fall back to the ``"usuario"`` account type.

        Args:
            tenant_id: The tenant UUID.
            tenant_default_account_type: The tenant's default account type name
                (or None).

        Returns:
            A ``(name, account_type_id)`` tuple for the resolved account type.

        Raises:
            NotFoundError: If neither the tenant default nor the ``"usuario"``
                fallback account type can be resolved for the tenant.
        """
        if tenant_default_account_type is not None:
            default_type = await self._account_type_repository.find_by_name_in_tenant(
                tenant_id=tenant_id,
                name=tenant_default_account_type,
            )
            if default_type is not None and default_type.is_active:
                return default_type.name, default_type.account_type_id

        fallback = await self._account_type_repository.find_by_name_in_tenant(
            tenant_id=tenant_id,
            name=self._FALLBACK_ACCOUNT_TYPE,
        )
        if fallback is not None and fallback.is_active:
            return fallback.name, fallback.account_type_id

        raise NotFoundError(
            "No account type available for tenant association",
            resource="account_type",
        )
