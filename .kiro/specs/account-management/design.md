# Design Document: Account Management (Control de Tipos de Cuentas y Gestión de Miembros)

## Overview

Este sistema provee un backend para la gestión de tipos de cuentas con operaciones CRUD, autenticación (login), registro de usuarios, gestión de miembros, soporte multi-tenant y multi-rol, utilizando AWS DynamoDB con un diseño de tabla única (single table design).

El modelo multi-tenant garantiza aislamiento de datos entre organizaciones (instituciones). Cada tenant opera de forma independiente con sus propios tipos de cuenta, miembros y usuarios. El sistema de roles permite control granular de permisos dentro de cada tenant, soportando roles como admin, manager y viewer.

Los miembros de una institución se clasifican por tipo de cuenta: **Socio** (asociado), **Usuario** (usuario genérico) y **Profesional** (entrenador/profesional). Cada miembro tiene un accountType asignado y roles dentro del tenant. El registro puede ser por auto-registro (el usuario se registra solo) o por invitación del admin.

La arquitectura serverless con DynamoDB single table design optimiza costos y latencia al consolidar todas las entidades en una sola tabla con patrones de acceso bien definidos.

**El backend está estructurado siguiendo Clean Architecture**, garantizando separación de responsabilidades, testabilidad y flexibilidad para cambiar componentes de infraestructura sin afectar la lógica de negocio.

## Architecture

### Clean Architecture Layers

La arquitectura sigue el principio de Clean Architecture (Robert C. Martin), organizando el código en capas concéntricas donde las dependencias apuntan únicamente hacia adentro.

```mermaid
graph TB
    subgraph "Infrastructure Layer (Outermost)"
        DDB[(DynamoDB)]
        APIGW[API Gateway]
        SM[Secrets Manager]
        BCR[bcrypt]
        JWTLIB[jsonwebtoken]
    end
    
    subgraph "Interface Adapters Layer"
        LC[Lambda Controllers]
        MW[Middleware - TenantGuard/RoleGuard]
        RM[Request/Response Mappers]
        REPO_IMPL[Repository Implementations]
        AUTH_IMPL[Auth Service Implementation]
    end
    
    subgraph "Application Layer (Use Cases)"
        AUTH_UC[AuthUseCase]
        REG_UC[RegistrationUseCase]
        ACCT_UC[AccountTypeUseCase]
        MEM_UC[MemberUseCase]
        DTOS[Input/Output DTOs]
    end
    
    subgraph "Domain Layer (Innermost)"
        ENT[Entities: User, Tenant, Member, AccountType, Session]
        VO[Value Objects: Email, Password, TenantId]
        DR[Domain Rules & Validation]
        DE[Domain Errors]
        EV[Domain Events]
    end
    
    %% Dependencies point INWARD only
    LC --> AUTH_UC
    LC --> REG_UC
    LC --> ACCT_UC
    LC --> MEM_UC
    MW --> AUTH_UC
    RM --> DTOS
    
    AUTH_UC --> ENT
    REG_UC --> ENT
    ACCT_UC --> ENT
    MEM_UC --> ENT
    AUTH_UC --> VO
    REG_UC --> VO
    
    REPO_IMPL --> DDB
    AUTH_IMPL --> JWTLIB
    AUTH_IMPL --> BCR
    LC --> APIGW
    
    %% Dependency Inversion: Use Cases depend on Ports (interfaces)
    AUTH_UC -.->|"uses port"| REPO_IMPL
    REG_UC -.->|"uses port"| REPO_IMPL
    ACCT_UC -.->|"uses port"| REPO_IMPL
    MEM_UC -.->|"uses port"| REPO_IMPL
    AUTH_UC -.->|"uses port"| AUTH_IMPL
```

### Dependency Flow

```mermaid
graph LR
    subgraph "Dependency Rule: Inner layers NEVER depend on outer layers"
        D[Domain] --> A[Application]
        A --> IA[Interface Adapters]
        IA --> I[Infrastructure]
    end
    
    style D fill:#4CAF50,color:#fff
    style A fill:#2196F3,color:#fff
    style IA fill:#FF9800,color:#fff
    style I fill:#f44336,color:#fff
```

**Capas:**

1. **Domain Layer (Entities)** — Capa más interna. Entidades de negocio puras y reglas de dominio. Sin dependencias de frameworks. Contiene: User, Tenant, Member, AccountType, Session con su lógica de validación y reglas de negocio.

2. **Application Layer (Use Cases)** — Lógica de negocio específica de la aplicación. Contiene: LoginUseCase, RegisterUseCase, AccountTypeUseCases, MemberUseCases. Cada use case define DTOs de entrada/salida y orquesta las entidades de dominio. Depende únicamente del Domain Layer y de interfaces de puertos (ports).

3. **Interface Adapters Layer (Controllers/Presenters/Gateways)** — Convierte datos entre use cases y agentes externos. Contiene: Lambda handlers (controllers), mappers de request/response, interfaces de repositorio (ports).

4. **Infrastructure Layer (Frameworks & Drivers)** — Capa más externa. Concerns externos. Contiene: Implementaciones de repositorio DynamoDB, implementación del servicio JWT, implementación bcrypt, configuración de API Gateway.

### Request Flow (Clean Architecture)

```mermaid
sequenceDiagram
    participant C as Client
    participant AG as API Gateway
    participant H as Lambda Handler
    participant CT as Controller
    participant MW as Middleware
    participant UC as Use Case
    participant P as Port (Interface)
    participant R as Repository (DynamoDB)
    participant D as Domain Entity

    C->>AG: HTTP Request
    AG->>H: Lambda Event
    H->>MW: Validate JWT / Extract Tenant
    MW->>CT: TenantContext
    CT->>CT: Map Request → Input DTO
    CT->>UC: Execute(InputDTO)
    UC->>D: Create/Validate Domain Entity
    D-->>UC: Valid Entity
    UC->>P: Repository Port method
    P->>R: DynamoDB operation
    R-->>P: Raw result
    P-->>UC: Domain Entity
    UC-->>CT: Output DTO
    CT->>CT: Map Output DTO → Response
    CT-->>H: HTTP Response
    H-->>AG: Lambda Response
    AG-->>C: HTTP Response
```

### Infrastructure Diagram (Deployment View)

```mermaid
graph TD
    Client[Client Application] --> APIGW[API Gateway]
    APIGW --> AuthLambda[Auth Lambda]
    APIGW --> RegisterLambda[Register Lambda]
    APIGW --> CRUDLambda[CRUD Lambda]
    APIGW --> MemberLambda[Member Lambda]
    
    AuthLambda --> DDB[(DynamoDB Single Table)]
    RegisterLambda --> DDB
    CRUDLambda --> DDB
    MemberLambda --> DDB
    
    AuthLambda --> JWT[JWT Token Service]
    RegisterLambda --> JWT
    
    subgraph "Tenant Isolation Layer"
        CRUDLambda --> TenantGuard[Tenant Guard Middleware]
        MemberLambda --> TenantGuard
        TenantGuard --> RoleGuard[Role Guard Middleware]
    end
    
    subgraph "DynamoDB Single Table"
        DDB --> Users[Users Partition]
        DDB --> AccountTypes[Account Types Partition]
        DDB --> Members[Members Partition]
        DDB --> Roles[Roles Partition]
        DDB --> Sessions[Sessions Partition]
    end
    
    subgraph "Actors"
        Admin[Admin - Gestión completa]
        Socio[Socio - Asociado]
        Usuario[Usuario - Genérico]
        Profesional[Profesional - Entrenador]
    end
    
    Admin --> Client
    Socio --> Client
    Usuario --> Client
    Profesional --> Client
```

## Project Structure

```
src/
├── domain/
│   ├── entities/              # Pure business entities
│   │   ├── user.ts
│   │   ├── tenant.ts
│   │   ├── member.ts
│   │   ├── accountType.ts
│   │   └── session.ts
│   ├── valueObjects/         # Immutable value types with validation
│   │   ├── email.ts
│   │   ├── password.ts
│   │   ├── tenantId.ts
│   │   ├── memberId.ts
│   │   ├── accountTypeId.ts
│   │   └── roleName.ts
│   ├── errors/                # Domain-specific errors
│   │   ├── domainError.ts
│   │   ├── validationError.ts
│   │   ├── invalidCredentialsError.ts
│   │   └── tenantNotFoundError.ts
│   └── events/                # Domain events (optional, for future use)
│       ├── memberCreated.ts
│       ├── memberDeactivated.ts
│       └── accountTypeDeleted.ts
├── application/
│   ├── useCases/             # Application-specific business logic
│   │   ├── auth/
│   │   │   ├── loginUseCase.ts
│   │   │   ├── refreshTokenUseCase.ts
│   │   │   └── logoutUseCase.ts
│   │   ├── registration/
│   │   │   ├── registerUseCase.ts
│   │   │   └── inviteUserUseCase.ts
│   │   ├── accountType/
│   │   │   ├── createAccountTypeUseCase.ts
│   │   │   ├── listAccountTypesUseCase.ts
│   │   │   ├── updateAccountTypeUseCase.ts
│   │   │   └── deleteAccountTypeUseCase.ts
│   │   └── member/
│   │       ├── createMemberUseCase.ts
│   │       ├── listMembersUseCase.ts
│   │       ├── updateMemberUseCase.ts
│   │       ├── deactivateMemberUseCase.ts
│   │       └── reactivateMemberUseCase.ts
│   ├── dtos/                  # Input/Output DTOs for each use case
│   │   ├── auth/
│   │   │   ├── loginInputDTO.ts
│   │   │   ├── loginOutputDTO.ts
│   │   │   ├── registerInputDTO.ts
│   │   │   └── registerOutputDTO.ts
│   │   ├── accountType/
│   │   │   ├── createAccountTypeInputDTO.ts
│   │   │   ├── accountTypeOutputDTO.ts
│   │   │   └── paginatedAccountTypesDTO.ts
│   │   └── member/
│   │       ├── createMemberInputDTO.ts
│   │       ├── memberOutputDTO.ts
│   │       └── paginatedMembersDTO.ts
│   ├── ports/                 # Repository & service interfaces (abstractions)
│   │   ├── iUserRepository.ts
│   │   ├── iMemberRepository.ts
│   │   ├── iAccountTypeRepository.ts
│   │   ├── iSessionRepository.ts
│   │   ├── iTenantRepository.ts
│   │   └── iAuthService.ts
│   └── services/              # Application services that orchestrate use cases
│       └── tenantContextService.ts
├── infrastructure/
│   ├── persistence/           # DynamoDB repository implementations
│   │   ├── dynamoDBUserRepository.ts
│   │   ├── dynamoDBMemberRepository.ts
│   │   ├── dynamoDBAccountTypeRepository.ts
│   │   ├── dynamoDBSessionRepository.ts
│   │   ├── dynamoDBTenantRepository.ts
│   │   └── dynamoDBClient.ts
│   ├── auth/                  # External auth implementations
│   │   ├── jwtAuthService.ts
│   │   └── bcryptPasswordHasher.ts
│   ├── config/                # Environment & client configuration
│   │   ├── environment.ts
│   │   └── dynamoDBClient.ts
│   └── mappers/               # Entity ↔ DynamoDB item mappers
│       ├── userMapper.ts
│       ├── memberMapper.ts
│       ├── accountTypeMapper.ts
│       └── sessionMapper.ts
└── interfaces/
    ├── http/
    │   ├── controllers/       # Lambda handlers (entry points)
    │   │   ├── authController.ts
    │   │   ├── registrationController.ts
    │   │   ├── accountTypeController.ts
    │   │   └── memberController.ts
    │   ├── middleware/        # Cross-cutting concerns
    │   │   ├── tenantGuardMiddleware.ts
    │   │   ├── roleGuardMiddleware.ts
    │   │   └── validationMiddleware.ts
    │   ├── routes/            # API route definitions
    │   │   └── routes.ts
    │   └── dtos/              # Request/Response schemas (HTTP-specific)
    │       ├── loginRequest.ts
    │       ├── registerRequest.ts
    │       ├── createAccountTypeRequest.ts
    │       ├── createMemberRequest.ts
    │       └── apiResponse.ts
    └── shared/                # Shared interface utilities
        ├── errorHandler.ts
        └── responseBuilder.ts
```

## Clean Architecture Rules

Las siguientes reglas son inmutables en este proyecto:

1. **Inner layers NEVER import from outer layers** — El dominio no conoce DynamoDB, JWT, ni Lambda. Los use cases no conocen HTTP ni la estructura de DynamoDB items.

