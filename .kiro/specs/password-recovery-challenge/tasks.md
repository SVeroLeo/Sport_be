# Implementation Plan: Password Recovery & Challenge

## Overview

Implement three public POST endpoints under the existing `/auth` resource served by the already-deployed `AuthFn` Lambda: `forgot-password`, `confirm-forgot-password`, and `respond-to-challenge`. The work follows the existing Clean/Hexagonal conventions and spans four layers: domain (new `ChallengeResult` entity + `RateLimitError`), application (port methods + input DTOs), infrastructure (new `CognitoAuthService` methods), and the HTTP interface (controller handlers + handler routing). No new use cases and no new compute infrastructure are introduced — the three endpoints delegate directly from `AuthController` to the Cognito adapter, mirroring `refresh`/`logout`. The design uses Python; property-based tests use Hypothesis. CDK/deployment changes are isolated in a clearly separated final task group to be run after the code tasks.

---

## Tasks

- [ ] 1. Extend the domain layer
  - [ ] 1.1 Add `ChallengeResult` entity
    - Create `src/domain/entities/challenge_result.py` as a frozen dataclass (`slots=True`) with fields `token_pair: TokenPair | None`, `next_challenge_name: str | None`, `next_session: str | None`
    - Implement `is_authenticated()` returning `token_pair is not None`
    - Implement `authenticated(token_pair)` and `next_challenge(challenge_name, session)` classmethod factories
    - Enforce the invariant that exactly one of the two modes is populated
    - _Requirements: 3.2, 3.3_
  - [ ] 1.2 Add `RateLimitError` domain error
    - Create `src/domain/errors/rate_limit_error.py` with `RateLimitError(DomainError)` and a default message
    - _Requirements: 1.6, 2.10_
  - [ ]* 1.3 Write unit tests for `ChallengeResult` and `RateLimitError`
    - Test `authenticated()` sets `token_pair` and `is_authenticated()` is `True`
    - Test `next_challenge()` sets name/session and `is_authenticated()` is `False`
    - Test `RateLimitError` is a `DomainError` subtype
    - _Requirements: 3.2, 3.3, 1.6, 2.10_

- [ ] 2. Add new abstract methods to the `ICognitoService` port
  - [ ] 2.1 Extend `ICognitoService` with recovery/challenge methods
    - In `src/application/ports/i_cognito_service.py` add `forgot_password(email) -> None`
    - Add `confirm_forgot_password(email, confirmation_code, new_password) -> None`
    - Add `respond_to_challenge(challenge_name, session, challenge_responses) -> ChallengeResult`
    - Document anti-enumeration and raised domain errors in docstrings
    - _Requirements: 1.1, 2.1, 3.1_

- [ ] 3. Implement input DTOs
  - [ ] 3.1 Create `ForgotPasswordInputDTO`
    - Create `src/application/dtos/auth/forgot_password_input_dto.py` as a Pydantic `BaseModel` with `email: str`
    - Validate email: single `@`, non-empty local/domain, total length 3–254
    - _Requirements: 1.5_
  - [ ] 3.2 Create `ConfirmForgotPasswordInputDTO`
    - Create `src/application/dtos/auth/confirm_forgot_password_input_dto.py` with `email`, `confirmation_code`, `new_password`
    - Reuse email validation; `confirmation_code` non-empty/non-whitespace (1–2048); `new_password` non-empty/non-whitespace (1–256)
    - _Requirements: 2.5, 2.6_
  - [ ] 3.3 Create `RespondToChallengeInputDTO`
    - Create `src/application/dtos/auth/respond_to_challenge_input_dto.py` with `challenge_name`, `session`, `challenge_responses`
    - Define `SUPPORTED_CHALLENGES` set; validate `challenge_name` in set; `session` non-empty (≤2048); `challenge_responses` non-empty dict
    - _Requirements: 3.5, 3.6_

