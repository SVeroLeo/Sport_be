# Requirements Document

## Introduction

El frontend (Kiro FE) ya invoca tres endpoints de autenticación que aún no existen en el backend, provocando que los usuarios lleguen a callejones sin salida durante la recuperación de contraseña y durante los flujos de desafío (challenge) devueltos por Cognito en el login. Este feature implementa dichos endpoints en el backend, respaldados por AWS Cognito, respetando exactamente las convenciones del feature de autenticación existente.

Los tres endpoints a implementar son:

- `POST /auth/forgot-password` — inicia la recuperación de contraseña enviando un código de restablecimiento al email del usuario (Cognito `ForgotPassword`).
- `POST /auth/confirm-forgot-password` — completa el restablecimiento usando el código enviado por email más una nueva contraseña (Cognito `ConfirmForgotPassword`).
- `POST /auth/respond-to-challenge` — responde a un desafío de autenticación de Cognito (p. ej. `NEW_PASSWORD_REQUIRED` y otros tipos de challenge devueltos durante el login) mediante Cognito `RespondToAuthChallenge`.

El backend sigue una arquitectura Clean/Hexagonal en Python (capas domain / application / infrastructure / interfaces) sobre AWS Lambda + API Gateway. Las tres rutas son sub-rutas POST adicionales bajo el recurso `/auth` existente, servidas por la Lambda `AuthFn` ya desplegada; NO se requiere una nueva Lambda ni un nuevo árbol de recursos de API Gateway. El handler de auth enruta por sufijo de path (`handle_forgot_password`, `handle_confirm_forgot_password`, `handle_respond_to_challenge`), el controlador parsea el cuerpo JSON y valida mediante DTOs de entrada, y el adaptador de Cognito (`CognitoAuthService`, que implementa el puerto `ICognitoService`) realiza las llamadas a las APIs de Cognito con las convenciones de `client_id` / `SECRET_HASH` de los métodos existentes.

El alcance de este documento cubre únicamente el comportamiento (requirements). El diseño y las tareas, incluida la modificación posterior del CDK stack (`infra/stacks/app_stack.py`), se abordarán en fases separadas.

---

## Glossary

- **Auth_System**: El sistema de autenticación del backend, compuesto por el `Auth_Handler`, el `Auth_Controller` y el `Cognito_Auth_Service`, servido por la Lambda `AuthFn` bajo el recurso `/auth`.
- **Auth_Handler**: Lambda handler (`src/interfaces/http/handlers/auth_handler.py`) que enruta las peticiones POST `/auth/*` al método correspondiente del `Auth_Controller` según el sufijo del path.
- **Auth_Controller**: Controlador (`src/interfaces/http/controllers/auth_controller.py`, clase `AuthController`) que parsea el cuerpo JSON, valida la entrada mediante DTOs y delega al `Cognito_Auth_Service`.
- **Cognito_Auth_Service**: Adaptador de infraestructura (`src/infrastructure/auth/cognito_auth_service.py`, clase `CognitoAuthService`) que implementa el puerto `ICognitoService` y realiza las llamadas a las APIs de AWS Cognito.
- **Cognito_ForgotPassword**: Operación de AWS Cognito que inicia el restablecimiento de contraseña y envía un código de confirmación al medio de contacto del usuario (email).
- **Cognito_ConfirmForgotPassword**: Operación de AWS Cognito que completa el restablecimiento de contraseña usando el email, el código de confirmación y la nueva contraseña.
- **Cognito_RespondToAuthChallenge**: Operación de AWS Cognito que responde a un desafío de autenticación pendiente identificado por un `Challenge_Name` y una `Challenge_Session`.
- **Challenge_Name**: Identificador del tipo de desafío devuelto por Cognito (p. ej. `NEW_PASSWORD_REQUIRED`, `SMS_MFA`, `SOFTWARE_TOKEN_MFA`).
- **Challenge_Session**: Token de sesión opaco emitido por Cognito que vincula una respuesta de desafío con el intento de autenticación en curso; tiene una vigencia limitada.
- **Challenge_Responses**: Mapa de pares clave-valor requeridos por Cognito para resolver un desafío específico (p. ej. `NEW_PASSWORD` y `USERNAME` para `NEW_PASSWORD_REQUIRED`).
- **Confirmation_Code**: Código de un solo uso enviado por email al usuario durante `Cognito_ForgotPassword`, usado en `Cognito_ConfirmForgotPassword`.
- **SECRET_HASH**: Valor HMAC derivado del `client_id`, el secreto del App Client y el `username`, exigido por Cognito cuando el App Client tiene secreto configurado; se calcula con la misma convención usada por los métodos existentes del `Cognito_Auth_Service`.
- **Token_Set**: Conjunto de tokens de Cognito: `access_token`, `id_token`, `refresh_token` y `expires_in`, con la misma forma que la respuesta de login.
- **User_Enumeration**: Vulnerabilidad por la cual una respuesta permite a un atacante distinguir si un email está o no registrado; el `Auth_System` debe prevenirla en la iniciación de recuperación de contraseña.
- **Domain_Error**: Error base del dominio (`DomainError`) del que derivan `InvalidCredentialsError` y `ValidationError`, mapeados por el controlador a códigos HTTP.

