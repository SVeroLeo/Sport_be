# Implementation Plan: Account Management

## Overview

Implementación del sistema de gestión de cuentas multi-tenant siguiendo Clean Architecture con TypeScript, AWS Lambda, API Gateway y DynamoDB single table design. El plan sigue el orden de capas: Domain → Application → Infrastructure → Interface Adapters, asegurando que cada capa se construya sobre las anteriores.

## Tasks

- [ ] 1. Set up project structure and configuration
  - [ ] 1.1 Initialize TypeScript project with package.json, tsconfig.json, and install core dependencies (aws-sdk/client-dynamodb, aws-sdk/lib-dynamodb, bcrypt, jsonwebtoken, uuid)
    - Configure strict TypeScript, path aliases for `@domain`, `@application`, `@infrastructure`, `@interfaces`
    - Install dev dependencies: vitest, fast-check, @types/bcrypt, @types/jsonwebtoken, @types/uuid
    - _Requirements: N/A (project setup)_

  - [ ] 1.2 Create directory structure following Clean Architecture layout
    - Create `src/domain/entities/`, `src/domain/valueObjects/`, `src/domain/errors/`
    - Create `src/application/useCases/`, `src/application/dtos/`, `src/application/ports/`
    - Create `src/infrastructure/persistence/`, `src/infrastructure/auth/`, `src/infrastructure/config/`, `src/infrastructure/mappers/`
    - Create `src/interfaces/http/controllers/`, `src/interfaces/http/middleware/`, `src/interfaces/http/dtos/`, `src/interfaces/shared/`
    - _Requirements: N/A (project setup)_

- [ ] 2. Implement Domain Layer — Value Objects
  - [ ] 2.1 Implement Email value object with validation (valid format, max 254 chars)
    - Create `src/domain/valueObjects/email.ts`
    - Static factory method `Email.create(value: string)` returning `Email | ValidationError`
    - Immutable, stores normalized (trimmed, lowercased) value
    - _Requirements: 11.1_

  - [ ] 2.2 Implement Password value object with validation (min 8, max 72 chars)
    - Create `src/domain/valueObjects/password.ts`
    - Static factory method `Password.create(value: string)` returning `Password | ValidationError`
    - Include `Password.createUnsafe(value: string)` for system-generated passwords
    - _Requirements: 11.2, 13.5_

  - [ ] 2.3 Implement TenantId value object with UUID validation
    - Create `src/domain/valueObjects/tenantId.ts`
    - Static factory method `TenantId.create(value: string)` returning `TenantId | ValidationError`
    - Validates non-empty and valid UUID format
    - _Requirements: 11.4_

  - [ ] 2.4 Implement remaining value objects (MemberId, AccountTypeId, RoleName, FullName)
    - Create `src/domain/valueObjects/memberId.ts`, `accountTypeId.ts`, `roleName.ts`, `fullName.ts`
    - FullName: non-empty, max 200 chars
    - RoleName: must be one of "admin", "manager", "viewer"
    - _Requirements: 11.3, 11.5_

  - [ ]* 2.5 Write property tests for Value Objects
    - **Property 17: Value Object Validation Gate**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 13.5**
    - Verify that invalid inputs never pass validation
    - Verify that valid inputs always produce valid value objects