- [ ] 4. Implement `CognitoAuthService` adapter methods
  - [ ] 4.1 Implement `forgot_password` in `CognitoAuthService`
    - In `src/infrastructure/auth/cognito_auth_service.py` call boto3 `forgot_password(ClientId, Username=email)`
    - Swallow `UserNotFoundException` → `return None` (anti-enumeration)
    - Map `LimitExceededException`/`TooManyRequestsException` → `RateLimitError`
    - `logger.error(...) + raise` for unexpected codes
    - Add documented `SECRET_HASH`-conditional note (omitted today; App Client has no secret)
    - _Requirements: 1.1, 1.3, 1.6, 1.7, 1.8_
  - [ ] 4.2 Implement `confirm_forgot_password` in `CognitoAuthService`
    - Call boto3 `confirm_forgot_password(ClientId, Username, ConfirmationCode, Password)`
    - Map `InvalidPasswordException`→`ValidationError(reason)`, `CodeMismatchException`/`ExpiredCodeException`→`ValidationError`
    - Map `LimitExceededException`/`TooManyRequestsException`→`RateLimitError`; unexpected → `logger.error + raise`
    - Document `SECRET_HASH`-conditional note (omitted today)
    - _Requirements: 2.1, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12_
  - [ ] 4.3 Implement `respond_to_challenge` in `CognitoAuthService`
    - Call boto3 `respond_to_auth_challenge(ClientId, ChallengeName, Session, ChallengeResponses)`
    - Map `AuthenticationResult`→`ChallengeResult.authenticated(token_pair)`; `ChallengeName`+`Session`→`ChallengeResult.next_challenge(...)`
    - Map `NotAuthorizedException`/`CodeMismatchException`→`InvalidCredentialsError`; `InvalidPasswordException`→`ValidationError(reason)`; unexpected → `logger.error + raise`
    - Document `SECRET_HASH`-conditional note (omitted today)
    - _Requirements: 3.1, 3.2, 3.3, 3.7, 3.8, 3.9, 3.10_

- [ ] 5. Write unit tests for the adapter methods
  - [ ]* 5.1 Write unit tests for `CognitoAuthService.forgot_password`
    - In `tests/unit/infrastructure/auth/test_cognito_auth_service.py` (moto + mock)
    - Test success; `UserNotFoundException` swallowed → `None`; `LimitExceeded`→`RateLimitError`; unexpected error re-raises
    - _Requirements: 1.3, 1.6_
  - [ ]* 5.2 Write unit tests for `CognitoAuthService.confirm_forgot_password`
    - Test success; `InvalidPassword`/`CodeMismatch`/`ExpiredCode`→`ValidationError`; `LimitExceeded`→`RateLimitError`
    - _Requirements: 2.7, 2.8, 2.9, 2.10_
  - [ ]* 5.3 Write unit tests for `CognitoAuthService.respond_to_challenge`
    - Test `AuthenticationResult`→authenticated `ChallengeResult`; `ChallengeName`+`Session`→next-challenge; `NotAuthorized`→`InvalidCredentialsError`; `InvalidPassword`→`ValidationError`
    - _Requirements: 3.2, 3.3, 3.7, 3.8_

- [ ] 6. Checkpoint — Ensure all domain, DTO, and adapter tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement `AuthController` handler methods
  - [ ] 7.1 Implement `handle_forgot_password`
    - In `src/interfaces/http/controllers/auth_controller.py` reuse `_parse_body`/`_success_response`/`_error_response`
    - Parse body (400 if missing/invalid); validate `ForgotPasswordInputDTO` (400, no Cognito call); delegate to `self._cognito_service.forgot_password`
    - Map `RateLimitError`→429, other exceptions → `logger.exception` + 500
    - Always return byte-identical 200 generic body (anti-enumeration)
    - _Requirements: 1.2, 1.4, 1.5, 1.6, 1.7, 4.1, 4.2, 4.4, 4.6_
  - [ ] 7.2 Implement `handle_confirm_forgot_password`
    - Parse body (400 if missing/invalid); validate `ConfirmForgotPasswordInputDTO` (400, no Cognito call); delegate to service
    - Map `ValidationError`→400, `RateLimitError`→429, other → 500
    - Return 200 generic body WITHOUT any tokens
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 4.1, 4.2, 4.4, 4.6_
  - [ ] 7.3 Implement `handle_respond_to_challenge`
    - Parse body (400 if missing/not object); validate `RespondToChallengeInputDTO` (400, no Cognito call); delegate to service
    - Map `InvalidCredentialsError`→401, `ValidationError`→400, other → 500
    - On `is_authenticated()` return XOR token shape (no `challenge_name`); else return `challenge_name`+`session` (no tokens)
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.1, 4.2, 4.4, 4.6_

