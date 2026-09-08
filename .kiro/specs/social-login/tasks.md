# Implementation Plan: Social Login

## Overview

Implement federated social authentication (Google and Facebook) on top of the existing Account Management backend. The work spans three layers: CDK infrastructure configuration, application/domain logic (use cases, ports, domain model extensions), and an HTTP interface (new `OAuthHandlerFn` Lambda). Provisioning of DynamoDB records is synchronous inside the OAuth callback handler so tokens are only returned after the user's records exist.

---

## Tasks

- [x] 1. Extend domain model for social login
  - [x] 1.1 Add `"pending_tenant"` to `UserStatus` and `registration_type="social"` to `User`
    - Extend `UserStatus = Literal[..., "pending_tenant"]` in the `User` entity
    - Add `registration_type: Literal["native", "social"] = "native"` field to `User`
    - Update `User.create()` factory to accept `registration_type` parameter
    - _Requirements: 4.2, 4.3, 5.1_
  - [x] 1.2 Write unit tests for extended `User` entity
    - Test `User.create()` with `status="pending_tenant"`
    - Test `User.create()` with `registration_type="social"`
    - _Requirements: 4.2, 4.3_

  - [x] 1.3 Add `"social"` to `Member` valid registration types
    - Add `"social"` to `_VALID_REGISTRATION_TYPES` frozenset in `member.py`
    - _Requirements: 4.3_
  - [x] 1.4 Write unit tests for `Member.create()` with `registration_type="social"`
    - Test valid creation and rejection of unknown types
    - _Requirements: 4.3_

- [x] 2. Implement state token module (`state_token.py`)
  - [x] 2.1 Create `application/services/state_token.py` with `generate_state` and `validate_state`
    - Implement `generate_state(secret: str, now: datetime | None = None) -> str`
    - Format: `base64url(timestamp_iso) + "." + hex(hmac_sha256(secret, timestamp_iso))`
    - Implement `validate_state(token: str, secret: str, now: datetime | None = None) -> None`
    - Raise `ValidationError("invalid_state")` on bad HMAC or TTL > 10 minutes
    - Use `hmac.compare_digest` for constant-time comparison
    - _Requirements: 2.4, 3.2, 3.3, 8.1, 8.2_
  - [x] 2.2 Write property test: State token HMAC integrity round-trip (Property 1)
    - **Property 1: State token HMAC integrity round-trip**
    - **Validates: Requirements 2.4, 3.2, 8.1**
    - Use `hypothesis.strategies.datetimes` for arbitrary UTC timestamps within valid window
    - Assert `validate_state(generate_state(secret, ts), secret, now=ts)` passes
    - Mutate one character in the signature half; assert validation raises `ValidationError`
  - [x] 2.3 Write property test: State token TTL enforcement (Property 2)
    - **Property 2: State token TTL enforcement**
    - **Validates: Requirements 8.2**
    - Generate a token at time T; draw a timedelta from 0 to 24 hours
    - Assert validation passes iff `delta.total_seconds() < 600`
  - [x] 2.4 Write unit tests for state token module
    - Test valid token round-trip within TTL
    - Test expired token raises `ValidationError`
    - Test tampered signature raises `ValidationError`
    - _Requirements: 2.4, 8.1, 8.2_

- [x] 3. Checkpoint — Ensure all domain and state-token tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add new port methods to `ICognitoService` and `IUserRepository`
  - [x] 4.1 Extend `ICognitoService` with social-login abstract methods
    - Add `exchange_code_for_tokens(code, redirect_uri, hosted_ui_domain) -> TokenPair`
    - Add `admin_link_provider_for_user(destination_cognito_sub, provider_name, provider_user_id) -> None`
    - Add `admin_update_user_attributes(cognito_sub, attributes: dict[str, str]) -> None`
    - _Requirements: 3.4, 6.1, 6.2_
  - [x] 4.2 Extend `IUserRepository` with social-login abstract methods
    - Add `find_by_cognito_sub(cognito_sub: str) -> User | None`
    - Add `register_social_user(user, membership, member, role) -> None` (atomic `TransactWrite` with `attribute_not_exists(PK)`)
    - Add `associate_tenant(user_id, membership, member, role, new_status, new_default_tenant_id) -> None` (atomic write)
    - _Requirements: 4.1, 4.6, 5.3, 9.1_