- [ ] 3. Implement Domain Layer — Entities and Errors
  - [ ] 3.1 Implement domain error hierarchy
    - Create `src/domain/errors/domainError.ts` (base class)
    - Create `src/domain/errors/validationError.ts`
    - Create `src/domain/errors/invalidCredentialsError.ts`
    - Create `src/domain/errors/tenantNotFoundError.ts`
    - Create `src/domain/errors/conflictError.ts`, `notFoundError.ts`, `forbiddenError.ts`
    - _Requirements: N/A (cross-cutting domain concern)_

  - [ ] 3.2 Implement User entity
    - Create `src/domain/entities/user.ts`
    - Fields: userId, email, passwordHash, fullName, status (active|inactive|suspended|pending_confirmation), createdAt, updatedAt
    - Static factory `User.create(...)` with domain validation
    - _Requirements: 1.1, 3.1, 4.1_

  - [ ] 3.3 Implement Tenant entity
    - Create `src/domain/entities/tenant.ts`
    - Fields: tenantId, name, plan, status, allowSelfRegistration, defaultAccountType, createdAt
    - _Requirements: 3.3, 3.4, 3.5_

  - [ ] 3.4 Implement Member entity
    - Create `src/domain/entities/member.ts`
    - Fields: memberId, tenantId, userId, accountType, accountTypeId, fullName, email, status, registrationType, invitedBy, metadata, createdAt, updatedAt
    - Static factory `Member.create(...)` with validation
    - _Requirements: 4.1, 6.1, 7.3_

  - [ ] 3.5 Implement AccountType entity
    - Create `src/domain/entities/accountType.ts`
    - Fields: accountTypeId, tenantId, name, description, config, status, createdAt, updatedAt
    - Static factory `AccountType.create(...)` with name validation (non-empty, max 100 chars)
    - _Requirements: 5.1, 5.3_

  - [ ] 3.6 Implement Session entity and supporting types (TenantMembership, UserRole, TokenPair)
    - Create `src/domain/entities/session.ts` — Fields: pk, sk, refreshToken (hash), tenantId, expiresAt, createdAt, ttl
    - Create `src/domain/entities/tenantMembership.ts`
    - Create `src/domain/entities/userRole.ts` with RoleDefinition constants and permissions
    - Create `src/domain/entities/tokenPair.ts`
    - _Requirements: 10.1, 10.6, 14.1, 14.2_

  - [ ]* 3.7 Write unit tests for domain entities
    - Test entity creation with valid and invalid data
    - Test User status transitions
    - Test AccountType name validation constraints
    - Test RoleDefinition permission sets
    - _Requirements: 5.3, 10.1, 10.2, 10.3_

- [ ] 4. Implement Application Layer — Ports (Interfaces)
  - [ ] 4.1 Define IUserRepository port interface
    - Create `src/application/ports/iUserRepository.ts`
    - Methods: find_by_email, find_by_id, save, get_roles_for_tenant, register_with_membership, create_user_with_membership
    - _Requirements: 1.1, 3.1, 4.1, 4.2, 12.1, 12.2_

  - [ ] 4.2 Define IMemberRepository port interface
    - Create `src/application/ports/iMemberRepository.ts`
    - Methods: find_by_id, find_by_user_in_tenant, find_by_tenant_and_filters, save, update, create_member_with_roles, count_active_by_account_type
    - _Requirements: 5.7, 6.1, 6.2, 6.3, 7.1, 8.1_

  - [ ] 4.3 Define IAccountTypeRepository, ISessionRepository, ITenantRepository, and IAuthService port interfaces
    - Create `src/application/ports/iAccountTypeRepository.ts` — find_by_id, find_by_name_in_tenant, find_all_by_tenant, save, update
    - Create `src/application/ports/iSessionRepository.ts` — create_session, find_by_token_hash, delete_session, delete_all_for_user_in_tenant, rotate_token
    - Create `src/application/ports/iTenantRepository.ts` — find_by_id
    - Create `src/application/ports/iAuthService.ts` — hash_password, verify_password, generate_token_pair, verify_access_token, generate_secure_random, hash_token
    - _Requirements: 2.1, 2.4, 5.4, 13.1, 13.3, 14.4_

- [ ] 5. Implement Application Layer — DTOs
  - [ ] 5.1 Create authentication DTOs (login, register, refresh, token output)
    - Create `src/application/dtos/auth/loginInputDTO.ts`, `loginOutputDTO.ts`
    - Create `src/application/dtos/auth/registerInputDTO.ts`, `registerOutputDTO.ts`
    - Create `src/application/dtos/auth/refreshInputDTO.ts`
    - _Requirements: 1.1, 2.1, 3.1_

  - [ ] 5.2 Create account type and member DTOs
    - Create `src/application/dtos/accountType/createAccountTypeInputDTO.ts`, `updateAccountTypeInputDTO.ts`, `accountTypeOutputDTO.ts`, `paginatedAccountTypesDTO.ts`
    - Create `src/application/dtos/member/createMemberInputDTO.ts`, `updateMemberInputDTO.ts`, `memberOutputDTO.ts`, `paginatedMembersDTO.ts`
    - Create shared pagination types (`src/application/dtos/shared/paginationParams.ts`)
    - _Requirements: 4.1, 5.1, 6.1, 7.1_