- [ ] 8. Implement `auth_handler` routing
  - [ ] 8.1 Add routing branches and `_method_not_allowed` helper
    - In `src/interfaces/http/handlers/auth_handler.py` add suffix branches for `/forgot-password`, `/confirm-forgot-password`, `/respond-to-challenge` routing to the corresponding controller methods
    - Add `_method_not_allowed()` returning 405 with `Allow: POST` header and `{"error": <message>}`; route all non-POST methods to it
    - Keep 404 for unknown routes
    - _Requirements: 1.9, 2.13, 3.11, 4.5_

- [ ] 9. Write unit tests for the controller and handler
  - [ ]* 9.1 Write unit tests for `AuthController` handlers
    - In `tests/unit/interfaces/http/controllers/test_auth_controller.py` (mock service)
    - Test per-endpoint status mapping (400/401/429/500), success shapes, no tokens in confirm success, both respond-to-challenge outcomes
    - Assert secrets are never logged (`caplog`)
    - _Requirements: 1.2, 1.4, 2.2, 2.3, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4_
  - [ ]* 9.2 Write unit tests for `auth_handler` routing
    - In `tests/unit/interfaces/http/handlers/test_auth_handler.py`
    - Test routing of the three new branches; 405 + `Allow: POST` for non-POST; 404 for unknown route
    - _Requirements: 1.9, 2.13, 3.11, 4.5_

- [ ] 10. Write property-based tests (Hypothesis, ≥100 iterations each)
  - [ ]* 10.1 Write property test: Anti-enumeration of forgot-password (Property 1)
    - **Property 1: Anti-enumeración de forgot-password**
    - **Validates: Requirements 1.2, 1.3**
    - Generate valid emails; run controller with mocked success vs swallowed `UserNotFound`; assert responses are byte-identical and 200
    - Tag: `# Feature: password-recovery-challenge, Property 1: Anti-enumeration of forgot-password`
  - [ ]* 10.2 Write property test: Input validation without side effect (Property 2)
    - **Property 2: Validación de entrada sin efecto colateral (y llamada única en entrada válida)**
    - **Validates: Requirements 1.1, 1.4, 1.5, 2.1, 2.4, 2.5, 2.6, 3.1, 3.4, 3.5, 3.6**
    - Generate malformed bodies / invalid fields per endpoint → assert 400 and service not called; valid inputs → exactly one service call
    - Tag: `# Feature: password-recovery-challenge, Property 2: Input validation without side effect`
  - [ ]* 10.3 Write property test: XOR distinguishability of respond-to-challenge (Property 3)
    - **Property 3: Distinguibilidad XOR de respond-to-challenge**
    - **Validates: Requirements 3.2, 3.3**
    - Generate authenticated vs next-challenge `ChallengeResult`; assert exactly one field set present, status 200, no `challenge_name` in authenticated case
    - Tag: `# Feature: password-recovery-challenge, Property 3: XOR distinguishability of respond-to-challenge`
  - [ ]* 10.4 Write property test: Error shape and no sensitive-material leak (Property 4)
    - **Property 4: Forma del error y no-fuga de material sensible**
    - **Validates: Requirements 4.1, 4.6**
    - Inject secrets as inputs in error scenarios; assert body is `{"error": s}` with 1≤len≤500 and no sensitive substrings
    - Tag: `# Feature: password-recovery-challenge, Property 4: Error shape and no sensitive-material leak`
  - [ ]* 10.5 Write property test: confirm-forgot-password success has no tokens (Property 5)
    - **Property 5: confirm-forgot-password exitoso no contiene tokens**
    - **Validates: Requirements 2.2, 2.3**
    - Generate valid (email, code, password) with mocked success; assert 200 body lacks `access_token`/`id_token`/`refresh_token`
    - Tag: `# Feature: password-recovery-challenge, Property 5: confirm-forgot-password success has no tokens`
  - [ ]* 10.6 Write property test: DomainError → HTTP status mapping (Property 6)
    - **Property 6: Mapeo de DomainError a estado HTTP**
    - **Validates: Requirements 1.6, 1.7, 2.7, 2.8, 2.9, 2.10, 2.11, 3.7, 3.8, 3.9, 4.4**
    - Raise each `DomainError` subtype from the mocked service; assert `ValidationError`→400, `InvalidCredentialsError`→401, `RateLimitError`→429, other→500
    - Tag: `# Feature: password-recovery-challenge, Property 6: DomainError to HTTP status mapping`
  - [ ]* 10.7 Write property test: Non-POST method yields 405 with Allow: POST (Property 7)
    - **Property 7: Método no-POST produce 405 con Allow: POST**
    - **Validates: Requirements 4.5**
    - Generate HTTP methods other than POST over the three routes; assert 405, `Allow: POST` header, and `{"error": <non-empty>}`
    - Tag: `# Feature: password-recovery-challenge, Property 7: Non-POST method yields 405 with Allow POST`