2. **Domain entities have no framework annotations/decorators** — Las entidades son clases TypeScript puras con lógica de validación propia. No tienen decoradores de ORM, serialización, ni frameworks.

3. **Use Cases define their own input/output DTOs** — No se filtran estructuras HTTP (request body) ni estructuras DynamoDB (items) a los use cases. Los DTOs son contratos puros de la capa de aplicación.

4. **Dependency Inversion Principle** — Los módulos de alto nivel (use cases) no dependen de módulos de bajo nivel (DynamoDB). Ambos dependen de abstracciones (port interfaces como `IUserRepository`).

5. **El DynamoDB single table design es un concern de infraestructura** — Está completamente oculto detrás de las interfaces de repositorio. Los use cases solo conocen métodos como `find_by_email()`, `save()`, `find_by_tenant_and_account_type()`.

6. **Cada capa tiene su propio modelo de error** — Domain tiene `DomainError`, Application tiene errores de use case, Interface Adapters mapea a HTTP status codes.

7. **Testing sin infraestructura** — Los use cases se testean con mocks de los ports. El dominio se testea sin mocks (lógica pura). Solo los tests de integración necesitan DynamoDB.


## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Variables | camelCase | userId, tenantId, accountType, passwordHash |
| Functions/Methods | snake_case | find_by_email, hash_password, create_session |
| Classes/Interfaces | PascalCase | IUserRepository, LoginUseCase, Member |
| Folders/Files | camelCase | useCases/, valueObjects/, loginUseCase.ts |
## Dependency Injection

### Estrategia de Inyección

Se utiliza un patrón de composición simple (Composition Root) en cada Lambda handler para conectar las capas:

```pascal
// Composition Root - Se ejecuta una vez por Lambda cold start
PROCEDURE create_dependencies()
  OUTPUT: container of type DependencyContainer

BEGIN
  // Infrastructure Layer - concrete implementations
  dynamoClient ← create_dynamodb_client(ENV.TABLE_NAME, ENV.REGION)
  
  // Repository implementations (implement port interfaces)
  userRepository ← NEW DynamoDBUserRepository(dynamoClient)
  memberRepository ← NEW DynamoDBMemberRepository(dynamoClient)
  accountTypeRepository ← NEW DynamoDBAccountTypeRepository(dynamoClient)
  sessionRepository ← NEW DynamoDBSessionRepository(dynamoClient)
  tenantRepository ← NEW DynamoDBTenantRepository(dynamoClient)
  
  // Service implementations (implement port interfaces)
  authService ← NEW JwtAuthService(ENV.JWT_SECRET, ENV.TOKEN_EXPIRY)
  passwordHasher ← NEW BcryptPasswordHasher(ENV.SALT_ROUNDS)
  
  // Application Layer - Use Cases (receive ports via constructor injection)
  loginUseCase ← NEW LoginUseCase(userRepository, sessionRepository, authService, passwordHasher)
  registerUseCase ← NEW RegisterUseCase(userRepository, memberRepository, tenantRepository, accountTypeRepository, sessionRepository, authService, passwordHasher)
  createAccountTypeUseCase ← NEW CreateAccountTypeUseCase(accountTypeRepository, tenantRepository)
  listAccountTypesUseCase ← NEW ListAccountTypesUseCase(accountTypeRepository)
  updateAccountTypeUseCase ← NEW UpdateAccountTypeUseCase(accountTypeRepository)
  deleteAccountTypeUseCase ← NEW DeleteAccountTypeUseCase(accountTypeRepository, memberRepository)
  createMemberUseCase ← NEW CreateMemberUseCase(userRepository, memberRepository, accountTypeRepository, passwordHasher)
  listMembersUseCase ← NEW ListMembersUseCase(memberRepository)
  updateMemberUseCase ← NEW UpdateMemberUseCase(memberRepository, accountTypeRepository)
  deactivateMemberUseCase ← NEW DeactivateMemberUseCase(memberRepository, sessionRepository)
  
  // Interface Adapters Layer - Controllers (receive use cases)
  authController ← NEW AuthController(loginUseCase, refreshTokenUseCase, logoutUseCase)
  registrationController ← NEW RegistrationController(registerUseCase)
  accountTypeController ← NEW AccountTypeController(createAccountTypeUseCase, listAccountTypesUseCase, updateAccountTypeUseCase, deleteAccountTypeUseCase)
  memberController ← NEW MemberController(createMemberUseCase, listMembersUseCase, updateMemberUseCase, deactivateMemberUseCase)
  
  RETURN container
END
```

### Principios de DI

- **Constructor Injection** — Todas las dependencias se inyectan via constructor. No se usa service locator.
- **Interface Segregation** — Cada port define solo los métodos que su consumidor necesita.
- **Single Responsibility** — Cada use case tiene una única razón para cambiar.
- **Composition Root** — La composición ocurre en un único punto (Lambda handler entry), no dispersa por el código.
- **Lazy Initialization** — El container se crea una vez por cold start de Lambda y se reutiliza en invocaciones warm.

## Sequence Diagrams

### Authentication Flow (Clean Architecture)

```mermaid
sequenceDiagram
    participant C as Client
    participant AG as API Gateway
    participant H as Lambda Handler
    participant CT as AuthController
    participant UC as LoginUseCase
    participant UR as IUserRepository
    participant SR as ISessionRepository
    participant AS as IAuthService
    participant DB as DynamoDB

    C->>AG: POST /auth/login {email, password}
    AG->>H: Lambda Event
    H->>CT: handle(event)
    CT->>CT: Map request → LoginInputDTO
    CT->>UC: execute(loginInput)
    UC->>UC: Validate Email value object
    UC->>UR: find_by_email(email)
    UR->>DB: GetItem(PK=USER#email, SK=PROFILE)
    DB-->>UR: Raw item
    UR-->>UC: User entity (or null)
    UC->>AS: verify_password(password, user.passwordHash)
    AS-->>UC: boolean
    UC->>UR: get_roles_for_tenant(userId, tenantId)
    UR->>DB: Query(PK=TENANT#{tid}#USER#{uid}, SK begins_with ROLE#)
    DB-->>UR: Role items
    UR-->>UC: Role[] entities
    UC->>AS: generate_token_pair(userId, tenantId, roles)
    AS-->>UC: {accessToken, refreshToken}
    UC->>SR: create_session(userId, tenantId, refreshToken)
    SR->>DB: PutItem(session)
    DB-->>SR: Success
    UC-->>CT: LoginOutputDTO {accessToken, refreshToken}
    CT->>CT: Map DTO → HTTP Response
    CT-->>H: 200 {accessToken, refreshToken}
    H-->>AG: Lambda Response
    AG-->>C: Response
```

### Self-Registration Flow (Clean Architecture)

```mermaid
sequenceDiagram
    participant C as Client
    participant AG as API Gateway
    participant CT as RegistrationController
    participant UC as RegisterUseCase
    participant UR as IUserRepository
    participant TR as ITenantRepository
    participant ATR as IAccountTypeRepository
    participant MR as IMemberRepository
    participant AS as IAuthService
    participant DB as DynamoDB

    C->>AG: POST /auth/register {email, password, fullName, tenantId, accountType?}
    AG->>CT: handle(event)
    CT->>CT: Map request → RegisterInputDTO
    CT->>UC: execute(registerInput)
    UC->>UC: Validate value objects (Email, Password)
    UC->>UR: find_by_email(email)
    UR->>DB: GetItem(PK=USER#email)
    DB-->>UR: NULL
    UR-->>UC: null (user doesn't exist)
    UC->>TR: find_by_id(tenantId)
    TR->>DB: GetItem(PK=TENANT#{tid})
    DB-->>TR: Tenant item
    TR-->>UC: Tenant entity
    UC->>UC: Verify tenant.allowSelfRegistration
    UC->>ATR: find_by_name_in_tenant(tenantId, accountTypeName)
    ATR->>DB: Query GSI1
    DB-->>ATR: AccountType item
    ATR-->>UC: AccountType entity
    UC->>AS: hash_password(password)
    AS-->>UC: passwordHash
    UC->>UC: Create User, Member, Membership entities
    UC->>UR: register_with_membership(user, membership, member, role)
    UR->>DB: TransactWriteItems [User, Membership, Member, Role]
    DB-->>UR: Success
    UC->>AS: generate_token_pair(userId, tenantId, ["viewer"])
    AS-->>UC: {accessToken, refreshToken}
    UC-->>CT: RegisterOutputDTO {user, accessToken, refreshToken}
    CT-->>AG: 201 {user, tokens}
    AG-->>C: Response
```

### Admin-Invited Registration (Create Member)

```mermaid
sequenceDiagram
    participant A as Admin Client
    participant AG as API Gateway
    participant MW as TenantGuard Middleware
    participant CT as MemberController
    participant UC as CreateMemberUseCase
    participant UR as IUserRepository
    participant MR as IMemberRepository
    participant ATR as IAccountTypeRepository
    participant DB as DynamoDB

    A->>AG: POST /members {email, fullName, accountType, roles}
    AG->>MW: Validate JWT
    MW->>MW: Extract tenantId, verify admin role
    MW->>CT: handle(event, tenantContext)
    CT->>CT: Map request → CreateMemberInputDTO
    CT->>UC: execute(tenantId, input, createdByUserId)
    UC->>ATR: find_by_name_in_tenant(tenantId, accountType)
    ATR->>DB: Query GSI1
    DB-->>ATR: AccountType
    ATR-->>UC: AccountType entity
    UC->>UR: find_by_email(email)
    UR->>DB: GetItem
    alt User exists
        DB-->>UR: User record
        UR-->>UC: User entity
        UC->>MR: find_by_user_in_tenant(tenantId, userId)
        MR-->>UC: null (not yet member)
        UC->>MR: create_member_with_roles(membership, member, roles)
    else User doesn't exist
        DB-->>UR: NULL
        UR-->>UC: null
        UC->>UC: Create User entity with temp password
        UC->>UR: create_user_with_membership(user, membership, member, roles)
    end
    MR->>DB: TransactWriteItems
    DB-->>MR: Success
    UC-->>CT: MemberOutputDTO
    CT-->>AG: 201 {member}
    AG-->>A: Response
```

### CRUD Account Type Flow (Clean Architecture)

```mermaid
sequenceDiagram
    participant C as Client
    participant AG as API Gateway
    participant MW as Middleware
    participant CT as AccountTypeController
    participant UC as CreateAccountTypeUseCase
    participant ATR as IAccountTypeRepository
    participant DB as DynamoDB

    C->>AG: POST /account-types {name, description}
    AG->>MW: Validate JWT
    MW->>MW: Extract tenantId, verify permissions
    MW->>CT: handle(event, tenantContext)
    CT->>CT: Map request → CreateAccountTypeInputDTO
    CT->>UC: execute(tenantId, input)
    UC->>UC: Validate AccountType domain entity
    UC->>ATR: find_by_name_in_tenant(tenantId, name)
    ATR->>DB: Query GSI1
    DB-->>ATR: NULL (no duplicate)
    UC->>ATR: save(accountType)
    ATR->>DB: PutItem(mapped item)
    DB-->>ATR: Success
    ATR-->>UC: AccountType entity
    UC-->>CT: AccountTypeOutputDTO
    CT->>CT: Map DTO → HTTP Response
    CT-->>AG: 201 {accountType}
    AG-->>C: Response
```

### Member Management Flow (Clean Architecture)

```mermaid
sequenceDiagram
    participant A as Admin Client
    participant AG as API Gateway
    participant MW as Middleware
    participant CT as MemberController
    participant UC as ListMembersUseCase
    participant MR as IMemberRepository
    participant DB as DynamoDB

    A->>AG: GET /members?accountType=socio&limit=20
    AG->>MW: Validate JWT
    MW->>MW: Extract tenantId, verify permissions
    MW->>CT: handle(event, tenantContext)
    CT->>CT: Map query params → ListMembersInputDTO
    CT->>UC: execute(tenantId, filters, pagination)
    UC->>MR: find_by_tenant_and_filters(tenantId, filters, pagination)
    MR->>DB: Query(GSI1PK=TENANT#{tid}#MEMBER#ACCTYPE#{type}...)
    DB-->>MR: Raw items + LastEvaluatedKey
    MR-->>UC: PaginatedResult<Member>
    UC-->>CT: PaginatedMembersDTO
    CT->>CT: Map DTO → HTTP Response
    CT-->>AG: 200 {members, pagination}
    AG-->>A: Response
```

## Components and Interfaces

### Ports (Interfaces — Application Layer)

Los ports definen los contratos que los use cases necesitan. Son interfaces declaradas en la capa de Application que las implementaciones de Infrastructure satisfacen.

