"""LoginUseCase — orchestrates user authentication via Cognito and membership verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from application.dtos.auth.login_input_dto import LoginInputDTO
from application.dtos.auth.login_output_dto import LoginOutputDTO
from domain.errors.domain_error import DomainError
from domain.errors.invalid_credentials_error import InvalidCredentialsError
from domain.value_objects.email import Email

if TYPE_CHECKING:
    from application.ports.i_cognito_service import ICognitoService
    from application.ports.i_member_repository import IMemberRepository
    from application.ports.i_user_repository import IUserRepository


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

        Args:
            input_dto: LoginInputDTO containing email, password, and tenant_id.

        Returns:
            LoginOutputDTO with access_token, id_token, refresh_token, expires_in, and roles.

        Raises:
            ValidationError: If email format is invalid.
            InvalidCredentialsError: If Cognito auth fails, user not found, or no membership.
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

        # 4. Check tenant membership (Req 1.5)
        member = self._member_repository.find_by_user_in_tenant(
            tenant_id=input_dto.tenant_id,
            user_id=user.user_id,
        )
        if member is None:
            # No membership in this tenant — generic error to avoid revealing membership status
            raise InvalidCredentialsError()

        # 5. Check membership status is active (Req 1.4)
        if member.status != "active":
            raise DomainError("Account is not active")

        # 6. Get roles for the user in this tenant (Req 1.6)
        user_roles = self._user_repository.get_roles_for_tenant(
            user_id=user.user_id,
            tenant_id=input_dto.tenant_id,
        )
        role_names = [role.role_name for role in user_roles]

        # 7. Build and return output DTO (Req 1.2)
        return LoginOutputDTO(
            access_token=token_pair.access_token,
            id_token=token_pair.id_token,
            refresh_token=token_pair.refresh_token,
            expires_in=token_pair.expires_in,
            roles=role_names,
        )
