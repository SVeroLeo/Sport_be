# Requirements Document

## Introduction

Este feature agrega autenticación federada mediante proveedores sociales (Google y Facebook) al sistema de Account Management. El sistema ya dispone de un flujo de registro/login con email+password respaldado por Cognito User Pool, un trigger Post Confirmation que crea los registros DynamoDB (User, TenantMembership, Member, Role) atómicamente, y una arquitectura multi-tenant donde cada usuario puede pertenecer a uno o más tenants.

El login social introduce la particularidad de que el usuario no conoce su `tenant_id` al iniciar el flujo OAuth. Por eso la asociación de tenant ocurre en un paso posterior: se asigna un tenant por defecto o se solicita al usuario que elija. Además, un usuario que ya existe en DynamoDB (registrado previamente con email+password) puede vincular su cuenta social para futuros inicios de sesión.

El alcance cubre: configuración CDK de Identity Providers en Cognito, endpoint de inicio de OAuth, manejo del callback, creación de registros DynamoDB para usuarios sociales nuevos, flujo de asociación de tenant, deduplicación por email, y entrega de tokens JWT al cliente frontend.

---

## Glossary

- **Social_Login_Service**: Componente de aplicación que orquesta el flujo OAuth completo (inicio, callback, provisioning).
- **Cognito_IDP**: AWS Cognito User Pool configurado con Google y Facebook como Identity Providers federados.
- **OAuth_Handler**: Lambda que expone los endpoints `/auth/social/authorize` y `/auth/social/callback`.
- **Post_Social_Confirmation_Handler**: Lambda trigger de Cognito (`PostConfirmation_ConfirmSignUp` o `PreTokenGeneration`) que provisiona los registros DynamoDB para usuarios sociales nuevos.
- **Tenant_Association_Service**: Componente que asigna o permite elegir el tenant de un usuario social tras el primer login.
- **User_Repository**: Repositorio DynamoDB que persiste y recupera entidades `User`.
- **Membership_Repository**: Repositorio DynamoDB que persiste y recupera entidades `TenantMembership` y `Member`.
- **Token_Pair**: Conjunto de tokens Cognito: `access_token`, `id_token`, `refresh_token` y `expires_in`.
- **Provider**: Proveedor de identidad social; valores válidos: `"google"` y `"facebook"`.
- **Social_User**: Usuario cuya identidad primaria proviene de un proveedor social (Google o Facebook).
- **Native_User**: Usuario registrado con email+password en el flujo existente.
- **Linked_User**: Native_User que ha vinculado adicionalmente un proveedor social.
- **Default_Tenant**: Tenant asignado automáticamente a un Social_User durante el primer login cuando el sistema puede determinarlo sin intervención del usuario.
- **Pending_Tenant_State**: Estado transitorio de un Social_User que ha completado el OAuth pero aún no tiene tenant asignado.
- **CDK_Stack**: `AccountManagementStack` definido en `infra/stacks/app_stack.py`.
- **Hosted_UI**: Interfaz de autorización OAuth alojada por Cognito en el dominio `auth.<env>.sport-app.com`.

---

## Requirements

### Requirement 1: Configuración de Identity Providers en Cognito (CDK)

**User Story:** As a DevOps engineer, I want Google and Facebook configured as Cognito Identity Providers in the CDK stack, so that Cognito can federate social logins without manual console configuration.

#### Acceptance Criteria

1. THE CDK_Stack SHALL configure a `UserPoolIdentityProviderGoogle` construct con `client_id` y `client_secret` leídos de AWS Secrets Manager o parámetros CDK, sin hardcodear credenciales en el código fuente.
2. THE CDK_Stack SHALL configure a `UserPoolIdentityProviderFacebook` construct con `client_id` y `client_secret` leídos de AWS Secrets Manager o parámetros CDK, sin hardcodear credenciales en el código fuente.
3. THE CDK_Stack SHALL configurar el User Pool App Client para incluir `COGNITO`, `Google` y `Facebook` en `supported_identity_providers`.
4. THE CDK_Stack SHALL habilitar el OAuth 2.0 Authorization Code Grant en el App Client con scopes `openid`, `email` y `profile`.
5. THE CDK_Stack SHALL configurar un dominio Cognito Hosted UI (`cognito_domain`) con prefijo único por entorno (ej. `sport-<env>`).
6. THE CDK_Stack SHALL registrar como `callback_urls` del App Client la URL del endpoint `/auth/social/callback` del API Gateway para cada entorno.
7. THE CDK_Stack SHALL registrar como `logout_urls` del App Client la URL de logout de la aplicación frontend para cada entorno.
8. THE CDK_Stack SHALL mapear los atributos del proveedor social `email` y `name` a los atributos estándar Cognito `email` y `name`.
9. WHEN `provider` is `"google"`, THE CDK_Stack SHALL mapear el atributo `sub` del proveedor al atributo personalizado `custom:social_sub` en Cognito.
10. WHEN `provider` is `"facebook"`, THE CDK_Stack SHALL mapear el atributo `id` del proveedor al atributo personalizado `custom:social_sub` en Cognito.