#### IUserRepository

```pascal
INTERFACE IUserRepository
  PROCEDURE find_by_email(email: Email): User OR NULL
  PROCEDURE find_by_id(userId: UUID): User OR NULL
  PROCEDURE save(user: User): User
  PROCEDURE get_roles_for_tenant(userId: UUID, tenantId: TenantId): List[Role]
  PROCEDURE register_with_membership(user: User, membership: TenantMembership, member: Member, role: UserRole): Void
  PROCEDURE create_user_with_membership(user: User, membership: TenantMembership, member: Member, roles: List[UserRole]): Void
END INTERFACE
```

#### IMemberRepository

```pascal
INTERFACE IMemberRepository
  PROCEDURE find_by_id(tenantId: TenantId, memberId: MemberId): Member OR NULL
  PROCEDURE find_by_user_in_tenant(tenantId: TenantId, userId: UUID): Member OR NULL
  PROCEDURE find_by_tenant_and_filters(tenantId: TenantId, filters: MemberFilters, pagination: PaginationParams): PaginatedResult[Member]
  PROCEDURE save(member: Member): Member
  PROCEDURE update(member: Member): Member
  PROCEDURE create_member_with_roles(membership: TenantMembership, member: Member, roles: List[UserRole]): Void
  PROCEDURE count_active_by_account_type(tenantId: TenantId, accountTypeName: String): Number
END INTERFACE
```

#### IAccountTypeRepository

```pascal
INTERFACE IAccountTypeRepository
  PROCEDURE find_by_id(tenantId: TenantId, accountTypeId: AccountTypeId): AccountType OR NULL
  PROCEDURE find_by_name_in_tenant(tenantId: TenantId, name: String): AccountType OR NULL
  PROCEDURE find_all_by_tenant(tenantId: TenantId, pagination: PaginationParams): PaginatedResult[AccountType]
  PROCEDURE save(accountType: AccountType): AccountType
  PROCEDURE update(accountType: AccountType): AccountType
END INTERFACE
```

#### ISessionRepository

```pascal
INTERFACE ISessionRepository
  PROCEDURE create_session(userId: UUID, tenantId: TenantId, refreshTokenHash: String, ttl: Number): Session
  PROCEDURE find_by_token_hash(tokenHash: String): Session OR NULL
  PROCEDURE delete_session(sessionPK: String, sessionSK: String): Void
  PROCEDURE delete_all_for_user_in_tenant(userId: UUID, tenantId: TenantId): Void
  PROCEDURE rotate_token(oldSession: Session, newSession: Session): Void
END INTERFACE
```

#### ITenantRepository

```pascal
INTERFACE ITenantRepository
  PROCEDURE find_by_id(tenantId: TenantId): Tenant OR NULL
END INTERFACE
```

#### IAuthService

```pascal
INTERFACE IAuthService
  PROCEDURE hash_password(password: Password): String
  PROCEDURE verify_password(plainPassword: String, hashedPassword: String): Boolean
  PROCEDURE generate_token_pair(userId: UUID, tenantId: TenantId, email: String, roles: List[String]): TokenPair
  PROCEDURE verify_access_token(token: String): TokenPayload OR NULL
  PROCEDURE generate_secure_random(length: Number): String
  PROCEDURE hash_token(token: String): String
END INTERFACE
```

### Use Cases (Application Layer)

Cada use case encapsula una operación de negocio. Recibe DTOs de entrada, orquesta entidades de dominio, y usa ports para persistencia/servicios.

#### LoginUseCase

```pascal
STRUCTURE LoginUseCase
  DEPENDENCIES: IUserRepository, ISessionRepository, IAuthService

  PROCEDURE execute(input: LoginInputDTO): LoginOutputDTO OR Error
    // Orchestrates: validate credentials, check user status, get roles, generate tokens, store session
END STRUCTURE
```

#### RegisterUseCase

```pascal
STRUCTURE RegisterUseCase
  DEPENDENCIES: IUserRepository, IMemberRepository, ITenantRepository, IAccountTypeRepository, ISessionRepository, IAuthService

  PROCEDURE execute(input: RegisterInputDTO): RegisterOutputDTO OR Error
    // Orchestrates: validate uniqueness, verify tenant, determine accountType, create all entities atomically, generate tokens
END STRUCTURE
```

#### CreateAccountTypeUseCase

```pascal
STRUCTURE CreateAccountTypeUseCase
  DEPENDENCIES: IAccountTypeRepository, ITenantRepository

  PROCEDURE execute(tenantId: TenantId, input: CreateAccountTypeInputDTO): AccountTypeOutputDTO OR Error
    // Orchestrates: verify tenant, check name uniqueness, create and persist AccountType entity
END STRUCTURE
```

#### ListAccountTypesUseCase

```pascal
STRUCTURE ListAccountTypesUseCase
  DEPENDENCIES: IAccountTypeRepository

  PROCEDURE execute(tenantId: TenantId, pagination: PaginationParams): PaginatedAccountTypesDTO
    // Orchestrates: query repository with tenant isolation, return paginated results
END STRUCTURE
```

#### UpdateAccountTypeUseCase

```pascal
STRUCTURE UpdateAccountTypeUseCase
  DEPENDENCIES: IAccountTypeRepository

  PROCEDURE execute(tenantId: TenantId, accountTypeId: AccountTypeId, input: UpdateAccountTypeInputDTO): AccountTypeOutputDTO OR Error
    // Orchestrates: find existing, validate name uniqueness if changed, update entity
END STRUCTURE
```

#### DeleteAccountTypeUseCase

```pascal
STRUCTURE DeleteAccountTypeUseCase
  DEPENDENCIES: IAccountTypeRepository, IMemberRepository

  PROCEDURE execute(tenantId: TenantId, accountTypeId: AccountTypeId): Void OR Error
    // Orchestrates: check for active members using this type, soft-delete if safe
END STRUCTURE
```

#### CreateMemberUseCase

```pascal
STRUCTURE CreateMemberUseCase
  DEPENDENCIES: IUserRepository, IMemberRepository, IAccountTypeRepository, IAuthService

  PROCEDURE execute(tenantId: TenantId, input: CreateMemberInputDTO, createdByUserId: UUID): MemberOutputDTO OR Error
    // Orchestrates: validate accountType, check user existence, create member atomically
END STRUCTURE
```

#### ListMembersUseCase

```pascal
STRUCTURE ListMembersUseCase
  DEPENDENCIES: IMemberRepository

  PROCEDURE execute(tenantId: TenantId, filters: MemberFilters, pagination: PaginationParams): PaginatedMembersDTO
    // Orchestrates: query repository with filters and pagination
END STRUCTURE
```

#### UpdateMemberUseCase

```pascal
STRUCTURE UpdateMemberUseCase
  DEPENDENCIES: IMemberRepository, IAccountTypeRepository

  PROCEDURE execute(tenantId: TenantId, memberId: MemberId, input: UpdateMemberInputDTO): MemberOutputDTO OR Error
    // Orchestrates: find member, validate new accountType if changed, update
END STRUCTURE
```

#### DeactivateMemberUseCase

```pascal
STRUCTURE DeactivateMemberUseCase
  DEPENDENCIES: IMemberRepository, ISessionRepository

  PROCEDURE execute(tenantId: TenantId, memberId: MemberId): Void OR Error
    // Orchestrates: verify member exists, soft-delete, invalidate sessions
END STRUCTURE
```

### Adapters (Infrastructure Layer — Implementations)

Las implementaciones concretas satisfacen los ports definidos en Application.

#### DynamoDBUserRepository implements IUserRepository

```pascal
STRUCTURE DynamoDBUserRepository IMPLEMENTS IUserRepository
  DEPENDENCIES: DynamoDBClient, UserMapper

  PROCEDURE find_by_email(email: Email): User OR NULL
    // Maps: Email → PK=USER#{email}, SK=PROFILE
    // Uses: GetItem
    // Returns: UserMapper.toDomain(item) OR NULL
  END PROCEDURE

  PROCEDURE get_roles_for_tenant(userId: UUID, tenantId: TenantId): List[Role]
    // Maps: → PK=TENANT#{tenantId}#USER#{userId}, SK begins_with ROLE#
    // Uses: Query
    // Returns: items mapped to Role entities
  END PROCEDURE

  PROCEDURE register_with_membership(user, membership, member, role): Void
    // Maps: all entities to DynamoDB items via Mappers
    // Uses: TransactWriteItems
    // Encapsulates: single table key patterns
  END PROCEDURE
END STRUCTURE
```

#### DynamoDBMemberRepository implements IMemberRepository

```pascal
STRUCTURE DynamoDBMemberRepository IMPLEMENTS IMemberRepository
  DEPENDENCIES: DynamoDBClient, MemberMapper

  PROCEDURE find_by_tenant_and_filters(tenantId, filters, pagination): PaginatedResult[Member]
    // Strategy: uses GSI1 if accountType filter present, otherwise base table query
    // Maps: filter → GSI1PK=TENANT#{tid}#MEMBER#ACCTYPE#{type} OR PK=TENANT#{tid}#MEMBER
    // Encapsulates: pagination cursor encoding/decoding
  END PROCEDURE

  PROCEDURE count_active_by_account_type(tenantId, accountTypeName): Number
    // Maps: → GSI1 query with status filter
    // Used by: DeleteAccountTypeUseCase to check references
  END PROCEDURE
END STRUCTURE
```

#### DynamoDBAccountTypeRepository implements IAccountTypeRepository

```pascal
STRUCTURE DynamoDBAccountTypeRepository IMPLEMENTS IAccountTypeRepository
  DEPENDENCIES: DynamoDBClient, AccountTypeMapper

  PROCEDURE find_by_name_in_tenant(tenantId, name): AccountType OR NULL
    // Maps: → GSI1PK=TENANT#{tid}#ACCTYPE, GSI1SK=NAME#{lowercase(name)}
    // Encapsulates: case-insensitive name lookup via GSI
  END PROCEDURE

  PROCEDURE save(accountType): AccountType
    // Maps: AccountType entity → DynamoDB item with PK/SK/GSI keys
    // Uses: PutItem with ConditionExpression
  END PROCEDURE
END STRUCTURE
```

#### JwtAuthService implements IAuthService

```pascal
STRUCTURE JwtAuthService IMPLEMENTS IAuthService
  DEPENDENCIES: jwtSecret: String, tokenExpiry: Number, saltRounds: Number

  PROCEDURE generate_token_pair(userId, tenantId, email, roles): TokenPair
    // Uses: jsonwebtoken library to sign JWT
    // Returns: {accessToken, refreshToken}
  END PROCEDURE

  PROCEDURE verify_access_token(token): TokenPayload OR NULL
    // Uses: jsonwebtoken library to verify and decode
    // Returns: decoded payload or null if invalid/expired
  END PROCEDURE

  PROCEDURE hash_password(password): String
    // Uses: bcrypt with configured salt rounds
  END PROCEDURE

  PROCEDURE verify_password(plain, hashed): Boolean
    // Uses: bcrypt.compare
  END PROCEDURE
END STRUCTURE
```

### Controllers (Interface Adapters Layer)

Los controllers mapean requests HTTP a DTOs de use case y responses de use case a HTTP responses.

#### AuthController

```pascal
STRUCTURE AuthController
  DEPENDENCIES: LoginUseCase, RefreshTokenUseCase, LogoutUseCase

  PROCEDURE handle_login(event: APIGatewayEvent): APIResponse
    // 1. Extract email, password from event.body
    // 2. Validate request schema
    // 3. Map to LoginInputDTO
    // 4. Call loginUseCase.execute(dto)
    // 5. Map LoginOutputDTO → 200 response
    // 6. On error: map to appropriate HTTP status
  END PROCEDURE

  PROCEDURE handle_refresh(event: APIGatewayEvent): APIResponse
    // Similar pattern: extract → validate → map → execute → respond
  END PROCEDURE
END STRUCTURE
```

#### MemberController

```pascal
STRUCTURE MemberController
  DEPENDENCIES: CreateMemberUseCase, ListMembersUseCase, UpdateMemberUseCase, DeactivateMemberUseCase

  PROCEDURE handle_create(event: APIGatewayEvent, context: TenantContext): APIResponse
    // 1. Extract body from event
    // 2. Validate request schema
    // 3. Map to CreateMemberInputDTO
    // 4. Call createMemberUseCase.execute(context.tenantId, dto, context.userId)
    // 5. Map MemberOutputDTO → 201 response
  END PROCEDURE

  PROCEDURE handle_list(event: APIGatewayEvent, context: TenantContext): APIResponse
    // 1. Extract query params (accountType, status, limit, cursor)
    // 2. Map to filters + pagination
    // 3. Call listMembersUseCase.execute(context.tenantId, filters, pagination)
    // 4. Map PaginatedMembersDTO → 200 response
  END PROCEDURE
END STRUCTURE
```