- [ ] 6. Implement Application Layer — Authentication Use Cases
  - [ ] 6.1 Implement LoginUseCase
    - Create `src/application/useCases/auth/loginUseCase.ts`
    - Validate Email VO, find user, check status, verify password, get roles for tenant, generate token pair, create session
    - Return generic "Invalid credentials" for all failure modes (email not found, wrong password, no membership)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ]* 6.2 Write property test for LoginUseCase credential error opacity
    - **Property 2: Credential Error Opacity**
    - **Validates: Requirements 1.2, 1.3, 1.5**

  - [ ] 6.3 Implement RefreshTokenUseCase
    - Create `src/application/useCases/auth/refreshTokenUseCase.ts`
    - Find session by token hash, check expiry, check user status, get current roles, generate new pair, rotate session atomically
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 6.4 Write property test for RefreshTokenUseCase single-use rotation
    - **Property 6: Refresh Token Single-Use Rotation**
    - **Validates: Requirements 2.1, 2.4, 2.5, 12.4**

  - [ ] 6.5 Implement LogoutUseCase
    - Create `src/application/useCases/auth/logoutUseCase.ts`
    - Delete session associated with the provided refresh token
    - _Requirements: 14.5_

- [ ] 7. Implement Application Layer — Registration Use Cases
  - [ ] 7.1 Implement RegisterUseCase (self-registration)
    - Create `src/application/useCases/registration/registerUseCase.ts`
    - Validate VOs, check email uniqueness, verify tenant (exists, active, allowSelfRegistration), determine accountType (explicit → defaultAccountType → "usuario" fallback), hash password, create User+Membership+Member+Role atomically, generate tokens, create session
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [ ]* 7.2 Write property tests for RegisterUseCase
    - **Property 8: Registration Atomicity**
    - **Property 13: Self-Registration Gate**
    - **Property 14: Default AccountType Assignment**
    - **Property 15: Email Uniqueness Enforcement**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 12.1**

  - [ ] 7.3 Implement InviteUserUseCase (admin-invited member creation)
    - Create `src/application/useCases/registration/inviteUserUseCase.ts`
    - Validate accountType (exists, active), check if user exists, if new → create User with temp password (status: pending_confirmation) + Membership + Member + Roles atomically; if existing → check not already member, create Membership + Member + Roles
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

- [ ] 8. Implement Application Layer — Account Type Use Cases
  - [ ] 8.1 Implement CreateAccountTypeUseCase
    - Create `src/application/useCases/accountType/createAccountTypeUseCase.ts`
    - Verify tenant, check name uniqueness (case-insensitive), create entity with status "active", persist
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 8.2 Implement ListAccountTypesUseCase
    - Create `src/application/useCases/accountType/listAccountTypesUseCase.ts`
    - Query by tenant with pagination (max 100 per page)
    - _Requirements: 5.4_

  - [ ] 8.3 Implement UpdateAccountTypeUseCase
    - Create `src/application/useCases/accountType/updateAccountTypeUseCase.ts`
    - Find existing, validate name uniqueness if changed, update, refresh updatedAt
    - _Requirements: 5.5_

  - [ ] 8.4 Implement DeleteAccountTypeUseCase (soft delete)
    - Create `src/application/useCases/accountType/deleteAccountTypeUseCase.ts`
    - Check active members count, reject if > 0, else set status to "inactive"
    - _Requirements: 5.6, 5.7_

  - [ ]* 8.5 Write property tests for Account Type use cases
    - **Property 4: AccountType Name Uniqueness per Tenant**
    - **Property 9: AccountType Deletion Protection**
    - **Validates: Requirements 5.2, 5.5, 5.7**