- [x] 5. Implement Cognito adapter methods for social login
  - [x] 5.1 Add `exchange_code_for_tokens` to `CognitoAuthService`
    - Call Cognito Hosted UI `POST /oauth2/token` with `authorization_code` grant
    - Parse response into `TokenPair`
    - Raise mapped error with code `"token_exchange_failed"` on failure
    - _Requirements: 3.4, 3.5_
  - [x] 5.2 Add `admin_link_provider_for_user` to `CognitoAuthService`
    - Call `cognito_idp.admin_link_provider_for_user`
    - Raise mapped error with code `"provider_link_failed"` on failure
    - _Requirements: 6.1, 6.5_
  - [x] 5.3 Add `admin_update_user_attributes` to `CognitoAuthService`
    - Call `cognito_idp.admin_update_user_attributes`
    - _Requirements: 6.2, 4.8_
  - [x] 5.4 Write unit tests for Cognito adapter social methods
    - Mock boto3 Cognito client; test happy paths and error mappings
    - _Requirements: 3.4, 3.5, 6.1, 6.5_

- [x] 6. Implement DynamoDB repository methods for social login
  - [x] 6.1 Add `find_by_cognito_sub` to `DynamoDBUserRepository`
    - Scan with filter expression on `cognito_sub` attribute (consistent with existing `find_by_id` pattern)
    - Return `User | None`
    - _Requirements: 3.6_
  - [x] 6.2 Add `register_social_user` to `DynamoDBUserRepository`
    - Build `TransactWrite` items: `User` (with `attribute_not_exists(PK)` condition), and optionally `TenantMembership`, `Member`, `UserRole` when tenant is known
    - Handle `ConditionalCheckFailed` silently (idempotent re-invocation)
    - _Requirements: 4.1, 4.6, 4.7, 9.1, 9.2_
  - [x] 6.3 Add `associate_tenant` to `DynamoDBUserRepository`
    - Atomic `TransactWrite`: write `TenantMembership`, `Member`, `UserRole` and update `User.default_tenant_id` + `User.status`
    - _Requirements: 5.3, 9_
  - [x] 6.4 Write unit tests for DynamoDB repository social methods
    - Mock DynamoDB client; test happy paths, conditional check handling, and error propagation
    - _Requirements: 4.1, 4.6, 4.7, 5.3, 9.1, 9.2_