---

### Requirement 2: Endpoint de inicio del flujo OAuth

**User Story:** As a frontend developer, I want a backend endpoint that returns the Cognito Hosted UI authorization URL, so that the frontend can redirect the user to the social provider without knowing Cognito internals.

#### Acceptance Criteria

1. THE OAuth_Handler SHALL exponer un endpoint `GET /auth/social/authorize` que acepte el parámetro de query `provider` con valores válidos `"google"` y `"facebook"`.
2. WHEN a valid `provider` parameter is received, THE OAuth_Handler SHALL construir y retornar en el cuerpo JSON la `authorization_url` hacia la Cognito Hosted UI con los parámetros `response_type=code`, `client_id`, `redirect_uri`, `scope` y `identity_provider`.
3. IF the `provider` parameter is absent or has an invalid value, THEN THE OAuth_Handler SHALL return HTTP 400 con un mensaje de error descriptivo indicando los valores permitidos.
4. THE OAuth_Handler SHALL incluir un parámetro `state` opaco, firmado con HMAC-SHA256 usando una clave secreta, en la `authorization_url` para mitigar ataques CSRF.
5. THE OAuth_Handler SHALL retornar la `authorization_url` en el cuerpo HTTP 200 sin redirigir directamente, dejando la redirección en responsabilidad del cliente frontend.

---

### Requirement 3: Manejo del callback OAuth

**User Story:** As a user, I want the backend to handle the OAuth callback from Cognito seamlessly, so that after authorizing with Google or Facebook I receive my access tokens automatically.

#### Acceptance Criteria

1. THE OAuth_Handler SHALL exponer un endpoint `GET /auth/social/callback` que acepte los parámetros de query `code` y `state`.
2. WHEN the `code` and `state` parameters are received, THE OAuth_Handler SHALL verificar que el parámetro `state` coincide con el valor firmado generado en el paso de autorización, antes de procesar el `code`.
3. IF the `state` parameter is invalid or tampered, THEN THE OAuth_Handler SHALL return HTTP 400 con código de error `"invalid_state"`.
4. WHEN the `state` is valid, THE OAuth_Handler SHALL intercambiar el `code` por tokens llamando al endpoint token de la Cognito Hosted UI.
5. IF the token exchange fails, THEN THE OAuth_Handler SHALL return HTTP 400 con código de error `"token_exchange_failed"` y descripción del fallo.
6. WHEN the token exchange succeeds, THE OAuth_Handler SHALL extraer el `sub` de Cognito del `id_token` resultante para identificar al usuario.
7. WHEN a new Social_User is detected (no existe registro User en DynamoDB con ese `cognito_sub`), THE OAuth_Handler SHALL invocar el flujo de provisioning de Requirement 4 antes de retornar los tokens.
8. WHEN an existing Native_User with the same email is detected, THE OAuth_Handler SHALL invocar el flujo de vinculación de cuenta de Requirement 6 antes de retornar los tokens.
9. WHEN all post-processing completes successfully, THE OAuth_Handler SHALL retornar HTTP 200 con el Token_Pair completo (`access_token`, `id_token`, `refresh_token`, `expires_in`).

---

### Requirement 4: Provisioning de registros DynamoDB para usuarios sociales nuevos

**User Story:** As a new social user, I want my account records to be created automatically after my first OAuth login, so that I can start using the platform without a separate registration step.

#### Acceptance Criteria

1. WHEN a new Social_User completes the OAuth flow, THE Social_Login_Service SHALL crear atómicamente en DynamoDB los registros `User`, `TenantMembership`, `Member` y `UserRole` usando una transacción DynamoDB (`TransactWrite`).
2. THE Social_Login_Service SHALL crear el registro `User` con `cognito_sub` igual al `sub` de Cognito, `email` igual al email provisto por el proveedor social, `status` igual a `"active"` (no requiere confirmación de email), y `registration_type` igual a `"social"`.
3. THE Social_Login_Service SHALL asignar `registration_type = "social"` al registro `Member` para distinguirlo de registros nativos.
4. WHEN the user's email matches an existing active tenant (ej. dominio corporativo), THE Tenant_Association_Service SHALL asignar ese tenant como `default_tenant_id` del User durante el provisioning.
5. WHEN no tenant can be determined automatically, THE Social_Login_Service SHALL crear el `User` con `default_tenant_id = None` y `status = "pending_tenant"`, dejando el TenantMembership y Member pendientes hasta que se complete el Requirement 5.
6. THE Social_Login_Service SHALL usar `attribute_not_exists(PK)` en la condición del Put de User para garantizar idempotencia ante re-invocaciones del trigger.
7. WHEN the atomic transaction fails due to a conditional check (User ya existe), THE Social_Login_Service SHALL omitir la creación y continuar con el login sin error.
8. THE Social_Login_Service SHALL almacenar en el atributo `custom:provider` del usuario Cognito el valor del Provider utilizado (`"google"` o `"facebook"`).

