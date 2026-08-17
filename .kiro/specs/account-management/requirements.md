# Requirements Document

## Introduction

Este documento define los requisitos del sistema de gestión de cuentas (Account Management) para un backend multi-tenant serverless. El sistema permite a instituciones deportivas gestionar tipos de cuentas, miembros, autenticación y control de acceso basado en roles. Soporta registro por invitación del administrador y auto-registro, con aislamiento completo de datos entre tenants.

## Glossary

- **System**: El backend de gestión de cuentas (Account Management API)
- **Tenant**: Una institución deportiva que opera de forma independiente con sus propios datos
- **Admin**: Usuario con rol de administrador que gestiona miembros, tipos de cuenta y roles dentro de un tenant
- **Manager**: Usuario con rol de gestor que puede crear y actualizar miembros y tipos de cuenta
- **Viewer**: Usuario con rol de solo lectura
- **Member**: Una persona registrada dentro de un tenant con un tipo de cuenta asignado
- **AccountType**: Clasificación de miembros dentro de un tenant (ej: socio, usuario, profesional)
- **Token_Pair**: Conjunto de access token (JWT) y refresh token emitido tras autenticación exitosa
- **Value_Object**: Objeto inmutable del dominio con validación incorporada (Email, Password, TenantId)
- **Port**: Interfaz abstracta definida en la capa de aplicación que las implementaciones de infraestructura satisfacen
- **Use_Case**: Operación de negocio encapsulada en la capa de aplicación
- **Session**: Registro de refresh token asociado a un usuario y tenant con TTL

## Requirements

### Requirement 1: User Authentication (Login)

**User Story:** As a registered user, I want to authenticate with my email and password, so that I can obtain access tokens to interact with the system.

#### Acceptance Criteria

1. WHEN a user submits valid email, password, and tenantId credentials, THE System SHALL verify the credentials against the stored password hash, confirm the user has an active membership in the specified tenant, and return a Token_Pair containing an access token and a refresh token
2. IF the submitted email does not correspond to any registered user, THEN THE System SHALL return an "Invalid credentials" error without revealing whether the email exists
3. IF the submitted email exists but the password is incorrect, THEN THE System SHALL return an "Invalid credentials" error without revealing that the email exists
4. IF the user's account status is not "active", THEN THE System SHALL reject the authentication and return an "Account is not active" error
5. IF the user does not have an active membership in the specified tenantId, THEN THE System SHALL return an "Invalid credentials" error without revealing membership status
6. WHEN authentication succeeds, THE System SHALL create a session record containing the hashed refresh token, the userId, and the tenantId, with a TTL of 7 days
7. WHEN authentication succeeds, THE System SHALL include the user's roles for the specified tenant in the generated access token payload

### Requirement 2: Token Refresh

**User Story:** As an authenticated user, I want to refresh my access token without re-entering credentials, so that I can maintain my session seamlessly.

#### Acceptance Criteria

1. WHEN a user submits a valid, non-expired refresh token, THE System SHALL generate a new Token_Pair and invalidate the old refresh token
2. WHEN a user submits an expired refresh token, THE System SHALL return a 401 "Refresh token expired" error
3. WHEN a user submits an invalid or already-used refresh token, THE System SHALL return a 401 "Invalid refresh token" error
4. WHEN token rotation succeeds, THE System SHALL atomically delete the old session and create a new session with a TTL of 7 days
5. IF the user associated with the refresh token has a status other than "active", THEN THE System SHALL reject the refresh request with a 401 "Account is not active" error and invalidate the session
6. WHEN generating the new Token_Pair during refresh, THE System SHALL retrieve the user's current roles for the tenant and include them in the new access token payload

### Requirement 3: Self-Registration

**User Story:** As a new user, I want to register myself in an institution that allows self-registration, so that I can become a member without requiring admin intervention.

#### Acceptance Criteria

1. WHEN a user submits valid registration data (email, password, fullName, tenantId), THE System SHALL create a User record with status "active", TenantMembership, Member, and default "viewer" Role atomically
2. IF a user attempts to register with an email already in the database, THEN THE System SHALL return a "Email already registered" error without creating any records
3. IF a user attempts to register in a tenant that does not exist, THEN THE System SHALL return a "Tenant not found" error
4. IF a user attempts to register in a tenant with status other than "active", THEN THE System SHALL return a "Tenant is not active" error
5. IF a user attempts to register in a tenant where allowSelfRegistration is false, THEN THE System SHALL return a "Self-registration is not allowed for this institution" error
6. WHEN a user registers without specifying an accountType, THE System SHALL assign the tenant's defaultAccountType; IF the defaultAccountType is null or inactive, THEN THE System SHALL assign "usuario" as fallback
7. WHEN registration succeeds, THE System SHALL create a session and return a Token_Pair so the user is immediately authenticated
8. IF a user specifies an accountType that does not exist or is inactive in the tenant, THEN THE System SHALL return an "Invalid account type" error