- [x] 7. Checkpoint — Ensure all adapter and repository tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement `SocialAuthorizeUseCase`
  - [x] 8.1 Create `application/use_cases/social_authorize_use_case.py`
    - Validate `provider` is `"google"` or `"facebook"`; raise `ValidationError("invalid_provider")` otherwise
    - Generate state token via `state_token.generate_state`
    - Build Cognito Hosted UI authorization URL with `response_type=code`, `client_id`, `redirect_uri`, `scope=openid email profile`, `identity_provider`, `state`
    - Return `SocialAuthorizeOutputDTO(authorization_url=...)`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 8.2 Write property test: Provider parameter validation (Property 3)
    - **Property 3: Provider parameter validation**
    - **Validates: Requirements 2.1, 2.3**
    - Use `hypothesis.strategies.text()` filtering out `"google"` and `"facebook"`
    - Assert `SocialAuthorizeUseCase.execute(provider=s)` raises `ValidationError` for all such inputs
  - [x] 8.3 Write property test: Authorization URL contains all required OAuth parameters (Property 4)
    - **Property 4: Authorization URL contains all required OAuth parameters**
    - **Validates: Requirements 2.2**
    - Draw provider from `st.sampled_from(["google", "facebook"])`
    - Parse returned URL; assert `response_type`, `client_id`, `redirect_uri`, `scope`, `identity_provider`, `state` are all present and non-empty
  - [x] 8.4 Write unit tests for `SocialAuthorizeUseCase`
    - Test valid URL returned for `"google"` and `"facebook"`
    - Test `ValidationError` for invalid provider values
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 9. Implement `SocialCallbackUseCase`
  - [x] 9.1 Create `application/use_cases/social_callback_use_case.py`
    - Validate `state` (HMAC + TTL); raise `ValidationError("invalid_state")` on failure
    - Exchange `code` for tokens via `cognito_service.exchange_code_for_tokens`
    - Decode `id_token` JWT payload (no signature verification) to extract `sub`, `email`, `name`, `custom:provider`
    - Validate email with `Email.create()`; raise `ValidationError("invalid_provider_email")` if invalid
    - Look up `User` by `cognito_sub` → fast-path return if found
    - Look up `User` by `email` → route to `_link_provider` for Native_User or `_provision_new_user` for new Social_User
    - Build and return `SocialLoginOutputDTO` (include `requires_tenant_selection` when `status=="pending_tenant"`)
    - Emit `SocialLoginAttempt` CloudWatch metric with `Provider` and `Outcome` dimensions
    - Log structured JSON events at start and end of each callback (Requirements 10.1, 10.2)
    - _Requirements: 3.1–3.9, 6, 7.1, 7.3, 7.4, 8.4, 8.5, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3_
  - [x] 9.2 Implement `_provision_new_user` internal method
    - Auto-assign tenant from email domain when possible; otherwise set `status="pending_tenant"` and `default_tenant_id=None`
    - Create `User` (with `registration_type="social"`), and optionally `TenantMembership`, `Member`, `UserRole`
    - Call `user_repository.register_social_user`
    - Call `cognito_service.admin_update_user_attributes` to set `custom:provider`
    - Emit provisioning metrics (Requirements 9.5, 9.6)
    - Log provisioning errors at `ERROR` level with masked `cognito_sub` and `email` domain (Requirement 9.3)
    - _Requirements: 4.1–4.8, 9.3–9.6_
  - [x] 9.3 Implement `_link_provider` internal method
    - Call `cognito_service.admin_link_provider_for_user`
    - Call `cognito_service.admin_update_user_attributes` to update `custom:provider`
    - Return existing user's tokens without creating duplicate DynamoDB records
    - _Requirements: 6.1–6.6_
  - [x] 9.4 Write property test: Social user provisioning idempotence (Property 5)
    - **Property 5: Social user provisioning idempotence and field correctness**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.6, 4.7, 9.1, 9.2**
    - Generate arbitrary (cognito_sub, email, full_name) triples
    - Call provisioning logic N times (N from 1–5) against mocked `DynamoDBUserRepository`
    - Assert `User` record is written exactly once with `registration_type="social"` and correct `cognito_sub`
    - Assert all duplicate calls are silently skipped
  - [x] 9.5 Write property test: Pending-tenant flag matches user status (Property 7)
    - **Property 7: Pending-tenant flag matches user status**
    - **Validates: Requirements 5.1, 7.4**
    - Generate arbitrary `User` entities with status drawn from all `UserStatus` values
    - Assert `build_callback_response(user, token_pair)["requires_tenant_selection"]` is `True` iff `user.status == "pending_tenant"`
  - [x] 9.6 Write property test: Token response format consistency (Property 8)
    - **Property 8: Token response format consistency**
    - **Validates: Requirements 7.1, 7.3**
    - Generate arbitrary `SocialLoginOutputDTO` instances with random token strings and `user_id`
    - Assert serialized JSON contains `access_token`, `id_token`, `refresh_token`, `expires_in`, `user_id` with non-null values
  - [x] 9.7 Write unit tests for `SocialCallbackUseCase`
    - Test state validation rejection (invalid HMAC, expired)
    - Test routing to provisioning for new user
    - Test routing to linking for existing native user
    - Test email validation rejection
    - _Requirements: 3.2, 3.3, 3.5, 3.7, 3.8, 8.4, 8.5_

- [x] 10. Implement `TenantAssociationUseCase`
  - [x] 10.1 Create `application/use_cases/tenant_association_use_case.py`
    - Find `User` by `user_id`; verify `status == "pending_tenant"`
    - Find `Tenant` by `tenant_id`; raise `ValidationError("tenant_not_found")` if missing or inactive
    - Check for existing `TenantMembership`; raise `ValidationError("already_member")` if present
    - Create `TenantMembership`, `Member` (with `registration_type="social"`), and `UserRole("viewer")`
    - Call `user_repository.associate_tenant` (atomic write)
    - Return `TenantAssociationOutputDTO`
    - _Requirements: 5.2–5.6_
  - [x] 10.2 Write property test: Tenant association atomicity (Property 9)
    - **Property 9: Tenant association atomicity**
    - **Validates: Requirements 5.3**
    - Generate arbitrary (user_id, tenant_id) pairs; build `User` with `status="pending_tenant"` and valid active `Tenant`
    - Assert all three records (TenantMembership, Member, UserRole) are written in a single `transact_write_items` call
    - Assert `User.status` transitions to `"active"`
  - [x] 10.3 Write unit tests for `TenantAssociationUseCase`
    - Test 404 on missing/inactive tenant
    - Test 409 on already-member
    - Test successful association returns updated user data
    - _Requirements: 5.3, 5.4, 5.5, 5.6_

