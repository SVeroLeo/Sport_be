# Implementation Plan: Account Management

## Overview

Implementación del sistema de gestión de cuentas multi-tenant siguiendo Clean Architecture con Python, AWS Lambda, API Gateway y DynamoDB single table design. El plan sigue el orden de capas: Domain → Application → Infrastructure → Interface Adapters, asegurando que cada capa se construya sobre las anteriores.

## Tasks

- [x] 1. Set up project structure and configuration
  - [x] 1.1 Initialize Python project with pyproject.toml, configure virtual environment, and install core dependencies (boto3, pydantic, uuid)
    - Configure strict Python, path aliases for `@domain`, `@application`, `@infrastructure`, `@interfaces`
    - Install dev dependencies: pytest, hypothesis, moto, mypy, ruff (linter)
    - _Requirements: N/A (project setup)_

  - [x] 1.2 Create directory structure following Clean Architecture layout
    - Create `src/domain/entities/`, `src/domain/value_objects/`, `src/domain/errors/`
    - Create `src/application/use_cases/`, `src/application/dtos/`, `src/application/ports/`
    - Create `src/infrastructure/persistence/`, `src/infrastructure/auth/`, `src/infrastructure/config/`, `src/infrastructure/mappers/`
    - Create `src/interfaces/http/controllers/`, `src/interfaces/http/middleware/`, `src/interfaces/http/dtos/`, `src/interfaces/shared/`
    - _Requirements: N/A (project setup)_

- [x] 2. Implement Domain Layer — Value Objects
  - [x] 2.1 Implement Email value object with validation (valid format, max 254 chars)
    - Create `src/domain/value_objects/email.py`
    - Static factory method `Email.create(value: string)` returning `Email | ValidationError`
    - Immutable, stores normalized (trimmed, lowercased) value
    - _Requirements: 11.1_

  - [x] 2.2 Implement Password value object with validation (min 8, max 72 chars)
    - Create `src/domain/value_objects/password.py`
    - Static factory method `Password.create(value: string)` returning `Password | ValidationError`
    - Include `Password.createUnsafe(value: string)` for system-generated passwords
    - _Requirements: 11.2, 13.5_

  - [x] 2.3 Implement tenant_id value object with UUID validation
    - Create `src/domain/value_objects/tenant_id.py`
    - Static factory method `tenant_id.create(value: string)` returning `tenant_id | ValidationError`
    - Validates non-empty and valid UUID format
    - _Requirements: 11.4_

  - [x] 2.4 Implement remaining value objects (member_id, account_type_id, RoleName, full_name)
    - Create `src/domain/value_objects/member_id.py`, `account_type_id.py`, `role_name.py`, `full_name.py`
    - full_name: non-empty, max 200 chars
    - RoleName: must be one of "admin", "manager", "viewer"
    - _Requirements: 11.3, 11.5_

  - [x] 2.5 Write property tests for Value Objects
    - **Property 17: Value Object Validation Gate**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 13.5**
    - Verify that invalid inputs never pass validation
    - Verify that valid inputs always produce valid value objects

