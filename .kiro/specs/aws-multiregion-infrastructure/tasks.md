# Implementation Plan: AWS Multi-Region Infrastructure

## Overview

Plan de implementación de la infraestructura AWS como **infraestructura como código con AWS CDK (Python)** bajo `infra/`. El plan se ejecuta en **dos fases**:

- **Fase 1 — Single-region (en curso / mayormente hecha)**: desplegar el backend completo en **una sola región (`sa-east-1`, São Paulo)** para dev y prod. Es el punto de partida para dar los primeros pasos en AWS. Ya existe una app CDK en Python (`infra/app.py`, `infra/config.py`, `infra/stacks/app_stack.py`) que provisiona tabla DynamoDB, Cognito, Lambdas, API Gateway, WAF regional y observabilidad.
- **Fase 2 — Multi-region (pendiente)**: promover esa base a multi-región: DynamoDB Global Tables, Cognito ASF, pools por región, WAF por región, Route 53 con health checks y failover, y consistencia de allow-lists cross-region. Requiere fijar los parámetros abiertos (regiones, política de enrutamiento, RTO/RPO) — ver `TODO.md`.

El código de aplicación en Python **no cambia**. Estas tareas solo agregan definiciones IaC y configuración.

**Nota de herramienta:** el spec original apuntaba a CDK en **TypeScript**; la implementación real se hizo en **CDK Python** (decisión del proyecto). Este documento refleja Python.

**Nota de despliegue:** el objetivo de esta fase es dejar el artefacto **listo para subir a AWS** por otra persona. El agente prepara y valida la definición IaC (`cdk synth`, tests); un operador con credenciales ejecuta `cdk deploy`. Ver la guía en `infra/DEPLOYMENT.md`.

**Leyenda de estado:**
- `[x]` hecho (single-region)
- `[~]` parcialmente hecho (single-region cubierto; falta la parte multi-region)
- `[ ]` pendiente (mayormente Fase 2 / requiere cuenta AWS)

## Tasks

- [x] 1. Set up CDK project structure and per-region parameters
  - [x] 1.1 Initialize an AWS CDK (Python) app under `infra/`
    - CDK app en Python creado: `app.py`, `cdk.json` (`"app": "python app.py"`), `requirements.txt` con `aws-cdk-lib` + `constructs`, `requirements-dev.txt`
    - Workflow `cdk synth` / `cdk diff` documentado en `infra/README.md`; tests CDK en `infra/tests/`
    - _Requirements: 8.1_

  - [~] 1.2 Define a typed region-deployment configuration model
    - Hecho (single-region): `EnvConfig` en `infra/config.py` parametriza dev/prod y centraliza `REGION = "sa-east-1"`
    - Pendiente (multi-region): tipos `RegionDeployment { region, cognitoPoolId?, cognitoClientId?, ddbReplica, dnsTtlSeconds }` y `RoutingPolicy { type: "latency" | "failover", primaryRegion?, secondaryRegions? }`, y una lista de regiones activas que parametrice los stacks por región
    - _Requirements: 8.2, 1.2, 1.3_

  - [ ] 1.3 Establish a parameterized multi-region app assembly
    - Pendiente (Fase 2): instanciar stacks regionales por región configurada + un único global stack para Route 53
    - Cablear referencias cross-stack (endpoints regionales, pool ids, table name) vía outputs/props
    - Hoy: `app.py` instancia un `AccountManagementStack` por entorno (dev/prod), ambos en `sa-east-1`; no hay global stack
    - _Requirements: 8.2_

- [ ] 2. Implement DynamoDB Global Table (data replication) — **Fase 2**
  - [~] 2.1 Define the single table as a Global Table with replicas per region
    - Hecho (single-region): la tabla única con PK/SK + GSI1 + GSI2 (PAY_PER_REQUEST) está modelada en `app_stack._build_table`
    - Pendiente (multi-region): convertirla en Global Table con una réplica por región configurada; documentar last-writer-wins
    - _Requirements: 5.1, 5.4, 5.5_

  - [ ] 2.2 Verify replicated item coverage
    - Pendiente (Fase 2): confirmar que la tabla lleva todos los tipos de ítem de lectura en caliente (perfil con default_tenant_id, membresías, roles, tipos de cuenta)
    - Documentar impacto de consistencia eventual para registro-luego-login-inmediato entre regiones
    - _Requirements: 5.2, 5.3_