- [x] 11. Implement new DTOs
  - [x] 11.1 Create `application/dtos/social_login_dtos.py`
    - Define `SocialAuthorizeOutputDTO(authorization_url: str)`
    - Define `SocialLoginOutputDTO(access_token, id_token, refresh_token, expires_in, user_id, requires_tenant_selection=False)`
    - Define `SelectTenantInputDTO(tenant_id: str)`
    - Define `TenantAssociationOutputDTO(user_id, email, default_tenant_id, status)`
    - _Requirements: 2.5, 5.1, 7.1, 7.3, 7.4_
  - [x] 11.2 Write property test: Email sanitization preserves canonical form (Property 6)
    - **Property 6: Email sanitization preserves canonical form**
    - **Validates: Requirements 8.4**
    - Generate valid email strings with arbitrary leading/trailing whitespace and mixed case using Hypothesis
    - Assert `Email.create(raw).value == raw.strip().lower()` for all accepted inputs

- [x] 12. Checkpoint — Ensure all use case and DTO tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement `OAuthController` and HTTP layer
  - [x] 13.1 Create `interface/controllers/oauth_controller.py`
    - Implement `GET /auth/social/authorize`: extract `provider` query param; call `SocialAuthorizeUseCase`; return HTTP 200 JSON with `authorization_url`; return HTTP 400 on `ValidationError("invalid_provider")`
    - Implement `GET /auth/social/callback`: extract `code` and `state`; call `SocialCallbackUseCase`; return HTTP 200 with `SocialLoginOutputDTO`; map error codes to HTTP 400/422/409/500
    - Implement `POST /auth/social/select-tenant`: require `AuthGuardMiddleware`; extract `tenant_id` from body; call `TenantAssociationUseCase`; return HTTP 200/404/409
    - Enforce HTTPS redirect (HTTP 301) when request arrives over HTTP (Requirement 7.5)
    - Log `WARNING` with masked IP on `state` validation failures (Requirement 10.5)
    - _Requirements: 2.1, 2.3, 2.5, 3.1, 3.3, 3.5, 3.9, 5.2, 5.4, 5.5, 5.6, 7.1, 7.3, 7.4, 7.5, 8.1_
  - [x] 13.2 Write unit tests for `OAuthController`
    - Test HTTP 400 on missing `provider` query param
    - Test HTTP 400 on missing `code` query param
    - Test HTTP 301 on HTTP request
    - Test `requires_tenant_selection` field in response for pending-tenant user
    - _Requirements: 2.3, 3.3, 7.4, 7.5_

- [x] 14. Implement `AuthGuardMiddleware` pending-tenant access control
  - [x] 14.1 Extend `AuthGuardMiddleware` to enforce pending-tenant restriction
    - After JWT validation, load `User` and check `status`
    - If `status == "pending_tenant"` and path is not `/auth/social/select-tenant` or `/auth/logout`, return HTTP 403 with `{"error": "tenant_required"}`
    - _Requirements: 5.7_
  - [x] 14.2 Write property test: Pending-tenant access control (Property 10)
    - **Property 10: Pending-tenant access control**
    - **Validates: Requirements 5.7**
    - Generate arbitrary path strings that are not `/auth/social/select-tenant` and not `/auth/logout`
    - Build a JWT for a user with `status == "pending_tenant"`
    - Assert `AuthGuardMiddleware` returns HTTP 403 with `error == "tenant_required"` for every such path
  - [x] 14.3 Write unit tests for `AuthGuardMiddleware` pending-tenant enforcement
    - Test allowed paths pass through
    - Test blocked paths return 403 `"tenant_required"`
    - _Requirements: 5.7_

- [x] 15. Create Lambda entry point and composition root
  - [x] 15.1 Create `oauth_handler.py` Lambda entry point
    - Mirror `auth_handler.py` pattern: parse API Gateway event, route to `OAuthController`
    - Apply rate-limiting check (20 req/IP/5 min) for `/authorize` and `/callback` endpoints (Requirement 8.6)
    - _Requirements: 8.6_
  - [x] 15.2 Create `social_login_composition_root.py`
    - Wire `CognitoAuthService`, `DynamoDBUserRepository`, `DynamoDBTenantRepository`
    - Read environment variables: `TABLE_NAME`, `REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_HOSTED_UI_DOMAIN`, `COGNITO_CALLBACK_URL`, `SOCIAL_STATE_SECRET`
    - Mirror `post_confirmation_handler` composition root pattern to avoid CDK circular deps
    - _Requirements: 8.6, 9.4_