- [x] 3. Implement Domain Layer — Entities and Errors
  - [x] 3.1 Implement domain error hierarchy
    - Create `src/domain/errors/domain_error.py` (base class)
    - Create `src/domain/errors/validation_error.py`
    - Create `src/domain/errors/invalid_credentials_error.py`
    - Create `src/domain/errors/tenant_not_found_error.py`
    - Create `src/domain/errors/conflict_error.py`, `not_found_error.py`, `forbidden_error.py`
    - _Requirements: N/A (cross-cutting domain concern)_

  - [x] 3.2 Implement User entity
    - Create `src/domain/entities/user.py`
    - Fields: user_id, email, cognito_sub, full_name, status (active|inactive|suspended|pending_confirmation), created_at, updated_at
    - Static factory `User.create(...)` with domain validation
    - _Requirements: 1.1, 3.1, 4.1_

  - [x] 3.3 Implement Tenant entity
    - Create `src/domain/entities/tenant.py`
    - Fields: tenant_id, name, plan, status, allowSelfRegistration, defaultAccountType, created_at
    - _Requirements: 3.3, 3.4, 3.5_

  - [x] 3.4 Implement Member entity
    - Create `src/domain/entities/member.py`
    - Fields: member_id, tenant_id, user_id, account_type, account_type_id, full_name, email, status, registrationType, invitedBy, metadata, created_at, updated_at
    - Static factory `Member.create(...)` with validation
    - _Requirements: 4.1, 6.1, 7.3_

  - [x] 3.5 Implement account_type entity
    - Create `src/domain/entities/account_type.py`
    - Fields: account_type_id, tenant_id, name, description, config, status, created_at, updated_at
    - Static factory `account_type.create(...)` with name validation (non-empty, max 100 chars)
    - _Requirements: 5.1, 5.3_

  - [x] 3.6 Implement supporting types (TenantMembership, UserRole)
        - Create `src/domain/entities/tenant_membership.py`
    - Create `src/domain/entities/user_role.py` with RoleDefinition constants and permissions
    - Create `src/domain/entities/token_pair.py`
    - _Requirements: 10.1, 10.6, 14.1, 14.2_

  - [x] 3.7 Write unit tests for domain entities
    - Test entity creation with valid and invalid data
    - Test User status transitions
    - Test account_type name validation constraints
    - Test RoleDefinition permission sets
    - _Requirements: 5.3, 10.1, 10.2, 10.3_

- [x] 4. Implement Application Layer — Ports (Interfaces)
  - [x] 4.1 Define IUserRepository port interface
    - Create `src/application/ports/i_user_repository.py`
    - Methods: find_by_email, find_by_id, save, get_roles_for_tenant, register_with_membership, create_user_with_membership
    - _Requirements: 1.1, 3.1, 4.1, 4.2, 12.1, 12.2_

  - [x] 4.2 Define IMemberRepository port interface
    - Create `src/application/ports/i_member_repository.py`
    - Methods: find_by_id, find_by_user_in_tenant, find_by_tenant_and_filters, save, update, create_member_with_roles, count_active_by_account_type
    - _Requirements: 5.7, 6.1, 6.2, 6.3, 7.1, 8.1_

  - [x] 4.3 Define IAccountTypeRepository, ICognitoService, and ITenantRepository port interfaces
    - Create `src/application/ports/i_account_type_repository.py` — find_by_id, find_by_name_in_tenant, find_all_by_tenant, save, update
    - Create `src/application/ports/i_cognito_service.py` — sign_up, admin_create_user, initiate_auth, admin_disable_user, admin_enable_user
    - Create `src/application/ports/i_tenant_repository.py` — find_by_id
    - Create `src/application/ports/i_cognito_service.py` — sign_up, admin_create_user, initiate_auth, admin_disable_user, admin_enable_user
    - _Requirements: 2.1, 2.4, 5.4, 13.1, 13.3, 14.4_

- [x] 5. Implement Application Layer — DTOs
  - [x] 5.1 Create authentication DTOs (login, register, refresh, token output)
    - Create `src/application/dtos/auth/login_input_dto.py`, `login_output_dto.py`
    - Create `src/application/dtos/auth/register_input_dto.py`, `register_output_dto.py`
    - Create `src/application/dtos/auth/refresh_input_dto.py`
    - _Requirements: 1.1, 2.1, 3.1_

  - [x] 5.2 Create account type and member DTOs
    - Create `src/application/dtos/account_type/create_account_type_input_dto.py`, `update_account_type_input_dto.py`, `account_type_output_dto.py`, `paginated_account_types_dto.py`
    - Create `src/application/dtos/member/create_member_input_dto.py`, `update_member_input_dto.py`, `member_output_dto.py`, `paginated_members_dto.py`
    - Create shared pagination types (`src/application/dtos/shared/pagination_params.py`)
    - _Requirements: 4.1, 5.1, 6.1, 7.1_