### Middleware (Interface Adapters Layer)

#### TenantGuard Middleware

```pascal
INTERFACE TenantGuard
  PROCEDURE validateTenantAccess(token: TokenPayload, resourceTenantId: String): Boolean
  PROCEDURE extractTenantContext(token: TokenPayload): TenantContext
END INTERFACE

INTERFACE RoleGuard
  PROCEDURE hasPermission(userRoles: List[Role], requiredPermission: String): Boolean
  PROCEDURE validateRole(tenantId: String, userId: String, action: String): Boolean
END INTERFACE
```

**Responsibilities**:
- Extraer tenantId del token JWT
- Verificar que el usuario pertenece al tenant solicitado
- Validar permisos de rol para la acción solicitada
- Rechazar acceso cross-tenant

## Data Models

### Table Structure

**Table Name**: `SportBE_Main`

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | String | Partition Key |
| SK | String | Sort Key |
| GSI1PK | String | Global Secondary Index 1 PK |
| GSI1SK | String | Global Secondary Index 1 SK |
| GSI2PK | String | Global Secondary Index 2 PK |
| GSI2SK | String | Global Secondary Index 2 SK |
| data | Map | Entity-specific attributes |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |
| ttl | Number | TTL for sessions (epoch) |

### Entity Key Patterns

```pascal
STRUCTURE KeyPatterns
  // Users
  User_PK: "USER#{email}"
  User_SK: "PROFILE"
  
  // User-Tenant membership
  UserTenant_PK: "TENANT#{tenantId}#USER#{userId}"
  UserTenant_SK: "MEMBERSHIP"
  
  // User Roles within Tenant
  UserRole_PK: "TENANT#{tenantId}#USER#{userId}"
  UserRole_SK: "ROLE#{roleName}"
  
  // Members (personas dentro de un tenant con accountType)
  Member_PK: "TENANT#{tenantId}#MEMBER"
  Member_SK: "MEMBER#{memberId}"
  
  // Account Types
  AccountType_PK: "TENANT#{tenantId}#ACCTYPE"
  AccountType_SK: "ACCTYPE#{accountTypeId}"
  
  // Tenants
  Tenant_PK: "TENANT#{tenantId}"
  Tenant_SK: "METADATA"
  
  // Sessions (for refresh tokens)
  Session_PK: "SESSION#{userId}"
  Session_SK: "TOKEN#{tokenId}"
  
  // GSI1 - Query users by tenant
  GSI1_UsersByTenant_PK: "TENANT#{tenantId}"
  GSI1_UsersByTenant_SK: "USER#{userId}"
  
  // GSI1 - Query account types by name
  GSI1_AccTypeByName_PK: "TENANT#{tenantId}#ACCTYPE"
  GSI1_AccTypeByName_SK: "NAME#{name}"
  
  // GSI1 - Query members by accountType within tenant
  GSI1_MembersByAccType_PK: "TENANT#{tenantId}#MEMBER#ACCTYPE#{accountType}"
  GSI1_MembersByAccType_SK: "MEMBER#{memberId}"
  
  // GSI2 - Query member by userId within tenant
  GSI2_MemberByUser_PK: "TENANT#{tenantId}#MEMBER#USER"
  GSI2_MemberByUser_SK: "USER#{userId}"
END STRUCTURE
```

### Data Entities

```pascal
STRUCTURE User
  pk: String          // USER#{email}
  sk: String          // PROFILE
  userId: UUID
  email: String
  passwordHash: String
  fullName: String
  status: ENUM(active, inactive, suspended, pending_confirmation)
  createdAt: String
  updatedAt: String
END STRUCTURE

STRUCTURE Tenant
  pk: String          // TENANT#{tenantId}
  sk: String          // METADATA
  tenantId: UUID
  name: String
  plan: ENUM(free, basic, premium)
  status: ENUM(active, suspended)
  allowSelfRegistration: Boolean
  defaultAccountType: String   // accountType assigned on self-registration
  createdAt: String
END STRUCTURE

STRUCTURE UserTenantMembership
  pk: String          // TENANT#{tenantId}#USER#{userId}
  sk: String          // MEMBERSHIP
  gsi1pk: String      // TENANT#{tenantId}
  gsi1sk: String      // USER#{userId}
  userId: UUID
  tenantId: UUID
  joinedAt: String
END STRUCTURE

STRUCTURE UserRole
  pk: String          // TENANT#{tenantId}#USER#{userId}
  sk: String          // ROLE#{roleName}
  roleName: String
  permissions: List[String]
  assignedAt: String
END STRUCTURE

STRUCTURE Member
  pk: String          // TENANT#{tenantId}#MEMBER
  sk: String          // MEMBER#{memberId}
  gsi1pk: String      // TENANT#{tenantId}#MEMBER#ACCTYPE#{accountType}
  gsi1sk: String      // MEMBER#{memberId}
  gsi2pk: String      // TENANT#{tenantId}#MEMBER#USER
  gsi2sk: String      // USER#{userId}
  memberId: UUID
  tenantId: UUID
  userId: UUID
  accountType: String          // "socio", "usuario", "profesional" (references AccountType)
  accountTypeId: UUID          // FK to AccountType entity
  fullName: String
  email: String
  status: ENUM(active, inactive, pending)
  registrationType: ENUM(self, invited)
  invitedBy: UUID OR NULL      // userId of admin who invited, NULL if self-registered
  metadata: Map                // Additional member-specific data
  createdAt: String
  updatedAt: String
END STRUCTURE

STRUCTURE AccountType
  pk: String          // TENANT#{tenantId}#ACCTYPE
  sk: String          // ACCTYPE#{accountTypeId}
  gsi1pk: String      // TENANT#{tenantId}#ACCTYPE
  gsi1sk: String      // NAME#{name}
  accountTypeId: UUID
  tenantId: UUID
  name: String             // "socio", "usuario", "profesional", custom types
  description: String
  config: Map
  status: ENUM(active, inactive)
  createdAt: String
  updatedAt: String
END STRUCTURE

STRUCTURE Session
  pk: String          // SESSION#{userId}
  sk: String          // TOKEN#{tokenId}
  refreshToken: String
  tenantId: String
  expiresAt: Number   // TTL epoch
  createdAt: String
  ttl: Number         // DynamoDB TTL
END STRUCTURE
```

### Access Patterns

| Access Pattern | Operation | Key Condition |
|---------------|-----------|---------------|
| Get user by email | GetItem | PK=USER#{email}, SK=PROFILE |
| Get user roles in tenant | Query | PK=TENANT#{tid}#USER#{uid}, SK begins_with ROLE# |
| List users in tenant | Query GSI1 | GSI1PK=TENANT#{tid}, GSI1SK begins_with USER# |
| Get account type by ID | GetItem | PK=TENANT#{tid}#ACCTYPE, SK=ACCTYPE#{id} |
| List account types by tenant | Query | PK=TENANT#{tid}#ACCTYPE, SK begins_with ACCTYPE# |
| Find account type by name | Query GSI1 | GSI1PK=TENANT#{tid}#ACCTYPE, GSI1SK=NAME#{name} |
| Get member by ID | GetItem | PK=TENANT#{tid}#MEMBER, SK=MEMBER#{mid} |
| List members by tenant | Query | PK=TENANT#{tid}#MEMBER, SK begins_with MEMBER# |
| List members by accountType | Query GSI1 | GSI1PK=TENANT#{tid}#MEMBER#ACCTYPE#{type}, GSI1SK begins_with MEMBER# |
| Get member by userId in tenant | Query GSI2 | GSI2PK=TENANT#{tid}#MEMBER#USER, GSI2SK=USER#{uid} |
| Get user sessions | Query | PK=SESSION#{uid}, SK begins_with TOKEN# |
| Get tenant metadata | GetItem | PK=TENANT#{tid}, SK=METADATA |
| Get user membership | GetItem | PK=TENANT#{tid}#USER#{uid}, SK=MEMBERSHIP |

### Validation Rules

- `email`: formato válido, único globalmente
- `name` (AccountType): no vacío, máx 100 caracteres, único dentro del tenant
- `tenantId`: debe existir en la tabla
- `roleName`: debe ser uno de los roles válidos del sistema
- `passwordHash`: generado con bcrypt, salt rounds >= 10
- `accountType` (Member): debe referenciar un AccountType activo dentro del mismo tenant
- `memberId`: único dentro del tenant
- `fullName` (Member): no vacío, máx 200 caracteres

## Multi-Role Model

### Role Definitions

```pascal
STRUCTURE RoleDefinition
  CONSTANT ROLES
    admin: List["create", "read", "update", "delete", "manage_users", "manage_roles", "manage_members", "invite_members"]
    manager: List["create", "read", "update", "delete", "manage_members"]
    viewer: List["read"]
  END CONSTANT
END STRUCTURE
```

### Permission Matrix

| Action | admin | manager | viewer |
|--------|-------|---------|--------|
| Create Account Type | Yes | Yes | No |
| Read Account Type | Yes | Yes | Yes |
| Update Account Type | Yes | Yes | No |
| Delete Account Type | Yes | No | No |
| Create Member (invite) | Yes | Yes | No |
| Read Members | Yes | Yes | Yes |
| Update Member | Yes | Yes | No |
| Deactivate Member | Yes | No | No |
| Manage Users | Yes | No | No |
| Manage Roles | Yes | No | No |

## Algorithmic Pseudocode

### Authentication Algorithm (LoginUseCase.execute)

```pascal
ALGORITHM LoginUseCase.execute(input: LoginInputDTO)
INPUT: input of type LoginInputDTO {email: String, password: String}
OUTPUT: result of type LoginOutputDTO OR Error

BEGIN
  // --- Domain Validation ---
  emailVO ← Email.create(input.email)
  IF emailVO IS Error THEN
    RETURN Error("Invalid email format")
  END IF
  
  ASSERT input.password IS NOT empty
  
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Retrieve user via repository port
  user ← this.userRepository.find_by_email(emailVO)
  
  IF user IS NULL THEN
    RETURN Error("Invalid credentials")
  END IF
  
  IF user.status != "active" THEN
    RETURN Error("Account is not active")
  END IF
  
  // Step 2: Verify password via auth service port
  isValid ← this.authService.verify_password(input.password, user.passwordHash)
  
  IF NOT isValid THEN
    RETURN Error("Invalid credentials")
  END IF
  
  // Step 3: Get roles via repository port
  roles ← this.userRepository.get_roles_for_tenant(user.userId, user.primaryTenantId)
  
  IF roles IS EMPTY THEN
    RETURN Error("No tenant assigned")
  END IF
  
  roleNames ← EXTRACT roleName FROM EACH role IN roles
  
  // Step 4: Generate tokens via auth service port
  tokenPair ← this.authService.generate_token_pair(user.userId, user.primaryTenantId, user.email, roleNames)
  
  // Step 5: Store session via repository port
  refreshTokenHash ← this.authService.hash_token(tokenPair.refreshToken)
  this.sessionRepository.create_session(user.userId, user.primaryTenantId, refreshTokenHash, NOW() + 86400 * 7)
  
  // --- Return Output DTO ---
  RETURN LoginOutputDTO {
    accessToken: tokenPair.accessToken,
    refreshToken: tokenPair.refreshToken,
    userId: user.userId,
    tenantId: user.primaryTenantId,
    roles: roleNames
  }
END
```

**Preconditions:**
- `input.email` is a non-empty string with valid email format
- `input.password` is a non-empty string
- All injected ports (IUserRepository, ISessionRepository, IAuthService) are available

**Postconditions:**
- On success: returns valid JWT access token and refresh token
- On success: session stored via ISessionRepository
- On failure: returns error without leaking user existence info
- No mutations to user record on authentication failure

### Registration Algorithm (RegisterUseCase.execute)