- [ ] 3. Implement Cognito User Pool + ASF per region
  - [x] 3.1 Define a Region-local Pool with app client in each region
    - Hecho (single-region): User Pool + app client creados en `app_stack._build_cognito`; se emite `iss` (`https://cognito-idp.{region}.amazonaws.com/{userPoolId}`) y client id como outputs (`CognitoIssuer`, `UserPoolClientId`)
    - Fase 2: replicar la definición por cada región configurada
    - _Requirements: 7.1, 7.2_

  - [ ] 3.2 Enable Advanced Security Features with adaptive authentication
    - Pendiente: activar ASF; configurar acciones por riesgo (allow / require MFA / block) y acción de credenciales comprometidas
    - Mantener la configuración de ASF equivalente en todas las regiones
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ] 3.3 Export Cognito security events to observability
    - Pendiente: enrutar eventos de sign-in/riesgo al destino central de logs/métricas
    - _Requirements: 4.5_

- [~] 4. Implement AWS WAF (edge protection + rate limiting level 1)
  - [x] 4.1 Define a WAF Web ACL per region
    - Hecho (single-region): Web ACL REGIONAL asociado al stage del API Gateway (`lambda_assets/api_waf.py`, construct `ApiWaf`)
    - Fase 2: replicar por región
    - _Requirements: 3.1_

  - [x] 4.2 Add AWS managed rule groups
    - Hecho: `AWSManagedRulesCommonRuleSet` + `AWSManagedRulesKnownBadInputsRuleSet`
    - _Requirements: 3.2_

  - [x] 4.3 Add rate-based rules (per source IP)
    - Hecho: regla rate-based por IP (dev 2000 / prod 10000 por ventana de 5 min) — rate limiting nivel 1
    - _Requirements: 3.3, 6.1_

  - [ ] 4.4 Configure WAF logging and an allow-list
    - Pendiente: enviar logs de WAF a observabilidad central (WAF logging config → CloudWatch Logs / Firehose) y añadir allow-list para orígenes de confianza
    - Hoy: el Web ACL tiene métricas CloudWatch (`sampled_requests_enabled`) pero no logging destino ni allow-list
    - _Requirements: 3.4, 3.5, 3.6_

- [~] 5. Implement regional API Gateway with TLS and rate limiting level 2
  - [~] 5.1 Define the regional API Gateway endpoint (HTTPS only) with ACM certificate
    - Hecho (single-region): API Gateway REST desplegado; el endpoint `execute-api` es **HTTPS-only** por defecto (Property 6 satisfecha en la base)
    - Pendiente: custom domain con certificado ACM por región + base path mapping (Route 53) — registrado en `TODO.md`
    - _Requirements: 1.4_

  - [~] 5.2 Define usage plans / throttling (per client)
    - Hecho (single-region): throttling a nivel de stage (`throttling_rate_limit` / `throttling_burst_limit` en `_build_api`); API Gateway devuelve 429 al superar el límite y lo registra (logging INFO + métricas activadas)
    - Pendiente: usage plans / API keys por cliente como rate limiting nivel 2 explícito
    - _Requirements: 6.2, 6.4_

  - [x] 5.3 Add a health endpoint for Route 53 health checks
    - Hecho: `GET /health` público (MockIntegration → `{"status":"ok"}`) por entorno, listo para health checks de Route 53
    - _Requirements: 2.1_

- [ ] 6. Implement Route 53 routing, health checks and failover (global stack) — **Fase 2**
  - [ ] 6.1 Create the hosted zone and alias records to regional endpoints
    - Pendiente: hosted zone + registros alias hacia cada endpoint regional
    - _Requirements: 1.1_

  - [ ] 6.2 Configure the routing policy (latency-based or failover) with short TTL
    - Pendiente: parametrizar latency vs failover desde config; designar primary/secondary; TTL <= 60s
    - _Requirements: 1.2, 1.3, 1.5_

  - [ ] 6.3 Wire Route 53 health checks and automatic failover
    - Pendiente: health checks por región con umbral configurable; dejar de enrutar a región no sana; reincorporar al recuperarse; error controlado si todas caen
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [ ] 6.4 Document RTO/RPO targets
    - Pendiente: fijar y documentar RTO/RPO (depende de TTL DNS + detección de health check + latencia de replicación) — registrado en `TODO.md`
    - _Requirements: 2.4_