- [x] 6. Implement Application Layer — Authentication Use Cases
  - [x] 6.1 Implement LoginUseCase
    - Create `src/application/use_cases/auth/login_use_case.py`
    - Call cognito_service.initiate_auth(email, password), on success query DynamoDB for user by cognito_sub, get tenant membership and roles
    - Return generic "Invalid credentials" for all Cognito auth failures and membership issues
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 6.2 Write property test for LoginUseCase credential error opacity
    - **Property 2: Credential Error Opacity**
    - **Validates: Requirements 1.2, 1.3, 1.5**

  - [x] 6.3 (REMOVED - Cognito handles token refresh directly)

  - [x] 6.4 Write property test for RefreshTokenUseCase single-use rotation
    - **Property 6: Refresh Token Single-Use Rotation**
    - **Validates: Requirements 2.1, 2.4, 2.5, 12.4**

  - [x] 6.5 (REMOVED - Client revokes tokens via Cognito GlobalSignOut)

- [x] 7. Implement Application Layer — Registration Use Cases
  - [x] 7.1 Implement RegisterUseCase (self-registration)
    - Create `src/application/use_cases/registration/register_use_case.py`
    - Validate VOs, check email uniqueness, verify tenant (exists, active, allowSelfRegistration), determine account_type (explicit → defaultAccountType → "usuario" fallback), hash password, create User+Membership+Member+Role atomically, generate tokens, create session
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 7.2 Write property tests for RegisterUseCase
    - **Property 8: Registration Atomicity**
    - **Property 13: Self-Registration Gate**
    - **Property 14: Default account_type Assignment**
    - **Property 15: Email Uniqueness Enforcement**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 12.1**

  - [x] 7.3 Implement InviteUserUseCase (admin-invited member creation)
    - Create `src/application/use_cases/registration/invite_user_use_case.py`
    - Validate account_type (exists, active), check if user exists, if new → create User with temp password (status: pending_confirmation) + Membership + Member + Roles atomically; if existing → check not already member, create Membership + Member + Roles
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

- [x] 8. Implement Application Layer — Account Type Use Cases
  - [x] 8.1 Implement CreateAccountTypeUseCase
    - Create `src/application/use_cases/account_type/createAccountTypeUseCase.py`
    - Verify tenant, check name uniqueness (case-insensitive), create entity with status "active", persist
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 8.2 Implement ListAccountTypesUseCase
    - Create `src/application/use_cases/account_type/listAccountTypesUseCase.py`
    - Query by tenant with pagination (max 100 per page)
    - _Requirements: 5.4_

  - [x] 8.3 Implement UpdateAccountTypeUseCase
    - Create `src/application/use_cases/account_type/updateAccountTypeUseCase.py`
    - Find existing, validate name uniqueness if changed, update, refresh updated_at
    - _Requirements: 5.5_

  - [x] 8.4 Implement DeleteAccountTypeUseCase (soft delete)
    - Create `src/application/use_cases/account_type/deleteAccountTypeUseCase.py`
    - Check active members count, reject if > 0, else set status to "inactive"
    - _Requirements: 5.6, 5.7_

  - [x] 8.5 Write property tests for Account Type use cases
    - **Property 4: account_type Name Uniqueness per Tenant**
    - **Property 9: account_type Deletion Protection**
    - **Validates: Requirements 5.2, 5.5, 5.7**

- [x] 9. Implement Application Layer — Member Use Cases
  - [x] 9.1 Implement ListMembersUseCase
    - Create `src/application/use_cases/member/listMembersUseCase.py`
    - Query by tenant with filters (account_type case-insensitive, status exact match) and pagination
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 9.2 Implement UpdateMemberUseCase
    - Create `src/application/use_cases/member/updateMemberUseCase.py`
    - Find member, validate new account_type if changed (exists and active), apply updates, preserve immutable fields (created_at, registrationType, invitedBy), refresh updated_at
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 9.3 Implement DeactivateMemberUseCase
    - Create `src/application/use_cases/member/deactivateMemberUseCase.py`
    - Find member, check not already inactive, set status to "inactive", invalidate all sessions in tenant, preserve User record
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 9.4 Write property tests for Member use cases
    - **Property 5: Soft Delete Preservation**
    - **Property 7: Member-account_type Referential Integrity**
    - **Property 11: Session Invalidation on Deactivation**
    - **Property 16: Member Update Preserves Immutable Fields**
    - **Property 19: Filter Correctness**
    - **Property 20: User Record Preservation on Member Deactivation**
    - **Validates: Requirements 5.6, 7.3, 7.4, 7.5, 8.1, 8.4, 8.5**