```pascal
ALGORITHM RegisterUseCase.execute(input: RegisterInputDTO)
INPUT: input of type RegisterInputDTO {email, password, fullName, tenantId, accountType?}
OUTPUT: result of type RegisterOutputDTO OR Error

BEGIN
  // --- Domain Validation (Value Objects) ---
  emailVO ← Email.create(input.email)
  IF emailVO IS Error THEN RETURN Error("Invalid email format") END IF
  
  passwordVO ← Password.create(input.password)
  IF passwordVO IS Error THEN RETURN Error("Password must be >= 8 characters") END IF
  
  tenantIdVO ← TenantId.create(input.tenantId)
  IF tenantIdVO IS Error THEN RETURN Error("Invalid tenant ID") END IF
  
  ASSERT input.fullName IS NOT empty
  
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Check if user already exists
  existingUser ← this.userRepository.find_by_email(emailVO)
  
  IF existingUser IS NOT NULL THEN
    RETURN Error("Email already registered")
  END IF
  
  // Step 2: Verify tenant exists and allows self-registration
  tenant ← this.tenantRepository.find_by_id(tenantIdVO)
  
  IF tenant IS NULL THEN
    RETURN Error("Tenant not found")
  END IF
  
  IF tenant.status != "active" THEN
    RETURN Error("Tenant is not active")
  END IF
  
  IF NOT tenant.allowSelfRegistration THEN
    RETURN Error("Self-registration is not allowed for this institution")
  END IF
  
  // Step 3: Determine and validate accountType
  accountTypeName ← input.accountType OR tenant.defaultAccountType OR "usuario"
  
  accountTypeRecord ← this.accountTypeRepository.find_by_name_in_tenant(tenantIdVO, LOWERCASE(accountTypeName))
  
  IF accountTypeRecord IS NULL THEN
    RETURN Error("Invalid account type")
  END IF
  
  // Step 4: Hash password via auth service port
  passwordHash ← this.authService.hash_password(passwordVO)
  
  // Step 5: Create domain entities
  userId ← generateUUID()
  memberId ← generateUUID()
  now ← ISO8601(NOW())
  
  user ← User.create(userId, emailVO, passwordHash, input.fullName, "active", now)
  membership ← TenantMembership.create(tenantIdVO, userId, now)
  member ← Member.create(memberId, tenantIdVO, userId, accountTypeName, accountTypeRecord.accountTypeId, input.fullName, emailVO, "active", "self", NULL, now)
  role ← UserRole.create(tenantIdVO, userId, "viewer", ["read"], now)
  
  // Step 6: Atomic persistence via repository port
  this.userRepository.register_with_membership(user, membership, member, role)
  
  // Step 7: Generate tokens via auth service port
  tokenPair ← this.authService.generate_token_pair(userId, tenantIdVO, emailVO, ["viewer"])
  
  // Store session
  refreshTokenHash ← this.authService.hash_token(tokenPair.refreshToken)
  this.sessionRepository.create_session(userId, tenantIdVO, refreshTokenHash, NOW() + 86400 * 7)
  
  // --- Return Output DTO ---
  RETURN RegisterOutputDTO {
    userId: userId,
    memberId: memberId,
    accessToken: tokenPair.accessToken,
    refreshToken: tokenPair.refreshToken
  }
END
```

**Preconditions:**
- `email` is unique globally (not already registered)
- `tenantId` references an active tenant that allows self-registration
- `accountType` (if provided) must reference an active AccountType in the tenant
- `password` meets minimum security requirements (>= 8 chars)

**Postconditions:**
- User, TenantMembership, Member, and Role all created atomically (all or nothing)
- User immediately receives tokens for authentication
- Member is assigned the specified or default accountType
- Default role "viewer" is assigned
- If any part of the transaction fails, no records are created

### Create Member Algorithm (CreateMemberUseCase.execute)

```pascal
ALGORITHM CreateMemberUseCase.execute(tenantId: TenantId, input: CreateMemberInputDTO, createdByUserId: UUID)
INPUT: tenantId of type TenantId, input of type CreateMemberInputDTO {email, fullName, accountType, roles}, createdByUserId of type UUID
OUTPUT: result of type MemberOutputDTO OR Error

BEGIN
  // --- Domain Validation ---
  emailVO ← Email.create(input.email)
  IF emailVO IS Error THEN RETURN Error("Invalid email format") END IF
  
  ASSERT input.fullName IS NOT empty
  ASSERT input.accountType IS NOT empty
  ASSERT input.roles IS NOT empty
  
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Verify accountType exists in tenant
  accountTypeRecord ← this.accountTypeRepository.find_by_name_in_tenant(tenantId, LOWERCASE(input.accountType))
  
  IF accountTypeRecord IS NULL THEN
    RETURN Error("Account type '" + input.accountType + "' does not exist in this tenant")
  END IF
  
  IF accountTypeRecord.status != "active" THEN
    RETURN Error("Account type is not active")
  END IF
  
  // Step 2: Check if user already exists
  existingUser ← this.userRepository.find_by_email(emailVO)
  
  memberId ← generateUUID()
  now ← ISO8601(NOW())
  
  IF existingUser IS NULL THEN
    // New user - create User entity with temp password
    userId ← generateUUID()
    tempPassword ← this.authService.generate_secure_random(16)
    passwordHash ← this.authService.hash_password(Password.createUnsafe(tempPassword))
    
    user ← User.create(userId, emailVO, passwordHash, input.fullName, "pending_confirmation", now)
    membership ← TenantMembership.create(tenantId, userId, now)
    member ← Member.create(memberId, tenantId, userId, input.accountType, accountTypeRecord.accountTypeId, input.fullName, emailVO, "active", "invited", createdByUserId, now)
    roles ← MAP input.roles TO UserRole.create(tenantId, userId, roleName, ROLES[roleName], now)
    
    // Validate all roles are valid
    FOR EACH roleName IN input.roles DO
      IF roleName NOT IN VALID_ROLES THEN
        RETURN Error("Invalid role: " + roleName)
      END IF
    END FOR
    
    this.userRepository.create_user_with_membership(user, membership, member, roles)
  ELSE
    userId ← existingUser.userId
    
    // Check if already a member of this tenant
    existingMember ← this.memberRepository.find_by_user_in_tenant(tenantId, userId)
    
    IF existingMember IS NOT NULL THEN
      RETURN Error("User is already a member of this tenant")
    END IF
    
    membership ← TenantMembership.create(tenantId, userId, now)
    member ← Member.create(memberId, tenantId, userId, input.accountType, accountTypeRecord.accountTypeId, input.fullName, emailVO, "active", "invited", createdByUserId, now)
    roles ← MAP input.roles TO UserRole.create(tenantId, userId, roleName, ROLES[roleName], now)
    
    FOR EACH roleName IN input.roles DO
      IF roleName NOT IN VALID_ROLES THEN
        RETURN Error("Invalid role: " + roleName)
      END IF
    END FOR
    
    this.memberRepository.create_member_with_roles(membership, member, roles)
  END IF
  
  // --- Return Output DTO ---
  RETURN MemberOutputDTO {
    memberId: memberId,
    tenantId: tenantId,
    userId: userId,
    accountType: input.accountType,
    fullName: input.fullName,
    email: input.email,
    status: "active",
    registrationType: "invited",
    invitedBy: createdByUserId,
    createdAt: now
  }
END
```

**Preconditions:**
- `createdByUserId` has "manage_members" or "invite_members" permission in the tenant
- `input.accountType` references an active AccountType in the tenant
- `input.roles` contains only valid role names

**Postconditions:**
- If user is new: User record created with status "pending_confirmation"
- If user exists: only Membership, Member, and Roles are created
- All records created atomically
- Member is linked to both the User and the AccountType
- User cannot be added as member to same tenant twice

### List Members Algorithm (ListMembersUseCase.execute)

```pascal
ALGORITHM ListMembersUseCase.execute(tenantId: TenantId, filters: MemberFilters, pagination: PaginationParams)
INPUT: tenantId of type TenantId, filters of type MemberFilters {accountType?, status?}, pagination of type PaginationParams {limit: Number, lastKey: String OR NULL}
OUTPUT: result of type PaginatedMembersDTO

BEGIN
  // --- Domain Validation ---
  ASSERT pagination.limit > 0 AND pagination.limit <= 100
  
  // --- Use Case Orchestration (via Port) ---
  paginatedResult ← this.memberRepository.find_by_tenant_and_filters(tenantId, filters, pagination)
  
  // --- Map to Output DTO ---
  RETURN PaginatedMembersDTO {
    items: MAP paginatedResult.items TO MemberOutputDTO,
    nextKey: paginatedResult.nextKey,
    count: paginatedResult.count
  }
END
```

**Preconditions:**
- `tenantId` corresponds to an existing tenant
- `limit` is between 1 and 100
- If `accountType` filter is specified, it must be a valid accountType name

**Postconditions:**
- Returns only members belonging to the specified tenant
- If accountType filter applied, returns only members with that accountType
- Pagination cursor provided if more items exist
- Never returns members from other tenants

**Loop Invariants:** N/A (DynamoDB handles iteration internally via repository)

### Update Member Algorithm (UpdateMemberUseCase.execute)

```pascal
ALGORITHM UpdateMemberUseCase.execute(tenantId: TenantId, memberId: MemberId, input: UpdateMemberInputDTO)
INPUT: tenantId of type TenantId, memberId of type MemberId, input of type UpdateMemberInputDTO {accountType?, status?, fullName?, metadata?}
OUTPUT: result of type MemberOutputDTO OR Error

BEGIN
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Get existing member
  existing ← this.memberRepository.find_by_id(tenantId, memberId)
  
  IF existing IS NULL THEN
    RETURN Error("Member not found")
  END IF
  
  // Step 2: If accountType is changing, validate new accountType
  IF input.accountType IS NOT NULL AND LOWERCASE(input.accountType) != LOWERCASE(existing.accountType) THEN
    accountTypeRecord ← this.accountTypeRepository.find_by_name_in_tenant(tenantId, LOWERCASE(input.accountType))
    
    IF accountTypeRecord IS NULL THEN
      RETURN Error("Account type '" + input.accountType + "' does not exist in this tenant")
    END IF
    
    IF accountTypeRecord.status != "active" THEN
      RETURN Error("Account type is not active")
    END IF
    
    existing.accountType = input.accountType
    existing.accountTypeId = accountTypeRecord.accountTypeId
  END IF
  
  // Step 3: Apply updates to domain entity
  IF input.status IS NOT NULL THEN existing.status = input.status END IF
  IF input.fullName IS NOT NULL THEN existing.fullName = input.fullName END IF
  IF input.metadata IS NOT NULL THEN existing.metadata = input.metadata END IF
  existing.updatedAt = ISO8601(NOW())
  
  // Step 4: Persist via repository port
  updated ← this.memberRepository.update(existing)
  
  // --- Return Output DTO ---
  RETURN MemberOutputDTO(updated)
END
```

**Preconditions:**
- Member exists in the specified tenant
- If accountType is being changed, new accountType must be active in the tenant

**Postconditions:**
- Only specified fields are updated
- GSI1 updated if accountType changed (handled by repository implementation)
- `updatedAt` timestamp refreshed
- Original `createdAt` and `registrationType` preserved

### Deactivate Member Algorithm (DeactivateMemberUseCase.execute)

```pascal
ALGORITHM DeactivateMemberUseCase.execute(tenantId: TenantId, memberId: MemberId)
INPUT: tenantId of type TenantId, memberId of type MemberId
OUTPUT: Void OR Error

BEGIN
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Verify member exists
  existing ← this.memberRepository.find_by_id(tenantId, memberId)
  
  IF existing IS NULL THEN
    RETURN Error("Member not found")
  END IF
  
  IF existing.status = "inactive" THEN
    RETURN Error("Member is already inactive")
  END IF
  
  // Step 2: Soft delete - update domain entity
  existing.status = "inactive"
  existing.updatedAt = ISO8601(NOW())
  
  this.memberRepository.update(existing)
  
  // Step 3: Invalidate sessions for this tenant via session port
  this.sessionRepository.delete_all_for_user_in_tenant(existing.userId, tenantId)
  
  RETURN Void
END
```

**Preconditions:**
- Member exists in the specified tenant
- User has "manage_members" permission (admin role) or specific deactivation permission

**Postconditions:**
- Member marked as inactive (soft delete)
- Active sessions for this tenant are invalidated
- Member record preserved for audit trail
- User record in USER# partition is NOT affected (can still access other tenants)

### CRUD - Create Account Type (CreateAccountTypeUseCase.execute)