### Requirement 4: Admin-Invited Member Creation

**User Story:** As an admin, I want to invite new members to my institution, so that I can onboard users with specific account types and roles.

#### Acceptance Criteria

1. WHEN an admin submits valid member data (email, fullName, accountType, roles) for a new user, THE System SHALL create a User with status "pending_confirmation", TenantMembership, Member with status "active", and assigned Roles atomically
2. WHEN an admin invites a user whose email already exists in the system but is not a member of the tenant, THE System SHALL create only TenantMembership, Member, and Roles without creating a new User record
3. IF an admin attempts to invite a user who is already a member of the tenant, THEN THE System SHALL return a "User is already a member of this tenant" error
4. IF an admin specifies an accountType that does not exist in the tenant, THEN THE System SHALL return an "Account type does not exist in this tenant" error
5. IF an admin specifies an accountType that is inactive, THEN THE System SHALL return an "Account type is not active" error
6. IF an admin specifies an empty roles array or invalid role names, THEN THE System SHALL return an "Invalid role" error
7. WHEN a new user is created by invitation, THE System SHALL generate a temporary password of at least 16 characters and store it hashed using bcrypt

### Requirement 5: Account Type CRUD

**User Story:** As an admin or manager, I want to create, list, update, and delete account types, so that I can define the classification structure for members in my institution.

#### Acceptance Criteria

1. WHEN an authorized user creates an account type with a valid name and description, THE System SHALL persist the account type with status "active" and return the created record with a generated UUID, createdAt, and updatedAt timestamps
2. IF a user attempts to create an account type with a name that already exists in the tenant (case-insensitive comparison), THEN THE System SHALL return a "Account type name already exists in this tenant" error
3. IF a user attempts to create an account type with an empty name or a name exceeding 100 characters, THEN THE System SHALL reject the request with a validation error specifying the constraint violated
4. WHEN an authorized user requests the list of account types, THE System SHALL return only active and inactive account types belonging to the requesting user's tenant with pagination support (max 100 items per page)
5. WHEN an authorized user updates an account type's name, THE System SHALL verify the new name is unique within the tenant (case-insensitive) before applying the update and refresh the updatedAt timestamp
6. WHEN an admin deletes an account type that has no active members assigned, THE System SHALL set its status to "inactive" while preserving the record and refreshing updatedAt
7. IF an admin attempts to delete an account type that has active members assigned, THEN THE System SHALL return a "Cannot delete account type: active members are using it" error

### Requirement 6: Member Management (List and Filter)

**User Story:** As an admin or manager, I want to list and filter members by account type and status, so that I can efficiently manage the institution's membership.

#### Acceptance Criteria

1. WHEN an authorized user requests the member list for a tenant without filters, THE System SHALL return all members belonging to that tenant with pagination support (max 100 items per page)
2. WHEN an authorized user filters members by accountType, THE System SHALL return only members whose accountType matches the specified value (case-insensitive)
3. WHEN an authorized user filters members by status, THE System SHALL return only members whose status field matches the specified value exactly
4. WHEN more results exist beyond the current page, THE System SHALL include a pagination cursor (nextKey) in the response that can be used to retrieve the next page
5. WHEN a pagination cursor is provided, THE System SHALL return results starting after the cursor position

### Requirement 7: Member Update

**User Story:** As an admin or manager, I want to update member information including their account type, so that I can maintain accurate member records.

#### Acceptance Criteria

1. WHEN an authorized user updates a member's accountType, THE System SHALL validate that the new accountType exists and is active in the tenant before applying the change
2. IF an authorized user attempts to update a member that does not exist in the tenant, THEN THE System SHALL return a "Member not found" error
3. WHEN a member is updated, THE System SHALL refresh the updatedAt timestamp while preserving the original createdAt, registrationType, and invitedBy values
4. IF an authorized user attempts to change a member's accountType to one that does not exist in the tenant, THEN THE System SHALL return an "Account type does not exist in this tenant" error
5. IF an authorized user attempts to change a member's accountType to one that is inactive, THEN THE System SHALL return an "Account type is not active" error

### Requirement 8: Member Deactivation

**User Story:** As an admin, I want to deactivate members, so that I can revoke their access while preserving their records for audit purposes.

#### Acceptance Criteria

1. WHEN an admin deactivates an active member, THE System SHALL set the member's status to "inactive", refresh updatedAt, and invalidate all sessions for that user in the tenant
2. IF an admin attempts to deactivate a member that is already inactive, THEN THE System SHALL return a "Member is already inactive" error
3. IF an admin attempts to deactivate a member that does not exist in the tenant, THEN THE System SHALL return a "Member not found" error
4. WHEN a member is deactivated, THE System SHALL preserve the full member record in the database including all historical fields for audit purposes
5. WHEN a member is deactivated, THE System SHALL NOT modify or delete the associated User record, allowing the user to remain active in other tenants

