# Implementation Plan: AWS Multi-Region Infrastructure

## Overview

Plan de implementación de la infraestructura AWS multi-región como **infraestructura como código con AWS CDK (TypeScript)**. El plan construye la plataforma en capas: primero el andamiaje del proyecto CDK y los parámetros por región, luego los stacks regionales (DynamoDB Global Table, Cognito + ASF, WAF, API Gateway), después la capa global de enrutamiento (Route 53 + health checks + failover), la consistencia de las allow-lists de verificación de tokens, y finalmente observabilidad y validación de despliegue.

El código de aplicación en Python **no cambia**. Estas tareas solo agregan definiciones IaC y configuración. Cada tarea busca ser incremental y desplegable/validable de forma aislada.

**Parámetros a fijar antes o durante la implementación** (ver `TODO.md`): regiones concretas, política de enrutamiento por defecto (latency-based vs failover), y valores de RTO/RPO.

## Tasks

- [ ] 1. Set up CDK project structure and per-region parameters
  - [ ] 1.1 Initialize an AWS CDK (TypeScript) app under `infra/`
    - Create the CDK app, `cdk.json`, `tsconfig.json`, and install `aws-cdk-lib` + `constructs`
    - Add lint/build scripts and a `cdk synth`/`cdk diff` workflow entry
    - _Requirements: 8.1_

  - [ ] 1.2 Define a typed region-deployment configuration model
    - Create a `RegionDeployment` config type: `{ region, cognitoPoolId?, cognitoClientId?, ddbReplica, dnsTtlSeconds }`
    - Create a `RoutingPolicy` config type: `{ type: "latency" | "failover", primaryRegion?, secondaryRegions? }`
    - Centralize the list of active regions in one config module so stacks are parameterized by region
    - _Requirements: 8.2, 1.2, 1.3_

  - [ ] 1.3 Establish a parameterized multi-region app assembly
    - Instantiate regional stacks per configured region and a single global stack for Route 53
    - Wire cross-stack references (regional endpoints, pool ids, table name) via stack outputs/props
    - _Requirements: 8.2_

- [ ] 2. Implement DynamoDB Global Table (data replication)
  - [ ] 2.1 Define the single table as a Global Table with replicas per region
    - Model PK/SK and all existing GSIs; add a replica in each configured region
    - Set conflict resolution to last-writer-wins (default) and document implications in the stack
    - _Requirements: 5.1, 5.4, 5.5_

  - [ ] 2.2 Verify replicated item coverage
    - Confirm the table carries all hot-read item types (user profile with default_tenant_id, memberships, roles, account types)
    - Document eventual-consistency impact for register-then-immediate-login across regions
    - _Requirements: 5.2, 5.3_

- [ ] 3. Implement Cognito User Pool + ASF per region
  - [ ] 3.1 Define a Region-local Pool with app client in each region
    - Create the User Pool and app client; capture `iss` (`https://cognito-idp.{region}.amazonaws.com/{userPoolId}`) and client id as outputs
    - _Requirements: 7.1, 7.2_

  - [ ] 3.2 Enable Advanced Security Features with adaptive authentication
    - Turn on ASF; configure risk-based actions (allow / require MFA / block) and compromised-credentials action
    - Keep the ASF configuration equivalent across all regions
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ] 3.3 Export Cognito security events to observability
    - Route sign-in/risk events to the central logging/metrics destination
    - _Requirements: 4.5_

- [ ] 4. Implement AWS WAF (edge protection + rate limiting level 1)
  - [ ] 4.1 Define a WAF Web ACL per region
    - Attach the Web ACL to the regional API Gateway entry point
    - _Requirements: 3.1_

  - [ ] 4.2 Add AWS managed rule groups
    - Include the common rule set and the known-bad-inputs rule set
    - _Requirements: 3.2_

  - [ ] 4.3 Add rate-based rules (per source IP)
    - Configure window and threshold; this is rate limiting level 1 (edge, per IP)
    - _Requirements: 3.3, 6.1_

  - [ ] 4.4 Configure WAF logging and an allow-list
    - Send WAF logs to central observability; add an allow-list for trusted origins
    - _Requirements: 3.4, 3.5, 3.6_

- [ ] 5. Implement regional API Gateway with TLS and rate limiting level 2
  - [ ] 5.1 Define the regional API Gateway endpoint (HTTPS only) with ACM certificate
    - Provision/attach a per-region ACM certificate; enforce HTTPS-only
    - _Requirements: 1.4_

  - [ ] 5.2 Define usage plans / throttling (per client)
    - Configure API Gateway usage plans/throttling as rate limiting level 2
    - Return 429 on exceeded limits and ensure the event is logged
    - _Requirements: 6.2, 6.4_

  - [ ] 5.3 Add a health endpoint for Route 53 health checks
    - Expose `GET /health` validating minimal dependencies, per region
    - _Requirements: 2.1_