```pascal
ALGORITHM CreateAccountTypeUseCase.execute(tenantId: TenantId, input: CreateAccountTypeInputDTO)
INPUT: tenantId of type TenantId, input of type CreateAccountTypeInputDTO {name, description?, config?}
OUTPUT: result of type AccountTypeOutputDTO OR Error

BEGIN
  // --- Domain Validation ---
  ASSERT input.name IS NOT empty
  ASSERT LENGTH(input.name) <= 100
  
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Verify tenant exists
  tenant ← this.tenantRepository.find_by_id(tenantId)
  
  IF tenant IS NULL THEN
    RETURN Error("Tenant not found")
  END IF
  
  // Step 2: Check for duplicate name within tenant
  existing ← this.accountTypeRepository.find_by_name_in_tenant(tenantId, LOWERCASE(input.name))
  
  IF existing IS NOT NULL THEN
    RETURN Error("Account type name already exists in this tenant")
  END IF
  
  // Step 3: Create domain entity
  accountTypeId ← generateUUID()
  now ← ISO8601(NOW())
  
  accountType ← AccountType.create(
    accountTypeId, tenantId, input.name, 
    input.description OR "", input.config OR {}, 
    "active", now
  )
  
  // Step 4: Persist via repository port
  saved ← this.accountTypeRepository.save(accountType)
  
  // --- Return Output DTO ---
  RETURN AccountTypeOutputDTO(saved)
END
```

**Preconditions:**
- `tenantId` corresponds to an existing tenant
- `input.name` is non-empty and max 100 characters

**Postconditions:**
- New account type stored via repository
- Name is unique within the tenant (case-insensitive)
- Returns created account type with generated ID and timestamps

### CRUD - List Account Types (ListAccountTypesUseCase.execute)

```pascal
ALGORITHM ListAccountTypesUseCase.execute(tenantId: TenantId, pagination: PaginationParams)
INPUT: tenantId of type TenantId, pagination of type PaginationParams {limit: Number, lastKey: String OR NULL}
OUTPUT: result of type PaginatedAccountTypesDTO

BEGIN
  ASSERT pagination.limit > 0 AND pagination.limit <= 100
  
  // --- Use Case Orchestration (via Port) ---
  paginatedResult ← this.accountTypeRepository.find_all_by_tenant(tenantId, pagination)
  
  // --- Return Output DTO ---
  RETURN PaginatedAccountTypesDTO {
    items: MAP paginatedResult.items TO AccountTypeOutputDTO,
    nextKey: paginatedResult.nextKey,
    count: paginatedResult.count
  }
END
```

**Preconditions:**
- `tenantId` corresponds to an existing tenant
- `limit` is between 1 and 100

**Postconditions:**
- Returns only account types belonging to the specified tenant
- Pagination cursor provided if more items exist
- Items ordered by sort key (accountTypeId)

**Loop Invariants:** N/A (DynamoDB handles iteration internally via repository)

### CRUD - Update Account Type (UpdateAccountTypeUseCase.execute)

```pascal
ALGORITHM UpdateAccountTypeUseCase.execute(tenantId: TenantId, accountTypeId: AccountTypeId, input: UpdateAccountTypeInputDTO)
INPUT: tenantId of type TenantId, accountTypeId of type AccountTypeId, input of type UpdateAccountTypeInputDTO {name?, description?, config?, status?}
OUTPUT: result of type AccountTypeOutputDTO OR Error

BEGIN
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Verify item exists and belongs to tenant
  existing ← this.accountTypeRepository.find_by_id(tenantId, accountTypeId)
  
  IF existing IS NULL THEN
    RETURN Error("Account type not found")
  END IF
  
  // Step 2: If name changed, check uniqueness
  IF input.name IS NOT NULL AND LOWERCASE(input.name) != LOWERCASE(existing.name) THEN
    duplicate ← this.accountTypeRepository.find_by_name_in_tenant(tenantId, LOWERCASE(input.name))
    
    IF duplicate IS NOT NULL THEN
      RETURN Error("Account type name already exists in this tenant")
    END IF
    
    existing.name = input.name
  END IF
  
  // Step 3: Apply updates to domain entity
  IF input.description IS NOT NULL THEN existing.description = input.description END IF
  IF input.config IS NOT NULL THEN existing.config = input.config END IF
  IF input.status IS NOT NULL THEN existing.status = input.status END IF
  existing.updatedAt = ISO8601(NOW())
  
  // Step 4: Persist via repository port
  updated ← this.accountTypeRepository.update(existing)
  
  // --- Return Output DTO ---
  RETURN AccountTypeOutputDTO(updated)
END
```

**Preconditions:**
- Account type exists in the specified tenant
- If name is being changed, new name is unique within tenant

**Postconditions:**
- Only specified fields are updated
- `updatedAt` timestamp refreshed
- GSI1 updated if name changed (handled by repository)
- Original `createdAt` preserved

### CRUD - Delete Account Type (DeleteAccountTypeUseCase.execute)

```pascal
ALGORITHM DeleteAccountTypeUseCase.execute(tenantId: TenantId, accountTypeId: AccountTypeId)
INPUT: tenantId of type TenantId, accountTypeId of type AccountTypeId
OUTPUT: Void OR Error

BEGIN
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Verify item exists
  existing ← this.accountTypeRepository.find_by_id(tenantId, accountTypeId)
  
  IF existing IS NULL THEN
    RETURN Error("Account type not found")
  END IF
  
  // Step 2: Check if any active members are using this account type
  activeCount ← this.memberRepository.count_active_by_account_type(tenantId, LOWERCASE(existing.name))
  
  IF activeCount > 0 THEN
    RETURN Error("Cannot delete account type: active members are using it")
  END IF
  
  // Step 3: Soft delete - update domain entity status
  existing.status = "inactive"
  existing.updatedAt = ISO8601(NOW())
  
  this.accountTypeRepository.update(existing)
  
  RETURN Void
END
```

**Preconditions:**
- Account type exists in the specified tenant
- User has "delete" permission (admin role)

**Postconditions:**
- Account type marked as inactive (soft delete) only if no active members use it
- Record preserved for audit trail
- `updatedAt` timestamp refreshed
- Existing members with this accountType are NOT affected

### Tenant Guard Middleware (Interface Adapters Layer)

```pascal
ALGORITHM TenantGuardMiddleware.validate(event: APIGatewayEvent, requiredPermission: String)
INPUT: event of type APIGatewayEvent, requiredPermission of type String
OUTPUT: TenantContext OR Error

BEGIN
  // Step 1: Extract and validate JWT via IAuthService
  authHeader ← event.headers["Authorization"]
  
  IF authHeader IS NULL OR NOT starts_with(authHeader, "Bearer ") THEN
    RETURN Error(401, "Missing or invalid authorization header")
  END IF
  
  token ← SUBSTRING(authHeader, 7)
  
  payload ← this.authService.verify_access_token(token)
  
  IF payload IS NULL OR payload.exp < NOW() THEN
    RETURN Error(401, "Token expired or invalid")
  END IF
  
  // Step 2: Validate tenant access
  tenantId ← payload.tenantId
  
  IF tenantId IS NULL THEN
    RETURN Error(403, "No tenant context in token")
  END IF
  
  // Step 3: Validate role permissions
  userRoles ← payload.roles
  hasPermission ← FALSE
  
  FOR EACH role IN userRoles DO
    permissions ← ROLES[role]
    IF requiredPermission IN permissions THEN
      hasPermission ← TRUE
      EXIT FOR
    END IF
  END FOR
  
  IF NOT hasPermission THEN
    RETURN Error(403, "Insufficient permissions")
  END IF
  
  // Step 4: Return tenant context
  RETURN TenantContext {
    userId: payload.userId,
    tenantId: tenantId,
    roles: userRoles,
    email: payload.email
  }
END
```

**Preconditions:**
- Request contains Authorization header with Bearer token
- IAuthService is available for token verification

**Postconditions:**
- Returns authenticated tenant context if valid
- Rejects with 401 for auth issues
- Rejects with 403 for permission issues
- Never allows cross-tenant access

**Loop Invariants:**
- For role permission check: all previously checked roles did not contain the required permission

### Refresh Token Algorithm (RefreshTokenUseCase.execute)

```pascal
ALGORITHM RefreshTokenUseCase.execute(refreshToken: String)
INPUT: refreshToken of type String
OUTPUT: result of type TokenPair OR Error

BEGIN
  ASSERT refreshToken IS NOT empty
  
  // --- Use Case Orchestration (via Ports) ---
  
  // Step 1: Find session by token hash
  hashedToken ← this.authService.hash_token(refreshToken)
  session ← this.sessionRepository.find_by_token_hash(hashedToken)
  
  IF session IS NULL THEN
    RETURN Error(401, "Invalid refresh token")
  END IF
  
  IF session.ttl < NOW() THEN
    RETURN Error(401, "Refresh token expired")
  END IF
  
  // Step 2: Get user and roles via ports
  userId ← session.userId
  roles ← this.userRepository.get_roles_for_tenant(userId, session.tenantId)
  
  // Step 3: Generate new token pair via auth service port
  roleNames ← EXTRACT roleName FROM roles
  newTokenPair ← this.authService.generate_token_pair(userId, session.tenantId, session.email, roleNames)
  
  // Step 4: Rotate refresh token atomically via session port
  newRefreshTokenHash ← this.authService.hash_token(newTokenPair.refreshToken)
  newSession ← Session.create(userId, session.tenantId, newRefreshTokenHash, NOW() + 86400 * 7)
  
  this.sessionRepository.rotate_token(session, newSession)
  
  RETURN TokenPair(newTokenPair.accessToken, newTokenPair.refreshToken)
END
```

**Preconditions:**
- `refreshToken` is a valid, non-expired token stored via ISessionRepository

**Postconditions:**
- Old refresh token invalidated
- New token pair generated
- Session TTL renewed
- Atomic operation (old deleted, new stored in transaction)

## Key Functions with Formal Specifications

### Function: generate_keys (Infrastructure — Mapper concern)

```pascal
PROCEDURE generate_keys(entityType, identifiers)
  INPUT: entityType of type String, identifiers of type Map
  OUTPUT: keys of type {PK: String, SK: String}
```

**Preconditions:**
- `entityType` is one of: "USER", "TENANT", "ACCTYPE", "SESSION", "MEMBERSHIP", "ROLE", "MEMBER"
- `identifiers` contains all required fields for the entity type

**Postconditions:**
- Returns correctly formatted PK and SK
- Keys conform to single table design pattern

**Note:** This function lives in the Infrastructure layer (mappers). Use cases never call it directly.

### Function: validateInput (Domain — Value Object concern)

```pascal
PROCEDURE validate_account_type_input(data)
  INPUT: data of type AccountTypeInput
  OUTPUT: validationResult of type {valid: Boolean, errors: List[String]}
```

**Preconditions:**
- `data` is defined (not null)

**Postconditions:**
- Returns `valid = true` if all fields pass validation
- Returns list of specific error messages for each invalid field
- No mutations to input data

### Function: validate_registration_input (Domain — Value Object concern)

```pascal
PROCEDURE validate_registration_input(data)
  INPUT: data of type RegistrationInput {email, password, fullName, tenantId, accountType?}
  OUTPUT: validationResult of type {valid: Boolean, errors: List[String]}
```

**Preconditions:**
- `data` is defined (not null)

**Postconditions:**
- Returns `valid = true` if:
  - email is valid format
  - password is >= 8 characters
  - fullName is non-empty and <= 200 characters
  - tenantId is non-empty
- Returns list of specific error messages for each invalid field
- No mutations to input data

### Function: validate_member_input (Domain — Value Object concern)

```pascal
PROCEDURE validate_member_input(data)
  INPUT: data of type CreateMemberInput {email, fullName, accountType, roles}
  OUTPUT: validationResult of type {valid: Boolean, errors: List[String]}
```

**Preconditions:**
- `data` is defined (not null)

**Postconditions:**
- Returns `valid = true` if:
  - email is valid format
  - fullName is non-empty and <= 200 characters
  - accountType is non-empty
  - roles is non-empty array of valid role names
- Returns list of specific error messages for each invalid field
- No mutations to input data

## Example Usage