- [x] 10. Checkpoint — Domain and Application layers complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement Infrastructure Layer — DynamoDB Client and Config
  - [x] 11.1 Create DynamoDB client configuration and environment config
    - Create `src/infrastructure/config/environment.py` — Read TABLE_NAME, REGION, JWT_SECRET, TOKEN_EXPIRY, SALT_ROUNDS from env
    - Create `src/infrastructure/config/dynamoDBClient.py` — Singleton DynamoDB DocumentClient setup
    - _Requirements: N/A (infrastructure setup)_

  - [x] 11.2 Create entity-to-DynamoDB item mappers
    - Create `src/infrastructure/mappers/userMapper.py` — User entity ↔ DynamoDB item with PK=USER#{email}, SK=PROFILE
    - Create `src/infrastructure/mappers/memberMapper.py` — Member entity ↔ DynamoDB item with PK, SK, GSI1PK, GSI1SK, GSI2PK, GSI2SK
    - Create `src/infrastructure/mappers/accountTypeMapper.py` — account_type entity ↔ DynamoDB item with PK, SK, GSI1PK, GSI1SK
    - Create `src/infrastructure/mappers/sessionMapper.py` — Session entity ↔ DynamoDB item with PK=SESSION#{user_id}, SK=TOKEN#{tokenId}, TTL
    - _Requirements: 9.4_