- [ ] 6. Implement Route 53 routing, health checks and failover (global stack)
  - [ ] 6.1 Create the hosted zone and alias records to regional endpoints
    - Alias records target each regional API endpoint
    - _Requirements: 1.1_

  - [ ] 6.2 Configure the routing policy (latency-based or failover) with short TTL
    - Parameterize latency vs failover from config; designate primary/secondary for failover
    - Set DNS TTL <= 60s for fast propagation
    - _Requirements: 1.2, 1.3, 1.5_

  - [ ] 6.3 Wire Route 53 health checks and automatic failover
    - Associate health checks per region with a configurable failure threshold
    - Stop routing to an unhealthy region; auto-reinstate on recovery; return a controlled error if all regions are unhealthy
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [ ] 6.4 Document RTO/RPO targets
    - Record the failover RTO/RPO targets in the stack docs (depends on DNS TTL + health check detection + replication latency)
    - _Requirements: 2.4_

- [ ] 7. Wire token-verification allow-lists to deployed pools
  - [ ] 7.1 Derive COGNITO_ISSUERS and COGNITO_CLIENT_IDS from deployed pools
    - Build both allow-lists from the set of Region-local Pools and app clients
    - Provide them to the backend Lambda via environment configuration (no JWT_SECRET)
    - _Requirements: 7.1, 7.2, 7.4_

  - [ ] 7.2 Make allow-lists update on region add/remove
    - Ensure adding/removing a region updates both allow-lists so verification stays valid for all active regions
    - _Requirements: 7.3_

- [ ] 8. Implement observability and deployment operations
  - [ ] 8.1 Emit metrics and alarms
    - Health-check status, WAF block rate, Cognito risk events, DynamoDB replication latency, and 429 rate
    - _Requirements: 8.3_

  - [ ] 8.2 Write a manual failover runbook
    - Document the manual failover procedure as a backup to automatic failover
    - _Requirements: 8.4_

- [ ] 9. Validate the multi-region deployment (post-deploy, real AWS account)
  - [ ] 9.1 Validate token portability cross-region
    - **Property 1: Token portability cross-region**
    - **Validates: Requirements 7.1, 7.3**
    - Emit a token from one region's pool and verify the backend in another region accepts it

  - [ ] 9.2 Validate allow-list consistency
    - **Property 2: Allow-list consistency**
    - **Validates: Requirements 7.1, 7.2, 7.3**
    - Confirm every active region's iss/client_id is present; simulate add/remove and re-check

  - [ ] 9.3 Validate failover safety
    - **Property 3: Failover safety**
    - **Validates: Requirements 2.2, 2.3, 2.5**
    - Simulate an unhealthy region and confirm traffic reroutes; confirm controlled error when all are unhealthy

  - [ ] 9.4 Validate replica convergence
    - **Property 4: Replica convergence**
    - **Validates: Requirements 5.1, 5.3, 5.4**
    - Write in one replica, read in another after convergence; confirm GSIs preserved

  - [ ] 9.5 Validate rate limit enforcement
    - **Property 5: Rate limit enforcement**
    - **Validates: Requirements 6.4, 6.5**
    - Exceed a configured threshold and confirm 429 + logged event; confirm the app does not reimplement the edge limit

  - [ ] 9.6 Validate HTTPS-only
    - **Property 6: HTTPS-only**
    - **Validates: Requirements 1.4**
    - Confirm no endpoint accepts unencrypted traffic

- [ ] 10. Checkpoint — multi-region infrastructure deployed and validated
  - Ensure all deployment validations (task 9) pass in the real AWS account; ask the user if questions arise.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["2.1", "3.1", "5.1"] },
    { "id": 4, "tasks": ["2.2", "3.2", "3.3", "5.2", "5.3"] },
    { "id": 5, "tasks": ["4.1", "4.2", "4.3", "4.4", "7.1"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.4", "7.2"] },
    { "id": 7, "tasks": ["8.1", "8.2"] },
    { "id": 8, "tasks": ["9.1", "9.2", "9.3", "9.4", "9.5", "9.6"] },
    { "id": 9, "tasks": ["10"] }
  ]
}
```

## Notes

- **IaC tool**: this plan targets **AWS CDK (TypeScript)** under `infra/`, since the CDK app is already being prepared. No Python application code changes.
- Task 1 (CDK scaffolding + per-region config) is the foundation for everything.
- Tasks 2 (DynamoDB Global Table), 3 (Cognito + ASF), 4 (WAF) and 5 (API Gateway) are the regional stacks; they depend on task 1 and can proceed in parallel.
- Task 4 (WAF) attaches to the regional API Gateway, so it is co-defined with / after task 5 in the regional stack (wave 5 follows wave 4).
- Task 6 (Route 53 global stack) depends on regional endpoints (task 5) and the health endpoint (5.3).
- Task 7 (allow-lists) depends on task 3 (pools/clients exist to derive issuers/client ids).
- Task 8 (observability/runbook) depends on the resources it monitors (tasks 2-6).
- Task 9 (post-deploy validation) depends on everything being deployed and runs against the real AWS account.
- Task 10 is the final checkpoint after task 9.
- **Open parameters** (tracked in `TODO.md`): concrete regions, default routing policy (latency vs failover), and RTO/RPO targets. These affect tasks 1.2, 6.2 and 6.4 but do not block scaffolding.