```pascal
// Example 1: Self-Registration (Controller → UseCase → Ports)
SEQUENCE
  // --- Controller Layer ---
  event ← APIGateway.receive()
  registrationData ← MapRequestToDTO(event.body)
  // registrationData = { email: "juan@example.com", password: "SecurePass123!", fullName: "Juan Pérez", tenantId: "club-deportivo-norte-uuid", accountType: "socio" }
  
  // --- Use Case Layer ---
  result ← registerUseCase.execute(registrationData)
  
  // --- Controller Response ---
  IF result IS Success THEN
    RETURN response(201, {
      userId: result.userId,
      accessToken: result.accessToken,
      refreshToken: result.refreshToken
    })
  ELSE
    RETURN response(400, { error: result.errorMessage })
  END IF
END SEQUENCE

// Example 2: Admin invites a new professional (Controller → Middleware → UseCase)
SEQUENCE
  // --- Middleware Layer ---
  context ← tenantGuardMiddleware.validate(event, "manage_members")
  
  IF context IS Error THEN
    RETURN response(context.statusCode, context.message)
  END IF
  
  // --- Controller Layer ---
  memberInput ← MapRequestToDTO(event.body)
  // memberInput = { email: "profesora.garcia@example.com", fullName: "María García", accountType: "profesional", roles: ["manager"], metadata: { specialty: "natación" } }
  
  // --- Use Case Layer ---
  result ← createMemberUseCase.execute(context.tenantId, memberInput, context.userId)
  
  // --- Controller Response ---
  IF result IS Error THEN
    RETURN response(400, { error: result.message })
  ELSE
    RETURN response(201, result)
  END IF
END SEQUENCE

// Example 3: Login (Controller → UseCase → Ports)
SEQUENCE
  // --- Controller Layer ---
  loginInput ← MapRequestToDTO(event.body)
  // loginInput = { email: "admin@tenant1.com", password: "securePass123" }
  
  // --- Use Case Layer ---
  result ← loginUseCase.execute(loginInput)
  
  // --- Controller Response ---
  IF result IS Success THEN
    RETURN response(200, {
      accessToken: result.accessToken,
      refreshToken: result.refreshToken
    })
  ELSE
    RETURN response(401, { error: "Invalid credentials" })
  END IF
END SEQUENCE

// Example 4: List members by accountType (Controller → UseCase → Port)
SEQUENCE
  // --- Middleware ---
  context ← tenantGuardMiddleware.validate(event, "read")
  IF context IS Error THEN RETURN response(context.statusCode, context.message) END IF
  
  // --- Controller ---
  filters ← { accountType: event.queryParams.accountType, status: "active" }
  pagination ← { limit: 20, lastKey: event.queryParams.cursor OR NULL }
  
  // --- Use Case ---
  result ← listMembersUseCase.execute(context.tenantId, filters, pagination)
  
  RETURN response(200, result)
END SEQUENCE

// Example 5: Create Account Type (Controller → UseCase → Port)
SEQUENCE
  context ← tenantGuardMiddleware.validate(event, "create")
  IF context IS Error THEN RETURN response(context.statusCode, context.message) END IF
  
  // --- Controller maps HTTP request to use case DTO ---
  input ← { name: "Premium", description: "Cuenta premium con beneficios extras", config: { maxUsers: 50 } }
  
  // --- Use Case handles business logic ---
  result ← createAccountTypeUseCase.execute(context.tenantId, input)
  
  IF result IS Error THEN
    RETURN response(400, { error: result.message })
  ELSE
    RETURN response(201, result)
  END IF
END SEQUENCE

// Example 6: List with Pagination (Controller → UseCase → Port)
SEQUENCE
  context ← tenantGuardMiddleware.validate(event, "read")
  pagination ← { limit: 20, lastKey: event.queryParams.cursor OR NULL }
  
  result ← listAccountTypesUseCase.execute(context.tenantId, pagination)
  RETURN response(200, result)
END SEQUENCE

// Example 7: Update member accountType (Controller → UseCase → Ports)
SEQUENCE
  context ← tenantGuardMiddleware.validate(event, "manage_members")
  IF context IS Error THEN RETURN response(context.statusCode, context.message) END IF
  
  updateInput ← { accountType: "profesional" }
  memberIdVO ← MemberId.create(event.pathParams.memberId)
  
  result ← updateMemberUseCase.execute(context.tenantId, memberIdVO, updateInput)
  
  IF result IS Error THEN
    RETURN response(400, { error: result.message })
  ELSE
    RETURN response(200, result)
  END IF
END SEQUENCE

// Example 8: Deactivate member (Controller → UseCase → Ports)
SEQUENCE
  context ← tenantGuardMiddleware.validate(event, "manage_members")
  IF context IS Error THEN RETURN response(context.statusCode, context.message) END IF
  
  memberIdVO ← MemberId.create(event.pathParams.memberId)
  result ← deactivateMemberUseCase.execute(context.tenantId, memberIdVO)
  
  IF result IS Error THEN
    RETURN response(404, { error: result.message })
  ELSE
    RETURN response(204, NULL)
  END IF
END SEQUENCE
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Tenant Data Isolation

*For any* two distinct tenants T1 and T2, the set of account types visible to T1 and the set visible to T2 are completely disjoint, and the set of members visible to T1 and the set visible to T2 are completely disjoint. Every authenticated data query uses the tenantId extracted from the JWT token payload as a mandatory filter.

```pascal
FOR ALL request R, tenant T1, tenant T2
  WHERE T1 != T2
  ASSERT accountTypesVisibleTo(R, T1) INTERSECTION accountTypesVisibleTo(R, T2) = EMPTY
  AND membersVisibleTo(R, T1) INTERSECTION membersVisibleTo(R, T2) = EMPTY
  AND sessionsVisibleTo(R, T1) INTERSECTION sessionsVisibleTo(R, T2) = EMPTY
  AND IF R.jwt.tenantId != resource.tenantId THEN response = 403
```

**Validates: Requirements 9.1, 9.2, 9.3, 9.4**

### Property 2: Credential Error Opacity

*For any* login attempt with invalid credentials (whether due to non-existent email, wrong password, or lack of active membership in the specified tenant), the System returns the same generic "Invalid credentials" error, making it impossible to distinguish between failure modes.

```pascal
FOR ALL loginAttempt L WHERE L.credentials are invalid
  ASSERT error_message(L) = "Invalid credentials"
  AND response_does_not_reveal_user_existence(L)
  AND response_does_not_reveal_membership_status(L)
```

**Validates: Requirements 1.2, 1.3, 1.5**

### Property 3: Role Permission Enforcement

*For any* user U, action A, and tenant T, the user can perform that action only if they hold a role in that tenant whose permission set includes the required permission for the action. When a user has multiple roles, the effective permissions are the union of all assigned role permissions.

```pascal
FOR ALL user U, action A, tenant T
  ASSERT IF U performs A on T THEN
    EXISTS role R IN U.roles(T) WHERE A IN R.permissions
  AND effective_permissions(U, T) = UNION(R.permissions FOR ALL R IN U.roles(T))
```

**Validates: Requirements 10.1, 10.2, 10.3, 10.5, 10.6**

### Property 4: AccountType Name Uniqueness per Tenant

*For any* single tenant, no two account types (regardless of status) can share the same name when compared case-insensitively.

```pascal
FOR ALL accountType AT1, accountType AT2 IN same tenant T
  ASSERT IF AT1.id != AT2.id THEN LOWERCASE(AT1.name) != LOWERCASE(AT2.name)
```

**Validates: Requirements 5.2, 5.5**

### Property 5: Soft Delete Preservation

*For any* account type deletion or member deactivation, the operation sets status to "inactive" but the record remains fully retrievable from the database for audit purposes, with updatedAt refreshed.

```pascal
FOR ALL accountType AT
  ASSERT IF delete(AT) succeeds THEN
    AT.status = "inactive" AND AT record still exists in database
    AND AT.updatedAt is refreshed

FOR ALL member M
  ASSERT IF deactivate(M) succeeds THEN
    M.status = "inactive" AND M record still exists in database with all historical fields
    AND M.updatedAt is refreshed
```

**Validates: Requirements 5.6, 8.1, 8.4**

### Property 6: Refresh Token Single-Use Rotation

*For any* valid refresh token, after a successful refresh operation, the old token is atomically invalidated and a new token pair is issued with a renewed TTL of 7 days; the old token can never be used again. If the user's status is not "active" at refresh time, the refresh is rejected and the session is invalidated.

```pascal
FOR ALL refreshToken RT
  ASSERT IF refresh(RT) succeeds THEN
    RT is no longer valid (single-use)
    AND new RT' is generated with TTL = 7 days
    AND old session is deleted AND new session is created atomically
  AND IF user(RT).status != "active" THEN
    refresh(RT) fails with 401
    AND session is invalidated
```

**Validates: Requirements 2.1, 2.4, 2.5, 12.4**

### Property 7: Member-AccountType Referential Integrity

*For any* member creation or update operation, the specified accountType must reference an existing, active AccountType entity within the same tenant. Operations with non-existent or inactive account types are rejected.

```pascal
FOR ALL member operation OP (create or update) with accountType AT in tenant T
  ASSERT IF OP succeeds THEN
    EXISTS accountType record ATR IN T
    WHERE LOWERCASE(ATR.name) = LOWERCASE(AT)
    AND ATR.status = "active"
  AND IF ATR does not exist THEN OP fails with "Account type does not exist in this tenant"
  AND IF ATR.status != "active" THEN OP fails with "Account type is not active"
```

**Validates: Requirements 4.4, 4.5, 7.1, 7.4, 7.5**

### Property 8: Registration Atomicity

*For any* registration attempt (self or invited), either all required records (User, TenantMembership, Member, Role) are created in a single atomic transaction, or none are created. On self-registration success, a session is also created and a Token_Pair returned.

```pascal
FOR ALL registration attempt REG
  ASSERT IF register(REG) succeeds THEN
    EXISTS User U AND TenantMembership TM AND Member M AND Role R
    WHERE U.userId = TM.userId = M.userId
    AND TM.tenantId = M.tenantId
    AND M.accountType IS valid
    AND (IF REG is self-registration THEN EXISTS Session S for U)
  AND IF register(REG) fails THEN
    NO new User, TenantMembership, Member, Role, or Session records are created
```

**Validates: Requirements 3.1, 3.7, 4.1, 4.2, 12.1, 12.2, 12.3**

### Property 9: AccountType Deletion Protection

*For any* account type, deletion (soft-delete) succeeds only when zero active members reference that account type.

```pascal
FOR ALL accountType AT
  ASSERT IF delete(AT) succeeds THEN
    NOT EXISTS member M WHERE M.accountTypeId = AT.accountTypeId AND M.status = "active"
```

**Validates: Requirements 5.7**

### Property 10: Password Storage Security

*For any* password stored in the system (whether user-provided or system-generated temporary), the stored value is a bcrypt hash with at least 10 salt rounds and never equals the plain-text input. Temporary passwords are at least 16 characters and cryptographically random.

```pascal
FOR ALL password P stored in database
  ASSERT P != plaintext_input
  AND P is a valid bcrypt hash with salt_rounds >= 10
  AND IF P is a temporary password THEN length(plaintext) >= 16

FOR ALL responses and logs
  ASSERT no plaintext password is present
```

**Validates: Requirements 13.1, 13.2, 13.4, 4.7**

### Property 11: Session Invalidation on Deactivation

*For any* member deactivation, all active sessions for that user within the deactivated tenant are immediately invalidated, preventing further access.

```pascal
FOR ALL member M, tenant T
  ASSERT IF deactivate(M) in T succeeds THEN
    NOT EXISTS session S WHERE S.userId = M.userId AND S.tenantId = T
```

**Validates: Requirements 8.1, 14.3**

### Property 12: Token Contains Correct Roles

*For any* successful authentication or token refresh, the generated access token payload includes all and only the current roles assigned to the user in that tenant.

```pascal
FOR ALL successful login or refresh L for user U in tenant T
  ASSERT token(L).roles = U.current_roles(T)
```

**Validates: Requirements 1.7, 2.6**

### Property 13: Self-Registration Gate

*For any* self-registration attempt, the operation succeeds only when the target tenant exists, is active, and has allowSelfRegistration set to true.

```pascal
FOR ALL self-registration SR targeting tenant T
  ASSERT IF SR succeeds THEN
    T EXISTS AND T.status = "active" AND T.allowSelfRegistration = true
```

**Validates: Requirements 3.3, 3.4, 3.5**

### Property 14: Default AccountType Assignment

*For any* self-registration where the user does not specify an accountType, the system assigns the tenant's defaultAccountType; if that is null or references an inactive account type, "usuario" is used as fallback.

```pascal
FOR ALL self-registration SR WHERE SR.accountType IS NULL
  ASSERT IF SR.tenant.defaultAccountType IS NOT NULL AND defaultAccountType IS active THEN
    member(SR).accountType = SR.tenant.defaultAccountType
  ELSE
    member(SR).accountType = "usuario"
```

**Validates: Requirements 3.6**

### Property 15: Email Uniqueness Enforcement

*For any* registration attempt with an email that already exists in the system, the operation is rejected with a conflict error and no new records are created.

```pascal
FOR ALL registration SR WHERE email(SR) EXISTS in database
  ASSERT SR fails with "Email already registered" error
  AND no new User record is created
  AND no new TenantMembership, Member, or Role records are created