### Requirement 9: Tenant Isolation

**User Story:** As a tenant administrator, I want to ensure that my institution's data is completely isolated from other institutions, so that there is no unauthorized cross-tenant data access.

#### Acceptance Criteria

1. THE System SHALL enforce that every authenticated data query includes the requesting user's tenantId as a mandatory filter, derived from the JWT token payload
2. WHEN a request contains a JWT token, THE System SHALL extract the tenantId from the token payload and use it for all subsequent data access operations
3. IF an authenticated user's tenantId does not match the requested resource's tenantId, THEN THE System SHALL reject the request with a 403 Forbidden response and not disclose the existence of the resource
4. THE System SHALL ensure that member, account type, role, and session records are partitioned by tenantId in the data store
5. IF a JWT token does not contain a tenantId claim, THEN THE System SHALL reject the request with a 401 error indicating an invalid token

### Requirement 10: Role-Based Access Control

**User Story:** As a system operator, I want to enforce role-based permissions, so that users can only perform actions authorized by their assigned roles.

#### Acceptance Criteria

1. WHEN a user with "viewer" role attempts a write operation (create, update, delete), THE System SHALL return a 403 "Insufficient permissions" error
2. WHEN a user with "manager" role attempts to delete an account type or deactivate a member, THE System SHALL return a 403 "Insufficient permissions" error
3. WHEN a user with "admin" role performs any operation within their tenant, THE System SHALL allow the operation
4. WHEN a request lacks a valid Authorization header, THE System SHALL return a 401 "Missing or invalid authorization header" error
5. THE System SHALL validate role permissions before executing any use case operation
6. IF a user has multiple roles within a tenant, THEN THE System SHALL grant the union of all permissions from all assigned roles, applying the least restrictive access

### Requirement 11: Input Validation (Value Objects)

**User Story:** As the system, I want to validate all inputs at the domain boundary, so that only well-formed data reaches the business logic.

#### Acceptance Criteria

1. WHEN an email input does not conform to valid email format or exceeds 254 characters, THE System SHALL return a validation error specifying "Invalid email format"
2. WHEN a password input is shorter than 8 characters or exceeds 72 characters, THE System SHALL return a validation error specifying the length requirement
3. WHEN a fullName input is empty or exceeds 200 characters, THE System SHALL return a validation error specifying the constraint violated
4. WHEN a tenantId input is empty or is not a valid UUID format, THE System SHALL return a validation error specifying "Invalid tenant ID"
5. THE System SHALL perform input validation through Value Objects in the Domain layer before any business logic executes

### Requirement 12: Atomic Transactions

**User Story:** As a system architect, I want all multi-record operations to be atomic, so that the database never contains partial or inconsistent state.

#### Acceptance Criteria

1. WHEN self-registration creates User, TenantMembership, Member, and Role records, THE System SHALL persist all records in a single atomic transaction
2. WHEN admin-invited member creation creates multiple records, THE System SHALL persist all records in a single atomic transaction
3. IF any part of an atomic transaction fails, THEN THE System SHALL roll back all changes, return an error indicating the operation failed, and leave the data store in the state it was prior to the transaction attempt
4. WHEN refresh token rotation occurs, THE System SHALL atomically delete the old session and create the new session

### Requirement 13: Password Security

**User Story:** As a security-conscious system, I want to store passwords securely, so that user credentials are protected even if the database is compromised.

#### Acceptance Criteria

1. THE System SHALL hash all passwords using bcrypt with a minimum of 10 salt rounds before storage
2. THE System SHALL never store or return plain-text passwords in any response or log
3. WHEN verifying credentials, THE System SHALL use constant-time comparison via bcrypt to prevent timing attacks
4. WHEN generating temporary passwords for invited users, THE System SHALL produce cryptographically secure random strings of at least 16 characters
5. THE System SHALL reject passwords exceeding 72 characters at the input validation boundary to prevent bcrypt silent truncation

### Requirement 14: Session Management

**User Story:** As the system, I want to manage user sessions with expiring refresh tokens, so that long-lived access is controlled and revocable.

#### Acceptance Criteria

1. THE System SHALL set access token expiration to 1 hour
2. THE System SHALL set refresh token expiration to 7 days
3. WHEN a member is deactivated, THE System SHALL invalidate all active sessions for that user within the tenant
4. THE System SHALL store refresh tokens as hashed values, never in plain text
5. WHEN a user explicitly logs out, THE System SHALL delete the session associated with the provided refresh token