- [x] 12. Implement Infrastructure Layer — Repository Implementations
  - [x] 12.1 Implement DynamoDBUserRepository
    - Create `src/infrastructure/persistence/dynamoDBUserRepository.py`
    - Implement find_by_email (GetItem PK=USER#{email}, SK=PROFILE)
    - Implement get_roles_for_tenant (Query PK=TENANT#{tid}#USER#{uid}, SK begins_with ROLE#)
    - Implement register_with_membership (TransactWriteItems for User + Membership + Member + Role)
    - Implement create_user_with_membership (TransactWriteItems)
    - _Requirements: 1.1, 3.1, 4.1, 4.2, 12.1, 12.2_

  - [x] 12.2 Implement DynamoDBMemberRepository
    - Create `src/infrastructure/persistence/dynamoDBMemberRepository.py`
    - Implement find_by_id (GetItem)
    - Implement find_by_user_in_tenant (Query GSI2)
    - Implement find_by_tenant_and_filters (Query with account_type → GSI1, else base table; handle pagination cursor)
    - Implement count_active_by_account_type (Query GSI1 with filter)
    - Implement create_member_with_roles (TransactWriteItems)
    - _Requirements: 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 12.2_

  - [x] 12.3 Implement DynamoDBAccountTypeRepository
    - Create `src/infrastructure/persistence/dynamoDBAccountTypeRepository.py`
    - Implement find_by_id (GetItem PK=TENANT#{tid}#ACCTYPE, SK=ACCTYPE#{id})
    - Implement find_by_name_in_tenant (Query GSI1 with PK=TENANT#{tid}#ACCTYPE, SK=NAME#{lowercase(name)})
    - Implement find_all_by_tenant (Query with pagination)
    - Implement save and update
    - _Requirements: 5.1, 5.2, 5.4, 5.5_

  - [x] 12.4 (REMOVED - No session repository needed, Cognito manages sessions)

  - [x] 12.5 Implement DynamoDBTenantRepository
    - Create `src/infrastructure/persistence/dynamoDBTenantRepository.py`
    - Implement find_by_id (GetItem PK=TENANT#{tid}, SK=METADATA)
    - _Requirements: 3.3, 3.4, 3.5_

- [x] 13. Implement Infrastructure Layer — Auth Service
  - [x] 13.1 Implement CognitoAuthService (implements ICognitoService)
    - Create `src/infrastructure/auth/cognito_auth_service.py`
    - Implement initiate_auth: calls Cognito AdminInitiateAuth
    - Implement sign_up: calls Cognito SignUp
    - Implement admin_create_user: calls Cognito AdminCreateUser
    - 
    - _Requirements: 1.6, 1.7, 2.6, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.4_

  - [x] 13.2 Write property test for password security
    - **Property 10: Password Storage Security**
    - **Validates: Requirements 13.1, 13.2, 13.4, 4.7**

- [x] 14. Checkpoint — Infrastructure layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Implement Interface Adapters Layer — Middleware
  - [x] 15.1 Implement TenantGuard middleware
    - Create `src/interfaces/http/middleware/tenantGuardMiddleware.py`
    - Extract Bearer token from Authorization header
    - Verify JWT via IAuthService port
    - Extract tenant_id from token payload, reject if missing (401)
    - Return TenantContext { user_id, tenant_id, roles, email }
    - _Requirements: 9.1, 9.2, 9.5, 10.4_

  - [x] 15.2 Implement RoleGuard middleware
    - Create `src/interfaces/http/middleware/roleGuardMiddleware.py`
    - Check user roles against required permission for the action
    - Union of permissions across multiple roles (least restrictive)
    - Return 403 "Insufficient permissions" if unauthorized
    - _Requirements: 10.1, 10.2, 10.3, 10.5, 10.6_

  - [x] 15.3 Write property tests for tenant isolation and role enforcement
    - **Property 1: Tenant Data Isolation**
    - **Property 3: Role Permission Enforcement**
    - **Validates: Requirements 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.5, 10.6**

- [x] 16. Implement Interface Adapters Layer — Controllers
  - [x] 16.1 Implement AuthController (login, refresh, logout)
    - Create `src/interfaces/http/controllers/authController.py`
    - handle_login: parse body → LoginInputDTO → loginUseCase.execute → map response (200 / 401)
    - handle_refresh: parse body → refreshTokenUseCase.execute → map response (200 / 401)
    - handle_logout: parse body → logoutUseCase.execute → 204
    - _Requirements: 1.1, 2.1, 14.5_

  - [x] 16.2 Implement RegistrationController
    - Create `src/interfaces/http/controllers/registrationController.py`
    - handle_register: parse body → RegisterInputDTO → registerUseCase.execute → map response (201 / 400 / 403 / 409)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 16.3 Implement AccountTypeController (create, list, update, delete)
    - Create `src/interfaces/http/controllers/accountTypeController.py`
    - Each handler: validate request → map to DTO → execute use case → map response
    - Apply TenantGuard + RoleGuard per handler
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 16.4 Implement MemberController (create/invite, list, update, deactivate)
    - Create `src/interfaces/http/controllers/memberController.py`
    - handle_create: TenantGuard(manage_members) → parse body → inviteUserUseCase.execute → 201
    - handle_list: TenantGuard(read) → parse query params → listMembersUseCase.execute → 200
    - handle_update: TenantGuard(manage_members) → parse body → updateMemberUseCase.execute → 200
    - handle_deactivate: TenantGuard(manage_members) → deactivateMemberUseCase.execute → 204
    - _Requirements: 4.1, 6.1, 7.1, 8.1_

- [x] 17. Implement Interface Adapters Layer — Shared Utilities and Request DTOs
  - [x] 17.1 Implement error handler and response builder
    - Create `src/interfaces/shared/errorHandler.py` — Map domain errors to HTTP status codes (400, 401, 403, 404, 409, 429, 500)
    - Create `src/interfaces/shared/responseBuilder.py` — Standardized API response format
    - _Requirements: N/A (cross-cutting)_

  - [x] 17.2 Create HTTP request/response DTOs and validation middleware
    - Create `src/interfaces/http/dtos/loginRequest.py`, `registerRequest.py`, `createAccountTypeRequest.py`, `createMemberRequest.py`, `apiResponse.py`
    - Create `src/interfaces/http/middleware/validationMiddleware.py` — Schema validation for request bodies
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [x] 18. Implement Lambda Handlers and Composition Root
  - [x] 18.1 Create Composition Root (dependency injection container)
    - Create `src/interfaces/http/compositionRoot.py`
    - Instantiate all infrastructure implementations (repositories, auth service)
    - Wire use cases with their port dependencies via constructor injection
    - Wire controllers with their use cases
    - Lazy initialization on cold start, reuse on warm invocations
    - _Requirements: N/A (architecture wiring)_

  - [x] 18.2 Create Lambda handler entry points
    - Create `src/interfaces/http/handlers/authHandler.py` — POST /auth/login, POST /auth/refresh, POST /auth/logout
    - Create `src/interfaces/http/handlers/registrationHandler.py` — POST /auth/register
    - Create `src/interfaces/http/handlers/accountTypeHandler.py` — POST/GET/PUT/DELETE /account-types
    - Create `src/interfaces/http/handlers/memberHandler.py` — POST/GET/PUT/DELETE /members
    - Each handler: compose middleware + controller, handle request routing
    - _Requirements: N/A (infrastructure wiring)_

- [x] 19. Checkpoint — All layers implemented
  - Ensure all tests pass, ask the user if questions arise.

- [x] 20. Integration testing and final verification
  - [x] 20.1 Write integration tests for authentication flow
    - Test login → use token → refresh → logout end-to-end
    - Test invalid credentials return same error
    - Test token expiry triggers 401
    - **Property 12: Token Contains Correct Roles**
    - **Validates: Requirements 1.1, 1.2, 1.7, 2.1, 14.5**

  - [x] 20.2 Write integration tests for registration flows
    - Test self-registration complete flow (register → auto-login → access)
    - Test admin invitation flow (invite → check user created with pending_confirmation)
    - Test atomicity (partial failures don't leave orphan records)
    - **Property 8: Registration Atomicity**
    - **Validates: Requirements 3.1, 3.7, 4.1, 4.2, 12.1, 12.2, 12.3**

  - [x] 20.3 Write integration tests for tenant isolation and CRUD operations
    - Test that data queries are isolated per tenant
    - Test account type CRUD (create, list, update, delete)
    - Test member management (list with filters, update, deactivate)
    - **Property 1: Tenant Data Isolation**
    - **Property 18: Pagination Bounded Response**
    - **Validates: Requirements 5.1, 5.4, 6.1, 6.4, 8.1, 9.1, 9.3**

  - [x] 20.4 Write property test for pagination correctness
    - **Property 18: Pagination Bounded Response**
    - **Validates: Requirements 5.4, 6.1, 6.4, 6.5**
    - Verify max 100 items per page
    - Verify cursor-based pagination returns non-overlapping results

- [x] 21. Final checkpoint — All implementations and tests complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation follows Clean Architecture layer order: Domain → Application → Infrastructure → Interface Adapters
- Python is the implementation language with hypothesis for property-based testing and pytest as test runner
- Naming conventions: variables=snake_case, functions/methods=snake_case, classes=PascalCase, files/folders=snake_case, constants=UPPER_SNAKE_CASE
- DynamoDB single table design keys and GSIs are encapsulated within repository implementations (Infrastructure layer)
- All use cases depend on port interfaces, never on concrete implementations

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4", "3.1"] },
    { "id": 3, "tasks": ["2.5", "3.2", "3.3", "3.4", "3.5", "3.6"] },
    { "id": 4, "tasks": ["3.7", "4.1", "4.2", "4.3"] },
    { "id": 5, "tasks": ["5.1", "5.2"] },
    { "id": 6, "tasks": ["6.1", "6.3", "6.5", "7.1", "7.3", "8.1", "8.2", "8.3", "8.4", "9.1", "9.2", "9.3"] },
    { "id": 7, "tasks": ["6.2", "6.4", "7.2", "8.5", "9.4"] },
    { "id": 8, "tasks": ["11.1"] },
    { "id": 9, "tasks": ["11.2"] },
    { "id": 10, "tasks": ["12.1", "12.2", "12.3", "12.4", "12.5", "13.1"] },
    { "id": 11, "tasks": ["13.2"] },
    { "id": 12, "tasks": ["15.1", "15.2", "17.1", "17.2"] },
    { "id": 13, "tasks": ["15.3", "16.1", "16.2", "16.3", "16.4"] },
    { "id": 14, "tasks": ["18.1"] },
    { "id": 15, "tasks": ["18.2"] },
    { "id": 16, "tasks": ["20.1", "20.2", "20.3", "20.4"] }
  ]
}
```