```

**Validates: Requirements 3.2**

### Property 16: Member Update Preserves Immutable Fields

*For any* member update operation, the createdAt timestamp, registrationType, and invitedBy fields are never modified, while updatedAt is always refreshed.

```pascal
FOR ALL member update U on member M
  ASSERT after(U).createdAt = before(U).createdAt
  AND after(U).registrationType = before(U).registrationType
  AND after(U).invitedBy = before(U).invitedBy
  AND after(U).updatedAt > before(U).updatedAt
```

**Validates: Requirements 7.3**

### Property 17: Value Object Validation Gate

*For any* input that fails Value Object validation (invalid email format, email > 254 chars, password < 8 or > 72 chars, empty/non-UUID tenantId, empty/oversized fullName), the system returns a validation error before any business logic or persistence operation executes.

```pascal
FOR ALL input I that fails Value Object creation
  ASSERT no repository method is called
  AND error is returned with specific validation message
  AND no state changes occur in the data store
```

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 13.5**

### Property 18: Pagination Bounded Response

*For any* list query (members or account types), the number of items returned never exceeds 100 per page, a pagination cursor is provided when more items exist, and using the cursor returns results continuing from where the previous page ended.

```pascal
FOR ALL list query Q with limit L
  ASSERT COUNT(results(Q)) <= MIN(L, 100)
  AND IF total_items > returned_count THEN nextKey IS NOT NULL
  AND IF Q uses cursor C from previous query Q' THEN
    results(Q) starts after last item of results(Q')
    AND results(Q) INTERSECTION results(Q') = EMPTY
```

**Validates: Requirements 5.4, 6.1, 6.4, 6.5**

### Property 19: Filter Correctness

*For any* member list query with an accountType filter (case-insensitive) or status filter (exact match), every returned member matches the specified filter value.

```pascal
FOR ALL member list query Q with filter F
  ASSERT FOR ALL member M in results(Q):
    IF F.accountType IS set THEN LOWERCASE(M.accountType) = LOWERCASE(F.accountType)
    AND IF F.status IS set THEN M.status = F.status
```

**Validates: Requirements 6.2, 6.3**

### Property 20: User Record Preservation on Member Deactivation

*For any* member deactivation in a tenant, the associated User record remains unmodified, allowing the user to continue accessing other tenants where they have active memberships.

```pascal
FOR ALL member deactivation D of member M in tenant T
  ASSERT user(M).status is unchanged after D
  AND user(M).passwordHash is unchanged after D
  AND FOR ALL other tenants T' WHERE T' != T AND user(M) has membership in T':
    membership(user(M), T') is unchanged
```

**Validates: Requirements 8.5**

### Property 21: Logout Session Deletion

*For any* explicit logout operation with a valid refresh token, the session associated with that token is deleted and the token becomes unusable for future refresh attempts.

```pascal
FOR ALL logout operation LO with refreshToken RT
  ASSERT IF logout(RT) succeeds THEN
    NOT EXISTS session S WHERE S.refreshTokenHash = hash(RT)
    AND subsequent refresh(RT) fails with "Invalid refresh token"
```

**Validates: Requirements 14.5**

## Error Handling

### Error Scenario 1: Invalid Credentials

**Condition**: Email no existe o password incorrecto
**Response**: 401 Unauthorized con mensaje genérico "Invalid credentials"
**Recovery**: Cliente puede reintentar. Después de 5 intentos fallidos, cuenta se bloquea temporalmente.
**Layer**: Use Case returns domain error → Controller maps to HTTP 401

### Error Scenario 2: Token Expired

**Condition**: JWT access token ha expirado
**Response**: 401 Unauthorized con mensaje "Token expired"
**Recovery**: Cliente usa refresh token para obtener nuevo access token
**Layer**: Middleware (Interface Adapters) detects via IAuthService port

### Error Scenario 3: Insufficient Permissions

**Condition**: Usuario no tiene el rol necesario para la operación
**Response**: 403 Forbidden con mensaje "Insufficient permissions"
**Recovery**: Usuario debe solicitar el rol apropiado a un admin
**Layer**: Middleware (Interface Adapters) validates role permissions

### Error Scenario 4: Duplicate Account Type Name

**Condition**: Nombre de tipo de cuenta ya existe en el tenant
**Response**: 409 Conflict con mensaje descriptivo
**Recovery**: Cliente elige un nombre diferente
**Layer**: Use Case checks via IAccountTypeRepository port

### Error Scenario 5: DynamoDB Throttling

**Condition**: Capacidad de lectura/escritura excedida
**Response**: 429 Too Many Requests con header Retry-After
**Recovery**: Retry con exponential backoff (base 100ms, max 5 retries)
**Layer**: Infrastructure (Repository) throws → Controller maps to HTTP 429

### Error Scenario 6: Tenant Not Found

**Condition**: TenantId en token no corresponde a tenant activo
**Response**: 403 Forbidden
**Recovery**: Re-autenticar o contactar soporte
**Layer**: Use Case validates via ITenantRepository port

### Error Scenario 7: Email Already Registered

**Condition**: Usuario intenta registrarse con email que ya existe
**Response**: 409 Conflict con mensaje "Email already registered"
**Recovery**: Cliente puede intentar login o usar otro email
**Layer**: Use Case checks via IUserRepository port

### Error Scenario 8: Self-Registration Not Allowed

**Condition**: Tenant tiene `allowSelfRegistration = false` y usuario intenta auto-registro
**Response**: 403 Forbidden con mensaje "Self-registration is not allowed for this institution"
**Recovery**: Usuario debe solicitar invitación de un admin
**Layer**: Use Case validates tenant configuration via ITenantRepository port

### Error Scenario 9: Invalid AccountType for Member

**Condition**: Se intenta crear/actualizar un miembro con un accountType que no existe o está inactivo en el tenant
**Response**: 400 Bad Request con mensaje "Account type does not exist in this tenant"
**Recovery**: Cliente selecciona un accountType válido
**Layer**: Use Case validates via IAccountTypeRepository port

### Error Scenario 10: Member Already Exists in Tenant

**Condition**: Admin intenta invitar un usuario que ya es miembro del tenant
**Response**: 409 Conflict con mensaje "User is already a member of this tenant"
**Recovery**: Admin puede buscar el miembro existente y actualizar su accountType/roles
**Layer**: Use Case checks via IMemberRepository port

### Error Scenario 11: Cannot Delete AccountType with Active Members

**Condition**: Se intenta eliminar un accountType que tiene miembros activos asignados
**Response**: 409 Conflict con mensaje "Cannot delete account type: active members are using it"
**Recovery**: Primero desactivar o reasignar los miembros, luego eliminar el accountType
**Layer**: Use Case checks via IMemberRepository.count_active_by_account_type port

### Error Mapping Strategy (Interface Adapters Layer)

```pascal
PROCEDURE map_error_to_http_response(error: Error): APIResponse
BEGIN
  MATCH error.type WITH
    DomainValidationError → 400 Bad Request
    InvalidCredentialsError → 401 Unauthorized
    TokenExpiredError → 401 Unauthorized
    ForbiddenError → 403 Forbidden
    NotFoundError → 404 Not Found
    ConflictError → 409 Conflict
    ThrottlingError → 429 Too Many Requests
    InfrastructureError → 500 Internal Server Error
  END MATCH
END
```

## Testing Strategy

### Unit Testing Approach (Domain & Application Layers)

- Validar lógica de Value Objects (Email, Password, TenantId) — **Domain layer, no mocks**
- Verificar reglas de negocio en entities — **Domain layer, no mocks**
- Testear Use Cases con mocks de los ports — **Application layer, mock IUserRepository, IMemberRepository, etc.**
- Validar input sanitization y validation rules — **Domain layer**
- Testear role permission checking logic — **Domain/Application layer**
- Validar lógica de registro (self y invited) — **Application layer con mocks**
- Testear validación de accountType en operaciones de miembros — **Application layer con mocks**
- Verificar atomicidad de transacciones (mock repository ports) — **Application layer**

**Nota Clean Architecture:** Los unit tests de Use Cases SOLO mockean los ports (interfaces). Nunca se mockea DynamoDB directamente en esta capa.

### Property-Based Testing Approach

**Property Test Library**: fast-check (JavaScript/TypeScript)

Properties a verificar:
- Tenant isolation: operaciones nunca filtran datos cross-tenant
- Key generation: siempre produce keys válidas y únicas (Infrastructure layer test)
- Role hierarchy: admin siempre tiene permisos de manager y viewer
- Pagination: todos los items se recuperan eventualmente iterando páginas
- Member-AccountType consistency: todo miembro activo tiene accountType válido
- Registration atomicity: registro nunca deja registros parciales
- AccountType deletion: no se puede eliminar si hay miembros activos usándolo
- Value Object invariants: Email, Password, TenantId siempre válidos después de creación
- Dependency rule: ningún import cruza la frontera de capas incorrectamente

### Integration Testing Approach (Infrastructure Layer)

- Test end-to-end auth flow (login → use token → refresh → logout)
- Test end-to-end registration flow (register → auto-login → access resources)
- Test admin invitation flow (invite → user confirms → login)
- Test repository implementations con DynamoDB Local — **Infrastructure layer**
- Test mappers (Entity ↔ DynamoDB item) — **Infrastructure layer**
- Test tenant isolation con múltiples tenants simultáneos
- Test member management (create, list, filter, update, deactivate)
- Test rate limiting y throttling behavior

**Nota Clean Architecture:** Los integration tests validan que las implementaciones concretas (DynamoDBUserRepository, JwtAuthService) satisfacen correctamente los contratos definidos por los ports.

## Performance Considerations

- **DynamoDB On-Demand**: Usar modo on-demand para evitar provisioning manual, auto-escala
- **DAX Cache**: Considerar DynamoDB Accelerator para queries frecuentes de lectura (list account types, list members)
- **Token Size**: Mantener JWT payload mínimo para reducir overhead en cada request
- **Connection Reuse**: Reusar conexiones DynamoDB entre invocaciones Lambda (keep-alive). El DynamoDB client se instancia una vez en el Composition Root.
- **Pagination**: Límite máximo de 100 items por página para evitar timeouts
- **GSI Design**: GSIs diseñados para evitar hot partitions distribuyendo por tenantId
- **Transaction Size**: Registros usan TransactWriteItems (máx 25 items) - registro crea 4 items, bien dentro del límite
- **Member Queries**: GSI1 optimizado para filtrado por accountType sin necesidad de FilterExpression costoso
- **Clean Architecture Overhead**: La indirección de capas tiene costo mínimo en runtime (resolución de interfaces en cold start), pero mejora significativamente testabilidad y mantenibilidad

## Security Considerations

- **Password Storage**: bcrypt con salt rounds >= 10 (implementado en IAuthService, inyectado vía port)
- **JWT Secrets**: Almacenados en AWS Secrets Manager, rotados periódicamente (Infrastructure concern)
- **Token Expiry**: Access token 1h, refresh token 7d con rotación
- **CORS**: Configurar origins permitidos por tenant
- **Input Validation**: Sanitizar todos los inputs via Value Objects en Domain layer antes de llegar a Use Cases
- **Rate Limiting**: Máximo 5 login attempts por minuto por IP/email. Máximo 10 registros por hora por IP.
- **Tenant Isolation**: Validación a nivel de middleware (Interface Adapters), imposible bypass desde Lambda. Repository implementations siempre requieren tenantId.
- **HTTPS Only**: API Gateway configurado solo con HTTPS
- **Audit Log**: Registrar todas las operaciones de escritura con userId y timestamp
- **Invitation Security**: Passwords temporales hasheados, usuario debe cambiar en primer login
- **Self-Registration Control**: Flag `allowSelfRegistration` por tenant permite control granular
- **No Framework Leakage**: Domain entities no exponen detalles de infraestructura (DynamoDB keys, JWT structure)

## Dependencies

- **AWS DynamoDB**: Base de datos NoSQL principal (single table) — Infrastructure layer
- **AWS Lambda**: Runtime para funciones serverless — Infrastructure layer
- **AWS API Gateway**: HTTP API con authorizers — Infrastructure layer
- **AWS Secrets Manager**: Almacenamiento de JWT secrets — Infrastructure layer
- **bcrypt**: Hash de passwords — Infrastructure layer (implements IAuthService)
- **jsonwebtoken (o equivalente)**: Generación/verificación de JWT — Infrastructure layer (implements IAuthService)
- **uuid**: Generación de identificadores únicos — Domain/Infrastructure layer
- **DynamoDB Local**: Para desarrollo y testing local — Infrastructure layer (testing)
- **fast-check**: Property-based testing library — Testing
- **jest/vitest**: Unit & integration test runner — Testing
