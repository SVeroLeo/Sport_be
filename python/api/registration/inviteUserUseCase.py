"""InviteUserUseCase — orchestrates admin-invited member creation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.member.createMemberInputDto import CreateMemberInputDTO
from api.member.memberOutputDto import MemberOutputDTO
from api.member.member import Member
from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.users import User
from api.common.user.userRole import UserRole, _VALID_ROLES
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.common.valueObjects.email import Email
from api.member.fullName import FullName
from api.common.tenant.tenantId import TenantId

if TYPE_CHECKING:
    from api.accountType.iAccountTypeRepository import IAccountTypeRepository
    from api.common.ports.iCognitoService import ICognitoService
    from api.member.iMemberRepository import IMemberRepository
    from api.common.user.iUserRepository import IUserRepository


class InviteUserUseCase:
    """Application use case for admin-invited member creation.

    Orchestrates:
    1. Validate input value objects (email, full_name, tenant_id).
    2. Validate all role names are valid.
    3. Validate account type exists and is active in the tenant.
    4. Check if user already exists by email.
    5a. If user exists: check not already a member → create Membership + Member + Roles atomically.
    5b. If user is new: create in Cognito (AdminCreateUser) → create User + Membership + Member + Roles atomically.
    6. Return MemberOutputDTO.

    Requirements satisfied: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
    """

    def __init__(
        self,
        user_repository: IUserRepository,
        member_repository: IMemberRepository,
        account_type_repository: IAccountTypeRepository,
        cognito_service: ICognitoService,
    ) -> None:
        self._user_repository = user_repository
        self._member_repository = member_repository
        self._account_type_repository = account_type_repository
        self._cognito_service = cognito_service

    async def execute(
        self,
        input_dto: CreateMemberInputDTO,
        created_by_user_id: str,
    ) -> MemberOutputDTO:
        """Execute the invite user use case.

        Args:
            input_dto: CreateMemberInputDTO containing tenant_id, email, full_name,
                       account_type, and roles.
            created_by_user_id: User ID of the admin performing the invitation.

        Returns:
            MemberOutputDTO with the created member data.

        Raises:
            ValidationError: If email, full_name, tenant_id, or roles are invalid.
            NotFoundError: If account type does not exist in the tenant.
            DomainError: If account type is not active.
            ConflictError: If user is already a member of the tenant.
        """
        # 1. Validate input value objects (raises ValidationError if invalid)
        validated_email = Email.create(input_dto.email)
        validated_full_name = FullName.create(input_dto.full_name)
        validated_tenant_id = TenantId.create(input_dto.tenant_id)

        # 2. Validate roles — all must be valid role names (Req 4.7)
        self._validate_roles(input_dto.roles)

        # 3. Validate account type exists and is active in the tenant (Req 4.5, 4.6)
        account_type = await self._account_type_repository.find_by_name_in_tenant(
            tenant_id=validated_tenant_id.value,
            name=input_dto.account_type,
        )
        if account_type is None:
            raise NotFoundError(
                "Account type does not exist in this tenant",
                resource="account_type",
            )
        if not account_type.is_active:
            raise DomainError("Account type is not active")

        # 4. Check if user already exists by email
        existing_user = self._user_repository.find_by_email(validated_email)

        if existing_user is not None:
            # 5a. User exists — check not already a member of this tenant (Req 4.4)
            existing_member = self._member_repository.find_by_user_in_tenant(
                tenant_id=validated_tenant_id.value,
                user_id=existing_user.user_id,
            )
            if existing_member is not None:
                raise ConflictError(
                    "User is already a member of this tenant",
                    resource="member",
                )

            # Create Membership + Member + Roles atomically (Req 4.3)
            membership = TenantMembership.create(
                user_id=existing_user.user_id,
                tenant_id=validated_tenant_id.value,
            )
            member = Member.create(
                tenant_id=validated_tenant_id.value,
                user_id=existing_user.user_id,
                account_type=account_type.name,
                account_type_id=account_type.account_type_id,
                full_name=validated_full_name.value,
                email=validated_email.value,
                registration_type="invited",
                invited_by=created_by_user_id,
                status="active",
            )
            roles = [
                UserRole.create(
                    user_id=existing_user.user_id,
                    tenant_id=validated_tenant_id.value,
                    role_name=role_name,
                )
                for role_name in input_dto.roles
            ]

            self._member_repository.create_member_with_roles(
                membership=membership,
                member=member,
                roles=roles,
            )

        else:
            # 5b. User is new — create in Cognito first, then persist atomically (Req 4.1, 4.2)
            cognito_sub = await self._cognito_service.admin_create_user(
                email=validated_email.value,
                full_name=validated_full_name.value,
            )

            # Create User entity with status "pending_confirmation"
            new_user = User.create(
                email=validated_email.value,
                cognito_sub=cognito_sub,
                full_name=validated_full_name.value,
                status="pending_confirmation",
            )

            membership = TenantMembership.create(
                user_id=new_user.user_id,
                tenant_id=validated_tenant_id.value,
            )
            member = Member.create(
                tenant_id=validated_tenant_id.value,
                user_id=new_user.user_id,
                account_type=account_type.name,
                account_type_id=account_type.account_type_id,
                full_name=validated_full_name.value,
                email=validated_email.value,
                registration_type="invited",
                invited_by=created_by_user_id,
                status="active",
            )
            roles = [
                UserRole.create(
                    user_id=new_user.user_id,
                    tenant_id=validated_tenant_id.value,
                    role_name=role_name,
                )
                for role_name in input_dto.roles
            ]

            # Persist User + Membership + Member + Roles atomically (Req 12.2)
            self._user_repository.create_user_with_membership(
                user=new_user,
                membership=membership,
                member=member,
                roles=roles,
            )

        # 6. Build and return output DTO
        return MemberOutputDTO(
            member_id=member.member_id,
            tenant_id=member.tenant_id,
            user_id=member.user_id,
            account_type=member.account_type,
            account_type_id=member.account_type_id,
            full_name=member.full_name,
            email=member.email,
            status=member.status,
            registration_type=member.registration_type,
            invited_by=member.invited_by,
            metadata=member.metadata,
            created_at=member.created_at,
            updated_at=member.updated_at,
        )

    @staticmethod
    def _validate_roles(roles: list[str]) -> None:
        """Validate that all role names are valid.

        Args:
            roles: List of role name strings to validate.

        Raises:
            ValidationError: If the roles list is empty or contains invalid role names.
        """
        if not roles:
            raise ValidationError("Invalid role", field="roles")

        for role_name in roles:
            normalized = role_name.strip().lower() if role_name else ""
            if normalized not in _VALID_ROLES:
                raise ValidationError("Invalid role", field="roles")