---

### Requirement 5: Flujo de asociación de tenant para usuarios sociales

**User Story:** As a social user without an assigned tenant, I want a way to select or be assigned a tenant after my first login, so that I can access the platform's features.

#### Acceptance Criteria

1. WHEN a Social_User has `status = "pending_tenant"`, THE OAuth_Handler SHALL retornar HTTP 200 con el Token_Pair más un campo adicional `"requires_tenant_selection": true` en el cuerpo de respuesta.
2. THE Social_Login_Service SHALL exponer un endpoint `POST /auth/social/select-tenant` que acepte `tenant_id` en el cuerpo JSON, autenticado con el `access_token` del usuario.
3. WHEN a valid `tenant_id` is received and the tenant exists and is active, THE Tenant_Association_Service SHALL crear atómicamente los registros `TenantMembership`, `Member` y `UserRole` en DynamoDB y actualizar `User.default_tenant_id` y `User.status` a `"active"`.
4. IF the provided `tenant_id` does not exist or is not active, THEN THE Tenant_Association_Service SHALL return HTTP 404 con código de error `"tenant_not_found"`.
5. IF the Social_User already has an active TenantMembership for the provided `tenant_id`, THEN THE Tenant_Association_Service SHALL return HTTP 409 con código de error `"already_member"`.
6. WHEN the tenant association completes successfully, THE Tenant_Association_Service SHALL retornar HTTP 200 con los datos actualizados del usuario (user_id, email, default_tenant_id, status).
7. WHILE a Social_User has `status = "pending_tenant"`, THE OAuth_Handler SHALL permitir el acceso únicamente a los endpoints `/auth/social/select-tenant` y `/auth/logout`, retornando HTTP 403 con código `"tenant_required"` para cualquier otro endpoint protegido.

---

### Requirement 6: Vinculación de cuenta para usuarios existentes (mismo email, diferente provider)

**User Story:** As an existing user registered with email and password, I want to link my Google or Facebook account, so that I can sign in with either method without creating a duplicate account.

#### Acceptance Criteria

1. WHEN the OAuth callback receives a Social_User whose email matches an existing Native_User in DynamoDB, THE Social_Login_Service SHALL vincular el proveedor social al usuario nativo existente usando `AdminLinkProviderForUser` en Cognito, en lugar de crear un nuevo usuario.
2. WHEN linking succeeds, THE Social_Login_Service SHALL actualizar el atributo `custom:provider` del usuario Cognito para reflejar el proveedor vinculado.
3. WHEN linking succeeds, THE Social_Login_Service SHALL retornar el Token_Pair del usuario nativo existente, sin crear registros duplicados en DynamoDB.
4. IF the Social_User's email is already linked to a different provider (ej. el mismo email ya tiene Google y ahora intenta Facebook), THEN THE Social_Login_Service SHALL vincular el segundo proveedor adicionalmente, sin desvincularlo del primero.
5. IF the `AdminLinkProviderForUser` call fails, THEN THE Social_Login_Service SHALL return HTTP 409 con código de error `"provider_link_failed"` y descripción del fallo.
6. THE Social_Login_Service SHALL realizar la búsqueda de usuario existente usando el campo `email` en DynamoDB (no en Cognito) para evitar race conditions durante el primer login federado.

---

### Requirement 7: Entrega de tokens JWT al cliente frontend

**User Story:** As a frontend developer, I want the backend to return Cognito JWT tokens in a consistent format after the OAuth flow, so that the frontend can authenticate subsequent API calls the same way as with email+password login.

#### Acceptance Criteria

1. THE OAuth_Handler SHALL retornar el Token_Pair en el mismo formato JSON que el endpoint `POST /auth/login` existente: `{ "access_token": "...", "id_token": "...", "refresh_token": "...", "expires_in": 3600 }`.
2. THE OAuth_Handler SHALL retornar únicamente tokens emitidos por el Cognito_IDP configurado en el stack, de modo que el `AuthGuardMiddleware` existente pueda verificarlos sin modificaciones.
3. WHEN a Social_User completes the OAuth flow, THE OAuth_Handler SHALL incluir en la respuesta el campo `"user_id"` (UUID interno de DynamoDB) además del Token_Pair, para que el frontend no necesite parsear el JWT.
4. WHEN a Social_User has `status = "pending_tenant"`, THE OAuth_Handler SHALL incluir `"requires_tenant_selection": true` junto al Token_Pair, tal como especifica el Requirement 5.1.
5. THE OAuth_Handler SHALL retornar todos los tokens sobre HTTPS exclusivamente; IF the request arrives over HTTP, THEN THE OAuth_Handler SHALL return HTTP 301 redirigiéndolo a HTTPS.

