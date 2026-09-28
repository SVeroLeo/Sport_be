"""RegisterUseCase — orchestrates user self-registration with tenant and account type validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.auth.registerInputDto import RegisterInputDTO
from api.auth.registerOutputDto import RegisterOutputDTO
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.common.valueObjects.email import Email
from api.member.fullName import FullName
from api.common.valueObjects.password import Password
from api.common.tenant.tenantId import TenantId

if TYPE_CHECKING:
    from api.accountType.iAccountTypeRepository import IAccountTypeRepository
    from api.common.ports.iCognitoService import ICognitoService
    from api.common.tenant.iTenantRepository import ITenantRepository
    from api.common.user.iUserRepository import IUserRepository


class RegisterUseCase:
    """Application use case for self-registration of a new user.

    Orchestrates:
    1. Validate value objects (Email, Password, FullName, TenantId).
    2. Check email uniqueness in local database.
    3. Verify tenant exists, is active, and allows self-registration.
    4. Determine account type (explicit > tenant default > "usuario" fallback).
    5. Call Cognito SignUp to register the user (sends verification email).
    6. Return confirmation-pending status.

    The actual DynamoDB record creation (User, TenantMembership, Member, Role)
    happens in a Cognito post-confirmation Lambda trigger (Req 3.2).

    Requirements satisfied: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
    """

    _FALLBACK_ACCOUNT_TYPE = "usuario"

    def __init__(
        self,
        cognito_service: ICognitoService,
        user_repository: IUserRepository,
        tenant_repository: ITenantRepository,
        account_type_repository: IAccountTypeRepository,
    ) -> None:
        self._cognito_service = cognito_service
        self._user_repository = user_repository
        self._tenant_repository = tenant_repository
        self._account_type_repository = account_type_repository

    async def execute(self, input_dto: RegisterInputDTO) -> RegisterOutputDTO:
        """Execute the self-registration use case.

        Args:
            input_dto: RegisterInputDTO containing email, password, full_name,
                       tenant_id, and optional account_type.

        Returns:
            RegisterOutputDTO with user info and confirmation-pending status.

        Raises:
            ValidationError: If any input fails value object validation.
            ConflictError: If the email is already registered (Req 3.3).
            NotFoundError: If the tenant does not exist (Req 3.4).
            DomainError: If the tenant is not active (Req 3.5) or
                         self-registration is not allowed (Req 3.6).
            ValidationError: If specified account type is invalid (Req 3.8).
        """
        # 1. Validate value objects (Req 11.1, 11.2, 11.3, 11.4)
        validated_email = Email.create(input_dto.email)
        validated_password = Password.create(input_dto.password)
        validated_full_name = FullName.create(input_dto.full_name)
        validated_tenant_id = TenantId.create(input_dto.tenant_id)

        # 2. Check email uniqueness in local database (Req 3.3)
        existing_user = self._user_repository.find_by_email(validated_email)
        if existing_user is not None:
            raise ConflictError("Email already registered", resource="user")

        # 3. Verify tenant exists (Req 3.4)
        tenant = await self._tenant_repository.find_by_id(validated_tenant_id.value)
        if tenant is None:
            raise NotFoundError("Tenant not found", resource="tenant")

        # 4. Verify tenant is active (Req 3.5)
        if not tenant.is_active:
            raise DomainError("Tenant is not active")

        # 5. Verify tenant allows self-registration (Req 3.6)
        if not tenant.allow_self_registration:
            raise DomainError("Self-registration is not allowed for this institution")

        # 6. Determine account type (Req 3.7, 3.8)
        account_type_name = await self._resolve_account_type(
            tenant_id=validated_tenant_id.value,
            explicit_account_type=input_dto.account_type,
            tenant_default_account_type=tenant.default_account_type,
        )

        # 7. Call Cognito SignUp — registers user and sends verification email (Req 3.1)
        # ConflictError is raised by the cognito service if email already in Cognito (Req 3.3)
        cognito_sub = await self._cognito_service.sign_up(
            email=validated_email.value,
            password=validated_password.value,
            full_name=validated_full_name.value,
            tenant_id=validated_tenant_id.value,
            account_type=account_type_name,
        )

        # 8. Return confirmation-pending status (Req 3.1)
        # The post-confirmation Lambda trigger will create User, TenantMembership,
        # Member, and Role records atomically in DynamoDB (Req 3.2).
        # When that trigger creates the User record it MUST set
        # User.default_tenant_id = validated_tenant_id.value, so the tenant the
        # user registered into becomes their default (active) tenant. The AuthGuard
        # later resolves the active tenant from this value (tasks 23.1–23.2).
        return RegisterOutputDTO(
            user_id=cognito_sub,
            email=validated_email.value,
            full_name=validated_full_name.value,
            status="pending_confirmation",
            message="Registration successful. Please verify your email to activate your account.",
        )

    async def _resolve_account_type(
        self,
        tenant_id: str,
        explicit_account_type: str | None,
        tenant_default_account_type: str | None,
    ) -> str:
        """Resolve the account type for the new member.

        Resolution order (Req 3.7, 3.8):
        1. If user specified an account_type → validate it exists and is active.
        2. If not specified → use tenant's defaultAccountType (if set and active).
        3. If defaultAccountType is null or inactive → fall back to "usuario".

        Args:
            tenant_id: The tenant UUID.
            explicit_account_type: The account type name specified by the user (or None).
            tenant_default_account_type: The tenant's default account type (or None).

        Returns:
            The resolved account type name.

        Raises:
            ValidationError: If the explicit account type does not exist or is inactive.
        """
        if explicit_account_type is not None:
            # User specified an account type — must exist and be active (Req 3.8)
            account_type = await self._account_type_repository.find_by_name_in_tenant(
                tenant_id=tenant_id,
                name=explicit_account_type,
            )
            if account_type is None or not account_type.is_active:
                raise ValidationError("Invalid account type", field="account_type")
            return account_type.name

        # No explicit account type — try tenant default (Req 3.7)
        if tenant_default_account_type is not None:
            default_type = await self._account_type_repository.find_by_name_in_tenant(
                tenant_id=tenant_id,
                name=tenant_default_account_type,
            )
            if default_type is not None and default_type.is_active:
                return default_type.name

        # Fallback to "usuario" (Req 3.7)
        return self._FALLBACK_ACCOUNT_TYPE