- [ ] 11. Verification checkpoint — Run the full affected test suite
  - Run `pytest` for the new/affected unit and property tests and ensure all pass (no new failures)
  - Ensure all tests pass, ask the user if questions arise.

---

## N. CDK / Deployment (run after code tasks)

> **This group changes live infrastructure and MUST be run only after the code tasks above are complete and re-checked.** It is intentionally separated from the code tasks.

- [ ] 12. Update CDK stack and infra tests
  - [ ] 12.1 Add the three API Gateway sub-resources under `auth`
    - In `infra/stacks/app_stack.py` add `forgot-password`, `confirm-forgot-password`, `respond-to-challenge` sub-resources under the existing `auth` resource
    - Each with a `POST` method pointing to the EXISTING `AuthFn` `LambdaIntegration`, public (no authorizer)
    - _Requirements: 1.9, 2.13, 3.11_
  - [ ] 12.2 Extend the `AuthFn` IAM grant
    - Extend `user_pool.grant(auth_fn, ...)` with `cognito-idp:ForgotPassword`, `cognito-idp:ConfirmForgotPassword`, `cognito-idp:RespondToAuthChallenge`
    - _Requirements: 1.1, 2.1, 3.1_
  - [ ]* 12.3 Update CDK stack tests
    - In `infra/tests/test_app_stack.py` assert the three new `PathPart`s exist and the three new Cognito IAM actions are granted
    - _Requirements: 1.9, 2.13, 3.11, 1.1, 2.1, 3.1_

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at each layer boundary
- Property tests (Properties 1–7) validate universal correctness guarantees; unit tests cover specific examples and edge cases
- The design uses Python + Hypothesis for property-based testing (≥100 iterations per property, each test tagged `# Feature: password-recovery-challenge, Property N: <text>`)
- Anti-enumeration is enforced in the adapter (`forgot_password` swallows `UserNotFoundException`), so the controller always returns a byte-identical 200
- `RateLimitError` is a dedicated `DomainError` subtype mapped to HTTP 429, kept distinct from `ValidationError`→400
- `SECRET_HASH` is omitted today (the App Client has no secret); the adapter documents the conditional extension point
- The CDK / Deployment group (task 12) modifies live infrastructure and must be run only after the code tasks are complete and re-checked
- No new use cases and no new compute infrastructure are introduced; the three endpoints delegate directly from `AuthController` to `CognitoAuthService`, mirroring `refresh`/`logout`
- No composition-root wiring change is required (`AuthController` already receives `cognito_service`)

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "3.1", "3.2", "3.3"] },
    { "id": 1, "tasks": ["1.3", "4.1", "4.2", "4.3"] },
    { "id": 2, "tasks": ["5.1", "5.2", "5.3", "7.1", "7.2", "7.3"] },
    { "id": 3, "tasks": ["8.1", "9.1"] },
    { "id": 4, "tasks": ["9.2", "10.1", "10.2", "10.3", "10.4", "10.5", "10.6", "10.7"] },
    { "id": 5, "tasks": ["12.1", "12.2"] },
    { "id": 6, "tasks": ["12.3"] }
  ]
}
```