---

## Requirements

### Requirement 1: Iniciar la recuperación de contraseña

**User Story:** As a registered user who forgot my password, I want to request a reset code by email, so that I can begin the password recovery process without revealing whether an account exists.

#### Acceptance Criteria

1. WHEN `POST /auth/forgot-password` is received with a syntactically valid email (a single `@`, non-empty local and domain parts, total length between 3 and 254 characters), THE Auth_System SHALL invoke Cognito_ForgotPassword for that email within 5 seconds so that a Confirmation_Code is emailed to the user.
2. WHEN Cognito_ForgotPassword completes without error, THE Auth_System SHALL respond with HTTP status 200 and a generic body indicating that, if the account exists, a reset code has been sent.
3. IF the requested email is not registered in Cognito (Cognito raises `UserNotFoundException`), THEN THE Auth_System SHALL treat it as success and respond with a byte-identical status (200) and body to the registered-email case, so that User_Enumeration is prevented.
4. IF the request body is missing or is not valid JSON, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` and SHALL NOT invoke Cognito_ForgotPassword.
5. IF the `email` field is missing, empty, whitespace-only, exceeds 254 characters, or is not a syntactically valid email address, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` and SHALL NOT invoke Cognito_ForgotPassword.
6. IF Cognito reports a rate limit condition (`LimitExceededException` or `TooManyRequestsException`) during Cognito_ForgotPassword, THEN THE Auth_System SHALL respond with HTTP status 429 and body `{"error": <message>}`.
7. IF an unexpected error other than `UserNotFoundException` occurs during Cognito_ForgotPassword, THEN THE Auth_System SHALL respond with HTTP status 500 and body `{"error": <message>}`.
8. WHERE the App Client has a client secret configured, THE Auth_System SHALL include the SECRET_HASH in the Cognito_ForgotPassword call using the same derivation convention as the existing Cognito_Auth_Service methods.
9. THE Auth_System SHALL serve `POST /auth/forgot-password` as an unauthenticated (public) route under the existing `/auth` resource served by AuthFn.

---

### Requirement 2: Confirmar el restablecimiento de contraseña

**User Story:** As a user who received a reset code, I want to submit the code together with a new password, so that I can regain access to my account.

#### Acceptance Criteria

1. WHEN `POST /auth/confirm-forgot-password` is received with a syntactically valid `email` (a single `@`, non-empty local and domain parts, total length 3–254 characters), a non-empty `confirmation_code` (length 1–2048), and a non-empty `new_password` (length 1–256), THE Auth_System SHALL invoke Cognito_ConfirmForgotPassword with those values.
2. WHEN Cognito_ConfirmForgotPassword completes without error, THE Auth_System SHALL respond with HTTP status 200 and a generic body confirming that the password has been reset.
3. WHEN the confirm-forgot-password succeeds, THE Auth_System SHALL NOT include any authentication tokens (access_token, id_token, or refresh_token) in the response body, so that the user must log in afterward.
4. IF the request body is missing or is not valid JSON, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}`.
5. IF any of `email`, `confirmation_code`, or `new_password` is missing, empty, or whitespace-only, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` identifying that a required field is missing.
6. IF the `email` field is not a syntactically valid email address, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` and SHALL NOT invoke Cognito_ConfirmForgotPassword.
7. IF Cognito reports that the new password violates the password policy (`InvalidPasswordException`), THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <reason>}` conveying the policy violation reason.
8. IF Cognito reports that the confirmation code does not match (`CodeMismatchException`), THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` indicating an invalid code.
9. IF Cognito reports that the confirmation code has expired (`ExpiredCodeException`), THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` indicating an expired code.
10. IF Cognito reports a rate limit condition (`LimitExceededException` or `TooManyRequestsException`) during Cognito_ConfirmForgotPassword, THEN THE Auth_System SHALL respond with HTTP status 429 and body `{"error": <message>}`.
11. IF an unexpected error occurs during Cognito_ConfirmForgotPassword, THEN THE Auth_System SHALL respond with HTTP status 500 and body `{"error": <message>}`.
12. WHERE the App Client has a client secret configured, THE Auth_System SHALL include the SECRET_HASH in the Cognito_ConfirmForgotPassword call using the same derivation convention as the existing Cognito_Auth_Service methods.
13. THE Auth_System SHALL serve `POST /auth/confirm-forgot-password` as an unauthenticated (public) route under the existing `/auth` resource served by AuthFn.

---

### Requirement 3: Responder a un desafío de autenticación