- [~] 7. Wire token-verification allow-lists to deployed pools
  - [x] 7.1 Derive COGNITO_ISSUERS and COGNITO_CLIENT_IDS from deployed pools
    - Hecho (single-region): `COGNITO_ISSUERS` / `COGNITO_CLIENT_IDS` se derivan del User Pool y app client creados y se inyectan a las Lambdas vía entorno; **no se usa `JWT_SECRET`** (verificado por test)
    - Fase 2: componer ambas allow-lists a partir del conjunto de pools/clients de todas las regiones
    - _Requirements: 7.1, 7.2, 7.4_

  - [ ] 7.2 Make allow-lists update on region add/remove
    - Pendiente (Fase 2): agregar/quitar una región actualiza ambas allow-lists para que la verificación siga válida en todas las regiones activas
    - _Requirements: 7.3_

- [~] 8. Implement observability and deployment operations
  - [~] 8.1 Emit metrics and alarms
    - Hecho (single-region): SNS alarm topic + alarmas CloudWatch para Lambdas (errores/throttles), API Gateway (5XX, p99) y DynamoDB (user/system errors) — `lambda_assets/observability.py`
    - Pendiente: alarmas de estado de health checks, tasa de bloqueos de WAF, eventos de riesgo de Cognito, latencia de replicación de DynamoDB y tasa de 429; suscribir un endpoint al SNS topic (email/Slack/PagerDuty) — registrado en `TODO.md`
    - _Requirements: 8.3_

  - [ ] 8.2 Write a manual failover runbook
    - Pendiente (Fase 2): documentar el procedimiento de failover manual como respaldo del automático
    - _Requirements: 8.4_

- [ ] 9. Validate the multi-region deployment (post-deploy, real AWS account) — **Fase 2, requiere cuenta AWS**
  - [ ] 9.1 Validate token portability cross-region
    - **Property 1: Token portability cross-region** — **Validates: Requirements 7.1, 7.3**
    - Emitir un token en el pool de una región y verificar que el backend de otra lo acepta
  - [ ] 9.2 Validate allow-list consistency
    - **Property 2: Allow-list consistency** — **Validates: Requirements 7.1, 7.2, 7.3**
    - Confirmar que iss/client_id de cada región activa está presente; simular add/remove y re-chequear
  - [ ] 9.3 Validate failover safety
    - **Property 3: Failover safety** — **Validates: Requirements 2.2, 2.3, 2.5**
    - Simular una región no sana y confirmar reencaminamiento; error controlado si todas caen
  - [ ] 9.4 Validate replica convergence
    - **Property 4: Replica convergence** — **Validates: Requirements 5.1, 5.3, 5.4**
    - Escribir en una réplica, leer en otra tras converger; confirmar GSIs preservados
  - [ ] 9.5 Validate rate limit enforcement
    - **Property 5: Rate limit enforcement** — **Validates: Requirements 6.4, 6.5**
    - Superar un umbral y confirmar 429 + evento; confirmar que la app no reimplementa el límite de borde
  - [ ] 9.6 Validate HTTPS-only
    - **Property 6: HTTPS-only** — **Validates: Requirements 1.4**
    - Confirmar que ningún endpoint acepta tráfico no cifrado

- [ ] 10. Checkpoint — multi-region infrastructure deployed and validated — **Fase 2**
  - Asegurar que todas las validaciones de despliegue (tarea 9) pasan en la cuenta AWS real; consultar al usuario si surgen dudas.

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

- **IaC tool**: **AWS CDK (Python)** bajo `infra/`. No hay cambios en el código de aplicación Python.
- **Fase 1 (single-region) — hecho o casi**: tareas 1.1, 3.1, 4.1–4.3, 5.3, 7.1 completas; 1.2, 4.4, 5.1, 5.2, 8.1 parciales (la parte single-region está, falta la extensión multi-region o el detalle indicado).
- **Fase 2 (multi-region) — pendiente**: tareas 1.3, 2.x, 3.2, 3.3, 6.x, 7.2, 8.2, y toda la 9/10. Dependen de fijar los parámetros abiertos y, para la 9/10, de una cuenta AWS con despliegue real.
- Task 1 (scaffolding + config) es la base de todo y ya existe.
- Tasks 2 (Global Table), 3 (Cognito+ASF), 4 (WAF) y 5 (API Gateway) son los stacks regionales; dependen de task 1.
- Task 6 (Route 53 global stack) depende de endpoints regionales (task 5) y del `GET /health` (5.3, ya hecho).
- Task 7 (allow-lists) depende de task 3 (pools/clients).
- Task 8 depende de los recursos que monitoriza.
- Task 9/10 dependen de todo desplegado y corren contra la cuenta AWS real.
- **Parámetros abiertos** (en `TODO.md`): regiones concretas, política de enrutamiento por defecto (latency vs failover) y RTO/RPO. Afectan a 1.2, 6.2 y 6.4 pero no bloquean la Fase 1.
