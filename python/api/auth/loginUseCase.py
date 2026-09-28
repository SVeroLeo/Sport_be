"""LoginUseCase — orchestrates user authentication via Cognito and membership verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.auth.loginInputDto import LoginInputDTO
from api.auth.loginOutputDto import LoginOutputDTO
from api.common.errors.domainError import DomainError
from api.common.errors.invalidCredentialsError import InvalidCredentialsError
from api.common.valueObjects.email import Email

if TYPE_CHECKING:
    from api.common.ports.iCognitoService import ICognitoService
    from api.member.iMemberRepository import IMemberRepository
    from api.common.user.iUserRepository import IUserRepository


class LoginUseCase:
    """Application use case for authenticating a user.

    Orchestrates:
    1. Validate email format via Email value object.
    2. Delegate credential verification to Cognito (initiate_auth).
    3. Look up the user by email in the local database.
    4. Check tenant membership exists and is active.
    5. Retrieve user roles for the tenant.
    6. Return token pair and roles.

    Requirements satisfied: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6
    """

    def __init__(
        self,
        cognito_service: ICognitoService,
        user_repository: IUserRepository,
        member_repository: IMemberRepository,
    ) -> None:
        self._cognito_service = cognito_service
        self._user_repository = user_repository
        self._member_repository = member_repository

    async def execute(self, input_dto: LoginInputDTO) -> LoginOutputDTO:
        """Execute the login use case.

        Login is tenant-agnostic: the user authenticates with email + password.
        The active tenant is resolved from the user's default_tenant_id and used
        to verify membership and load roles.

        Args:
            input_dto: LoginInputDTO containing email and password.

        Returns:
            LoginOutputDTO with the Cognito token set, the resolved
            default_tenant_id, and the user's roles in that tenant.

        Raises:
            ValidationError: If email format is invalid.
            InvalidCredentialsError: If Cognito auth fails, user not found, no
                default tenant, or no active membership.
            DomainError: If membership is not active (message: "Account is not active").
        """
        # 1. Validate email format (raises ValidationError if invalid)
        validated_email = Email.create(input_dto.email)

        # 2. Authenticate with Cognito — raises InvalidCredentialsError on failure (Req 1.3)
        try:
            token_pair = await self._cognito_service.initiate_auth(
                email=validated_email.value,
                password=input_dto.password,
            )
        except InvalidCredentialsError:
            raise InvalidCredentialsError()

        # 3. Find the user in our database by email
        user = self._user_repository.find_by_email(validated_email)
        if user is None:
            # User authenticated in Cognito but not in our DB — treat as invalid credentials (Req 1.5)
            raise InvalidCredentialsError()

        # 4. Resolve the active tenant from the user's profile (Req 1.5).
        # Login no longer takes a tenant_id; the tenant is the user's default.
        default_tenant_id = user.default_tenant_id
        if not default_tenant_id:
            # No default tenant assigned — generic error, do not reveal account state
            raise InvalidCredentialsError()

        # 5. Check tenant membership in the resolved (default) tenant
        member = self._member_repository.find_by_user_in_tenant(
            tenant_id=default_tenant_id,
            user_id=user.user_id,
        )
        if member is None:
            # No membership in the default tenant — generic error to avoid leaking state
            raise InvalidCredentialsError()

        # 6. Check membership status is active (Req 1.4)
        if member.status != "active":
            raise DomainError("Account is not active")

        # 7. Get roles for the user in the resolved tenant (Req 1.6)
        user_roles = self._user_repository.get_roles_for_tenant(
            user_id=user.user_id,
            tenant_id=default_tenant_id,
        )
        role_names = [role.role_name for role in user_roles]

        # 8. Build and return output DTO (Req 1.2)
        return LoginOutputDTO(
            access_token=token_pair.access_token,
            id_token=token_pair.id_token,
            refresh_token=token_pair.refresh_token,
            expires_in=token_pair.expires_in,
            default_tenant_id=default_tenant_id,
            roles=role_names,
        )