- [ ] 9. Implement Application Layer — Member Use Cases
  - [ ] 9.1 Implement ListMembersUseCase
    - Create `src/application/useCases/member/listMembersUseCase.ts`
    - Query by tenant with filters (accountType case-insensitive, status exact match) and pagination
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 9.2 Implement UpdateMemberUseCase
    - Create `src/application/useCases/member/updateMemberUseCase.ts`
    - Find member, validate new accountType if changed (exists and active), apply updates, preserve immutable fields (createdAt, registrationType, invitedBy), refresh updatedAt
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ] 9.3 Implement DeactivateMemberUseCase
    - Create `src/application/useCases/member/deactivateMemberUseCase.ts`
    - Find member, check not already inactive, set status to "inactive", invalidate all sessions in tenant, preserve User record
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 9.4 Write property tests for Member use cases
    - **Property 5: Soft Delete Preservation**
    - **Property 7: Member-AccountType Referential Integrity**
    - **Property 11: Session Invalidation on Deactivation**
    - **Property 16: Member Update Preserves Immutable Fields**
    - **Property 19: Filter Correctness**
    - **Property 20: User Record Preservation on Member Deactivation**
    - **Validates: Requirements 5.6, 7.3, 7.4, 7.5, 8.1, 8.4, 8.5**

- [ ] 10. Checkpoint — Domain and Application layers complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement Infrastructure Layer — DynamoDB Client and Config
  - [ ] 11.1 Create DynamoDB client configuration and environment config
    - Create `src/infrastructure/config/environment.ts` — Read TABLE_NAME, REGION, JWT_SECRET, TOKEN_EXPIRY, SALT_ROUNDS from env
    - Create `src/infrastructure/config/dynamoDBClient.ts` — Singleton DynamoDB DocumentClient setup
    - _Requirements: N/A (infrastructure setup)_

  - [ ] 11.2 Create entity-to-DynamoDB item mappers
    - Create `src/infrastructure/mappers/userMapper.ts` — User entity ↔ DynamoDB item with PK=USER#{email}, SK=PROFILE
    - Create `src/infrastructure/mappers/memberMapper.ts` — Member entity ↔ DynamoDB item with PK, SK, GSI1PK, GSI1SK, GSI2PK, GSI2SK
    - Create `src/infrastructure/mappers/accountTypeMapper.ts` — AccountType entity ↔ DynamoDB item with PK, SK, GSI1PK, GSI1SK
    - Create `src/infrastructure/mappers/sessionMapper.ts` — Session entity ↔ DynamoDB item with PK=SESSION#{userId}, SK=TOKEN#{tokenId}, TTL
    - _Requirements: 9.4_