---

### Requirement 8: Seguridad y controles de acceso

**User Story:** As a security engineer, I want all social login endpoints protected against common OAuth attacks, so that the federated authentication flow does not introduce new vulnerabilities.

#### Acceptance Criteria

1. THE OAuth_Handler SHALL validar la firma HMAC-SHA256 del parámetro `state` antes de procesar cualquier callback, rechazando requests con `state` inválido con HTTP 400.
2. THE OAuth_Handler SHALL aplicar un TTL de 10 minutos al `state`, rechazando con HTTP 400 cualquier callback que supere dicho intervalo desde que fue generado.
3. THE CDK_Stack SHALL aplicar el mismo AWS WAF que protege los endpoints existentes al nuevo recurso `/auth/social/*` del API Gateway.
4. THE Social_Login_Service SHALL sanitizar el `email` recibido del proveedor social usando el mismo value object `Email` existente antes de persistirlo en DynamoDB.
5. IF the email received from the social provider is absent or invalid, THEN THE Social_Login_Service SHALL return HTTP 422 con código de error `"invalid_provider_email"` y SHALL NOT crear ningún registro en DynamoDB.
6. THE OAuth_Handler SHALL aplicar rate limiting de máximo 20 requests por IP en una ventana de 5 minutos en los endpoints `/auth/social/authorize` y `/auth/social/callback`, retornando HTTP 429 cuando se supere el límite.
7. THE CDK_Stack SHALL almacenar los `client_secret` de Google y Facebook exclusivamente en AWS Secrets Manager, nunca en variables de entorno en texto plano ni en el código fuente.

---

### Requirement 9: Idempotencia y manejo de errores en provisioning

**User Story:** As a platform operator, I want the social login provisioning to be idempotent and to handle partial failures gracefully, so that retries never corrupt data or block users.

#### Acceptance Criteria

1. THE Social_Login_Service SHALL usar condición `attribute_not_exists(PK)` en el Put del registro `User` dentro de la transacción DynamoDB para garantizar que re-invocaciones no creen registros duplicados.
2. WHEN the DynamoDB transaction fails due to `ConditionalCheckFailed` on the User record, THE Social_Login_Service SHALL tratar esto como un caso de usuario ya existente y continuar el flujo normalmente sin retornar error.
3. WHEN a partial failure occurs during provisioning (ej. la transacción falla por razón distinta a condicional), THE Social_Login_Service SHALL registrar el error en CloudWatch Logs con nivel `ERROR` incluyendo `cognito_sub`, `email` y el tipo de fallo, y SHALL retornar HTTP 500 con código `"provisioning_failed"`.
4. THE Social_Login_Service SHALL completar el provisioning de DynamoDB dentro del handler del callback OAuth, y no en un trigger Cognito asíncrono, para evitar que el usuario reciba tokens antes de que sus registros existan.
5. WHEN provisioning succeeds, THE Social_Login_Service SHALL emitir una métrica CloudWatch `SocialLoginProvisioningSuccess` con dimensión `Provider`.
6. WHEN provisioning fails, THE Social_Login_Service SHALL emitir una métrica CloudWatch `SocialLoginProvisioningFailure` con dimensión `Provider` y `FailureReason`.

---

### Requirement 10: Observabilidad del flujo social

**User Story:** As a platform operator, I want logs and metrics for all steps of the social login flow, so that I can diagnose issues and monitor adoption.

#### Acceptance Criteria

1. THE OAuth_Handler SHALL registrar en CloudWatch Logs un evento estructurado JSON al inicio de cada callback con campos: `event_type = "social_callback_received"`, `provider`, `cognito_sub` (enmascarado a primeros 8 caracteres), `timestamp`.
2. THE OAuth_Handler SHALL registrar en CloudWatch Logs el resultado de cada callback con campos: `event_type = "social_callback_result"`, `outcome` (uno de `"new_user"`, `"linked_user"`, `"existing_user"`), `provider`, `duration_ms`.
3. THE Social_Login_Service SHALL emitir una métrica CloudWatch `SocialLoginAttempt` con dimensiones `Provider` y `Outcome` al completar cada flujo OAuth.
4. THE CDK_Stack SHALL incluir la Lambda `OAuthHandlerFn` en el construct `Observability` existente para que reciba las mismas alarmas de error rate y duración que las demás funciones.
5. IF a `state` validation failure occurs, THE OAuth_Handler SHALL registrar el evento con nivel `WARNING` incluyendo la IP de origen (ofuscada) para detección de intentos CSRF.