**User Story:** As a user prompted with an authentication challenge during login, I want to submit my challenge response, so that I can complete authentication and receive my tokens.

#### Acceptance Criteria

1. WHEN `POST /auth/respond-to-challenge` is received with a `challenge_name` that is one of the Cognito-supported challenge values (e.g. `NEW_PASSWORD_REQUIRED`, `SMS_MFA`, `SOFTWARE_TOKEN_MFA`, `CUSTOM_CHALLENGE`), a non-empty `session` of up to 2048 characters, and a `challenge_responses` that is a non-empty object/map (at least one key-value pair), THE Auth_System SHALL invoke Cognito_RespondToAuthChallenge with those values.
2. WHEN Cognito_RespondToAuthChallenge returns an authentication result containing tokens, THE Auth_System SHALL respond with HTTP status 200 and a body containing the Token_Set (`access_token`, `id_token`, `refresh_token`, `expires_in`) using the same shape as the login response, without a `challenge_name` field.
3. WHEN Cognito_RespondToAuthChallenge returns a subsequent challenge instead of tokens, THE Auth_System SHALL respond with HTTP status 200 and a body containing the next non-empty `challenge_name` and the returned non-empty `session`, and SHALL omit the `access_token`, `id_token`, and `refresh_token` fields, so that the frontend can distinguish this case from the tokens case by the presence of `challenge_name` versus `access_token`.
4. IF the request body is missing, is not valid JSON, or the top-level JSON is not an object, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` indicating a JSON object was expected.
5. IF `challenge_name` or `session` is missing or empty, or if `challenge_responses` is missing, is not an object/map, or is an empty object/map, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` identifying the missing or invalid required field.
6. IF `challenge_name` is not one of the Cognito-supported challenge values, THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <message>}` indicating the `challenge_name` is invalid.
7. IF Cognito reports that the challenge session is invalid or expired (`NotAuthorizedException` or `CodeMismatchException` on the session), THEN THE Auth_System SHALL respond with HTTP status 401 and body `{"error": <message>}` indicating the challenge session is invalid or expired.
8. IF Cognito reports that the new password supplied for a `NEW_PASSWORD_REQUIRED` challenge violates the password policy (`InvalidPasswordException`), THEN THE Auth_System SHALL respond with HTTP status 400 and body `{"error": <reason>}` whose message conveys the password-policy violation reason reported by Cognito.
9. IF an unexpected error occurs during Cognito_RespondToAuthChallenge, THEN THE Auth_System SHALL respond with HTTP status 500 and body `{"error": <message>}`.
10. WHERE the App Client has a client secret configured, THE Auth_System SHALL include the SECRET_HASH in the Cognito_RespondToAuthChallenge Challenge_Responses using the same derivation convention as the existing Cognito_Auth_Service methods.
11. THE Auth_System SHALL serve `POST /auth/respond-to-challenge` as an unauthenticated (public) route under the existing `/auth` resource served by AuthFn.

---

### Requirement 4: Convenciones transversales de respuesta y observabilidad

**User Story:** As a backend maintainer, I want the new endpoints to follow the existing auth conventions for error shape and safe logging, so that the API stays consistent and no secrets leak.

#### Acceptance Criteria

1. WHEN any of the three endpoints returns an error response, THE Auth_System SHALL use the JSON body shape `{"error": <message>}`, where `<message>` is a non-empty string (length 1–500) describing the cause without including passwords, confirmation codes, challenge sessions, SECRET_HASH values, or tokens, consistent with the existing auth endpoints.
2. WHEN any of the three endpoints returns a success response, THE Auth_System SHALL use a response containing `statusCode`, `headers` with `Content-Type: application/json`, and a serializable JSON `body`, consistent with the existing auth endpoints.
3. WHEN the Auth_System emits log records for any of the three endpoints, THE Auth_System SHALL exclude (by omission or masking with a fixed marker) passwords, confirmation codes, challenge sessions, SECRET_HASH values, and tokens from the log output.
4. IF a Domain_Error subtype is raised while handling any of the three endpoints, THEN THE Auth_System SHALL map `ValidationError` to HTTP 400, `InvalidCredentialsError` to HTTP 401, and any other Domain_Error subtype to HTTP 500, consistent with the existing controller mapping.
5. IF the Auth_Handler receives a request for `/auth/forgot-password`, `/auth/confirm-forgot-password`, or `/auth/respond-to-challenge` with an HTTP method other than POST, THEN THE Auth_System SHALL respond with HTTP status 405, an `Allow: POST` header, and body `{"error": <message>}`.
6. IF an exception not derived from Domain_Error occurs while handling any of the three endpoints, THEN THE Auth_System SHALL respond with HTTP status 500 and body `{"error": <message>}`, where `<message>` is a generic message that includes neither stack traces nor any of the sensitive values enumerated in criterion 1.