- [x] 16. Checkpoint — Ensure all controller and middleware tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Update CDK stack (`infra/stacks/app_stack.py`)
  - [x] 17.1 Add Cognito custom attributes and Identity Providers
    - Add `custom:social_sub` (mutable) and `custom:provider` (mutable) to the User Pool schema
    - Add `UserPoolIdentityProviderGoogle` with credentials from Secrets Manager (`social/google`)
    - Add `UserPoolIdentityProviderFacebook` with credentials from Secrets Manager (`social/facebook`)
    - Map provider attributes: `email`→`email`, `name`→`name`, `sub`→`custom:social_sub` (Google), `id`→`custom:social_sub` (Facebook)
    - _Requirements: 1.1, 1.2, 1.8, 1.9, 1.10_
  - [x] 17.2 Extend Cognito App Client for OAuth flows
    - Update App Client to include `COGNITO`, `Google`, `Facebook` in `supported_identity_providers`
    - Enable Authorization Code Grant with scopes `openid`, `email`, `profile`
    - Register `callback_urls` (API Gateway `/auth/social/callback`) and `logout_urls` per environment
    - Configure `UserPoolDomain` with prefix `sport-<env>`
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7_
  - [x] 17.3 Add `OAuthHandlerFn` Lambda and CloudWatch resources
    - Define `OAuthHandlerFn` Lambda with all required environment variables
    - Source `SOCIAL_STATE_SECRET` from Secrets Manager (not plaintext env var)
    - Create `OAuthHandlerLogGroup`
    - Register `/auth/social/{proxy+}` routes in API Gateway pointing to `OAuthHandlerFn`
    - Include `OAuthHandlerFn` in the `Observability` construct
    - _Requirements: 1.7, 8.3, 8.7, 10.4_
  - [x] 17.4 Apply WAF to `/auth/social/*` API Gateway resource
    - Associate the existing AWS WAF with the new `/auth/social/*` resource
    - _Requirements: 8.3_
  - [x] 17.5 Write CDK snapshot tests
    - Assert synthesized template includes `UserPoolIdentityProviderGoogle`, `UserPoolIdentityProviderFacebook`, `OAuthHandlerFn`, and WAF association for `/auth/social/*`
    - Assert no credentials appear in the template (only Secrets Manager dynamic references)
    - _Requirements: 1.1, 1.2, 8.7_

- [x] 18. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at each layer boundary
- Property tests (Properties 1–10) validate universal correctness guarantees; unit tests cover specific examples and edge cases
- The design uses Python + Hypothesis for property-based testing
- `register_social_user` uses `attribute_not_exists(PK)` to guarantee idempotency — `ConditionalCheckFailed` is treated as success
- All secrets (Google and Facebook `client_secret`, `SOCIAL_STATE_SECRET`) must live in AWS Secrets Manager; never in plaintext environment variables
- The `OAuthHandlerFn` shares the same code bundle as the existing Lambdas but has its own entry point and IAM permissions
- CDK `_build_cognito()` must be refactored to produce a single App Client with social IDP settings — CDK does not allow patching an existing `UserPoolClient` construct after creation

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "2.1", "11.1"] },
    { "id": 1, "tasks": ["1.2", "1.4", "2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["4.1", "4.2"] },
    { "id": 3, "tasks": ["5.1", "5.2", "5.3", "6.1", "6.2", "6.3"] },
    { "id": 4, "tasks": ["5.4", "6.4", "8.1", "10.1"] },
    { "id": 5, "tasks": ["8.2", "8.3", "8.4", "10.2", "10.3", "11.2", "9.1"] },
    { "id": 6, "tasks": ["9.2", "9.3"] },
    { "id": 7, "tasks": ["9.4", "9.5", "9.6", "9.7"] },
    { "id": 8, "tasks": ["13.1", "14.1"] },
    { "id": 9, "tasks": ["13.2", "14.2", "14.3", "15.1", "15.2"] },
    { "id": 10, "tasks": ["17.1", "17.2"] },
    { "id": 11, "tasks": ["17.3", "17.4"] },
    { "id": 12, "tasks": ["17.5"] }
  ]
}
```