- [ ] 12. Implement Infrastructure Layer — Repository Implementations
  - [ ] 12.1 Implement DynamoDBUserRepository
    - Create `src/infrastructure/persistence/dynamoDBUserRepository.ts`
    - Implement find_by_email (GetItem PK=USER#{email}, SK=PROFILE)
    - Implement get_roles_for_tenant (Query PK=TENANT#{tid}#USER#{uid}, SK begins_with ROLE#)
    - Implement register_with_membership (TransactWriteItems for User + Membership + Member + Role)
    - Implement create_user_with_membership (TransactWriteItems)
    - _Requirements: 1.1, 3.1, 4.1, 4.2, 12.1, 12.2_

  - [ ] 12.2 Implement DynamoDBMemberRepository
    - Create `src/infrastructure/persistence/dynamoDBMemberRepository.ts`
    - Implement find_by_id (GetItem)
    - Implement find_by_user_in_tenant (Query GSI2)
    - Implement find_by_tenant_and_filters (Query with accountType → GSI1, else base table; handle pagination cursor)
    - Implement count_active_by_account_type (Query GSI1 with filter)
    - Implement create_member_with_roles (TransactWriteItems)
    - _Requirements: 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 12.2_

  - [ ] 12.3 Implement DynamoDBAccountTypeRepository
    - Create `src/infrastructure/persistence/dynamoDBAccountTypeRepository.ts`
    - Implement find_by_id (GetItem PK=TENANT#{tid}#ACCTYPE, SK=ACCTYPE#{id})
    - Implement find_by_name_in_tenant (Query GSI1 with PK=TENANT#{tid}#ACCTYPE, SK=NAME#{lowercase(name)})
    - Implement find_all_by_tenant (Query with pagination)
    - Implement save and update
    - _Requirements: 5.1, 5.2, 5.4, 5.5_

  - [ ] 12.4 Implement DynamoDBSessionRepository
    - Create `src/infrastructure/persistence/dynamoDBSessionRepository.ts`
    - Implement create_session with TTL
    - Implement find_by_token_hash
    - Implement delete_session, delete_all_for_user_in_tenant (batch delete)
    - Implement rotate_token (TransactWriteItems — delete old + put new atomically)
    - _Requirements: 2.1, 2.4, 8.1, 12.4, 14.3, 14.4, 14.5_

  - [ ] 12.5 Implement DynamoDBTenantRepository
    - Create `src/infrastructure/persistence/dynamoDBTenantRepository.ts`
    - Implement find_by_id (GetItem PK=TENANT#{tid}, SK=METADATA)
    - _Requirements: 3.3, 3.4, 3.5_

- [ ] 13. Implement Infrastructure Layer — Auth Service
  - [ ] 13.1 Implement JwtAuthService (implements IAuthService)
    - Create `src/infrastructure/auth/jwtAuthService.ts`
    - Implement generate_token_pair: access token (1h expiry) with userId, tenantId, email, roles in payload; refresh token (7d)
    - Implement verify_access_token: decode and verify JWT
    - Implement hash_password: bcrypt with configurable salt rounds (min 10)
    - Implement verify_password: bcrypt.compare (constant-time)
    - Implement generate_secure_random: crypto.randomBytes for temp passwords (min 16 chars)
    - Implement hash_token: SHA-256 hash for refresh tokens
    - _Requirements: 1.6, 1.7, 2.6, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.4_

  - [ ]* 13.2 Write property test for password security
    - **Property 10: Password Storage Security**
    - **Validates: Requirements 13.1, 13.2, 13.4, 4.7**

- [ ] 14. Checkpoint — Infrastructure layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Implement Interface Adapters Layer — Middleware
  - [ ] 15.1 Implement TenantGuard middleware
    - Create `src/interfaces/http/middleware/tenantGuardMiddleware.ts`
    - Extract Bearer token from Authorization header
    - Verify JWT via IAuthService port
    - Extract tenantId from token payload, reject if missing (401)
    - Return TenantContext { userId, tenantId, roles, email }
    - _Requirements: 9.1, 9.2, 9.5, 10.4_

  - [ ] 15.2 Implement RoleGuard middleware
    - Create `src/interfaces/http/middleware/roleGuardMiddleware.ts`
    - Check user roles against required permission for the action
    - Union of permissions across multiple roles (least restrictive)
    - Return 403 "Insufficient permissions" if unauthorized
    - _Requirements: 10.1, 10.2, 10.3, 10.5, 10.6_

  - [ ]* 15.3 Write property tests for tenant isolation and role enforcement
    - **Property 1: Tenant Data Isolation**
    - **Property 3: Role Permission Enforcement**
    - **Validates: Requirements 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.5, 10.6**

- [ ] 16. Implement Interface Adapters Layer — Controllers
  - [ ] 16.1 Implement AuthController (login, refresh, logout)
    - Create `src/interfaces/http/controllers/authController.ts`
    - handle_login: parse body → LoginInputDTO → loginUseCase.execute → map response (200 / 401)
    - handle_refresh: parse body → refreshTokenUseCase.execute → map response (200 / 401)
    - handle_logout: parse body → logoutUseCase.execute → 204
    - _Requirements: 1.1, 2.1, 14.5_

  - [ ] 16.2 Implement RegistrationController
    - Create `src/interfaces/http/controllers/registrationController.ts`
    - handle_register: parse body → RegisterInputDTO → registerUseCase.execute → map response (201 / 400 / 403 / 409)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ] 16.3 Implement AccountTypeController (create, list, update, delete)
    - Create `src/interfaces/http/controllers/accountTypeController.ts`
    - Each handler: validate request → map to DTO → execute use case → map response
    - Apply TenantGuard + RoleGuard per handler
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ] 16.4 Implement MemberController (create/invite, list, update, deactivate)
    - Create `src/interfaces/http/controllers/memberController.ts`
    - handle_create: TenantGuard(manage_members) → parse body → inviteUserUseCase.execute → 201
    - handle_list: TenantGuard(read) → parse query params → listMembersUseCase.execute → 200
    - handle_update: TenantGuard(manage_members) → parse body → updateMemberUseCase.execute → 200
    - handle_deactivate: TenantGuard(manage_members) → deactivateMemberUseCase.execute → 204
    - _Requirements: 4.1, 6.1, 7.1, 8.1_

- [ ] 17. Implement Interface Adapters Layer — Shared Utilities and Request DTOs
  - [ ] 17.1 Implement error handler and response builder
    - Create `src/interfaces/shared/errorHandler.ts` — Map domain errors to HTTP status codes (400, 401, 403, 404, 409, 429, 500)
    - Create `src/interfaces/shared/responseBuilder.ts` — Standardized API response format
    - _Requirements: N/A (cross-cutting)_

  - [ ] 17.2 Create HTTP request/response DTOs and validation middleware
    - Create `src/interfaces/http/dtos/loginRequest.ts`, `registerRequest.ts`, `createAccountTypeRequest.ts`, `createMemberRequest.ts`, `apiResponse.ts`
    - Create `src/interfaces/http/middleware/validationMiddleware.ts` — Schema validation for request bodies
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [ ] 18. Implement Lambda Handlers and Composition Root
  - [ ] 18.1 Create Composition Root (dependency injection container)
    - Create `src/interfaces/http/compositionRoot.ts`
    - Instantiate all infrastructure implementations (repositories, auth service)
    - Wire use cases with their port dependencies via constructor injection
    - Wire controllers with their use cases
    - Lazy initialization on cold start, reuse on warm invocations
    - _Requirements: N/A (architecture wiring)_

  - [ ] 18.2 Create Lambda handler entry points
    - Create `src/interfaces/http/handlers/authHandler.ts` — POST /auth/login, POST /auth/refresh, POST /auth/logout
    - Create `src/interfaces/http/handlers/registrationHandler.ts` — POST /auth/register
    - Create `src/interfaces/http/handlers/accountTypeHandler.ts` — POST/GET/PUT/DELETE /account-types
    - Create `src/interfaces/http/handlers/memberHandler.ts` — POST/GET/PUT/DELETE /members
    - Each handler: compose middleware + controller, handle request routing
    - _Requirements: N/A (infrastructure wiring)_

- [ ] 19. Checkpoint — All layers implemented
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 20. Integration testing and final verification
  - [ ]* 20.1 Write integration tests for authentication flow
    - Test login → use token → refresh → logout end-to-end
    - Test invalid credentials return same error
    - Test token expiry triggers 401
    - **Property 12: Token Contains Correct Roles**
    - **Validates: Requirements 1.1, 1.2, 1.7, 2.1, 14.5**

  - [ ]* 20.2 Write integration tests for registration flows
    - Test self-registration complete flow (register → auto-login → access)
    - Test admin invitation flow (invite → check user created with pending_confirmation)
    - Test atomicity (partial failures don't leave orphan records)
    - **Property 8: Registration Atomicity**
    - **Validates: Requirements 3.1, 3.7, 4.1, 4.2, 12.1, 12.2, 12.3**

  - [ ]* 20.3 Write integration tests for tenant isolation and CRUD operations
    - Test that data queries are isolated per tenant
    - Test account type CRUD (create, list, update, delete)
    - Test member management (list with filters, update, deactivate)
    - **Property 1: Tenant Data Isolation**
    - **Property 18: Pagination Bounded Response**
    - **Validates: Requirements 5.1, 5.4, 6.1, 6.4, 8.1, 9.1, 9.3**

  - [ ]* 20.4 Write property test for pagination correctness
    - **Property 18: Pagination Bounded Response**
    - **Validates: Requirements 5.4, 6.1, 6.4, 6.5**
    - Verify max 100 items per page
    - Verify cursor-based pagination returns non-overlapping results

- [ ] 21. Final checkpoint — All implementations and tests complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation follows Clean Architecture layer order: Domain → Application → Infrastructure → Interface Adapters
- TypeScript is the implementation language with fast-check for property-based testing
- Naming conventions: variables=camelCase, functions/methods=snake_case, classes/interfaces=PascalCase, files/folders=camelCase
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
