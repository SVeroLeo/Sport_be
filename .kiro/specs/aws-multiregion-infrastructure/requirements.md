# Requirements Document

## Introduction

Este documento define los requisitos de la **infraestructura AWS multi-región** que soporta el backend de Account Management. El servicio de aplicación (Python, Clean Architecture) ya verifica tokens con RS256/JWKS por issuer y resuelve el tenant activo desde DynamoDB en cada request. Esta spec cubre las piezas de plataforma que hacen ese diseño operable de forma resiliente y segura en múltiples regiones: enrutamiento y failover de DNS (Route 53), protección de borde y anti-abuso (AWS WAF), endurecimiento de identidad (Cognito Advanced Security Features), replicación de datos entre regiones (DynamoDB Global Tables) y la ubicación autoritativa del rate limiting.

Esta spec es **infraestructura como código (IaC)**. No modifica la lógica de negocio en Python. Su implementación queda **pendiente hasta disponer de una cuenta AWS**; el objetivo ahora es acordar requisitos y diseño para poder ejecutar sin ambigüedad cuando la cuenta esté lista.

## Glossary

- **System**: La plataforma de infraestructura AWS multi-región que aloja y protege el backend de Account Management.
- **Region-local Pool**: Una réplica de Cognito User Pool desplegada en una región concreta; cada una tiene su propio `iss`, `kid` y JWKS.
- **Issuer (`iss`)**: URL del emisor del token, con forma `https://cognito-idp.{region}.amazonaws.com/{userPoolId}`; identifica de forma única el pool que firmó el token.
- **Health Check**: Comprobación periódica de Route 53 sobre el endpoint regional del API para determinar si una región está sana.
- **Primary Region / Secondary Region**: Regiones designadas para failover activo-pasivo, o regiones equivalentes en un esquema latency-based.
- **WAF Web ACL**: Conjunto de reglas de AWS WAF asociado al distribuidor de borde o al API Gateway regional.
- **ASF**: Cognito Advanced Security Features (detección de credenciales comprometidas, autenticación adaptativa, señales de riesgo).
- **Global Table**: Tabla de DynamoDB replicada multi-región (multi-active) que mantiene consistencia eventual entre réplicas regionales.
- **Rate Limiting**: Límite de tasa de peticiones aplicado en el borde (WAF rate-based rules) y/o en API Gateway (usage plans/throttling).
- **RPO / RTO**: Recovery Point Objective / Recovery Time Objective; tolerancia de pérdida de datos y de tiempo de recuperación ante caída regional.

## Requirements

### Requirement 1: Enrutamiento DNS multi-región (Route 53)

**User Story:** As a platform operator, I want DNS-based routing across regions, so that user requests reach a healthy regional endpoint with low latency.

#### Acceptance Criteria

1. THE System SHALL exponer el API bajo un nombre de dominio estable gestionado en Route 53 (hosted zone) con registros alias hacia los endpoints regionales del API.
2. THE System SHALL soportar una política de enrutamiento configurable entre **latency-based routing** (dirigir a la región de menor latencia) y **failover routing** (activo-pasivo).
3. WHEN se usa failover routing, THE System SHALL designar una Primary Region y al menos una Secondary Region.
4. THE System SHALL usar únicamente HTTPS; los certificados TLS SHALL gestionarse por región (ACM) para los endpoints regionales.
5. THE System SHALL publicar el dominio con un TTL de DNS acotado (por ejemplo, 60 s o menos) para que el failover propague rápido.

### Requirement 2: Health checks y failover automático

**User Story:** As a platform operator, I want automatic failover when a region becomes unhealthy, so that the service stays available.

#### Acceptance Criteria

1. THE System SHALL configurar health checks de Route 53 contra un endpoint de salud del API en cada región.
2. WHEN un health check de una región falla de forma sostenida (según umbral configurable), THE System SHALL dejar de enrutar tráfico a esa región.
3. WHEN una región previamente no sana vuelve a pasar sus health checks, THE System SHALL reincorporarla al enrutamiento automáticamente.
4. THE System SHALL definir objetivos explícitos de RTO y RPO para el failover regional y documentarlos.
5. IF todas las regiones están no sanas, THEN THE System SHALL devolver una respuesta de error controlada en lugar de enrutar a un endpoint caído.

### Requirement 3: Protección de borde y anti-abuso (AWS WAF)

**User Story:** As a security owner, I want edge protection against common web attacks and abuse, so that the backend is shielded before requests reach application logic.

#### Acceptance Criteria

1. THE System SHALL asociar un WAF Web ACL a la capa de entrada del API en cada región.
2. THE System SHALL incluir reglas administradas de AWS (por ejemplo, el conjunto de reglas comunes y el de detección de entradas maliciosas conocidas).
3. THE System SHALL definir reglas rate-based que limiten peticiones por IP de origen dentro de una ventana de tiempo configurable.
4. WHEN una petición coincide con una regla de bloqueo, THE System SHALL bloquearla en el borde y registrar el evento.
5. THE System SHALL enviar los logs de WAF a un destino de observabilidad (por ejemplo, logs centralizados) para auditoría.
6. THE System SHALL permitir una lista de excepciones (allow-list) para orígenes de confianza cuando sea necesario.

### Requirement 4: Endurecimiento de identidad (Cognito ASF)

**User Story:** As a security owner, I want Cognito Advanced Security Features enabled, so that compromised credentials and risky sign-ins are detected and mitigated.

#### Acceptance Criteria

1. THE System SHALL habilitar Cognito Advanced Security Features en cada Region-local Pool.
2. THE System SHALL configurar autenticación adaptativa con acciones basadas en nivel de riesgo (permitir, exigir MFA, o bloquear).
3. WHEN Cognito detecta credenciales comprometidas, THE System SHALL aplicar la acción configurada (por ejemplo, bloquear el inicio de sesión).
4. THE System SHALL mantener la configuración de ASF **equivalente entre todas las regiones** para un comportamiento de seguridad uniforme.
5. THE System SHALL exportar los eventos de seguridad de Cognito a observabilidad para auditoría.

### Requirement 5: Replicación de datos entre regiones (DynamoDB Global Tables)

**User Story:** As a platform operator, I want user, tenant, membership and role data replicated across regions, so that the AuthGuard can resolve tenant and roles in whichever region serves the request.

#### Acceptance Criteria

1. THE System SHALL configurar la tabla única de DynamoDB como Global Table con réplicas en cada región donde exista un Region-local Pool.
2. THE System SHALL incluir en la replicación todos los tipos de ítem que el AuthGuard y los casos de uso leen en caliente (perfil de usuario con default_tenant_id, membresías, roles, tipos de cuenta).
3. THE System SHALL asumir consistencia eventual entre réplicas y documentar el impacto en flujos sensibles a la latencia de replicación (por ejemplo, registro seguido de login inmediato en otra región).
4. THE System SHALL preservar los GSIs de la tabla en todas las réplicas.
5. THE System SHALL definir la estrategia de resolución de conflictos por defecto (last-writer-wins) y documentar sus implicaciones.

### Requirement 6: Ubicación autoritativa del rate limiting

**User Story:** As a security owner, I want a clearly defined place where rate limiting is enforced, so that abuse controls are consistent and not duplicated ambiguously.

#### Acceptance Criteria

1. THE System SHALL definir el rate limiting de borde (por IP) en las reglas rate-based de WAF como primer nivel de defensa.
2. THE System SHALL definir límites por cliente/uso en API Gateway (usage plans / throttling) como segundo nivel cuando aplique.
3. THE System SHALL documentar explícitamente los límites acordados de negocio (por ejemplo, intentos de login por minuto por IP/email y registros por hora por IP) y el nivel donde se aplica cada uno.
4. WHEN se supera un límite, THE System SHALL responder con 429 (Too Many Requests) y registrar el evento.
5. THE System SHALL asegurar que la lógica de aplicación en Python **no** reimplemente el rate limiting de borde, evitando duplicación; cualquier límite de negocio no cubierto por WAF/API Gateway SHALL documentarse como excepción explícita.

### Requirement 7: Consistencia multi-región de la configuración de verificación de tokens

**User Story:** As a platform operator, I want the token issuer/client allow-lists to stay consistent with the deployed regional pools, so that RS256 verification works regardless of which region served the login.

#### Acceptance Criteria

1. THE System SHALL derivar la allow-list de issuers (`COGNITO_ISSUERS`) del conjunto de Region-local Pools desplegados.
2. THE System SHALL derivar la allow-list de client ids (`COGNITO_CLIENT_IDS`) de los app clients desplegados por región.
3. WHEN se agrega o elimina una región, THE System SHALL actualizar ambas allow-lists de forma que la verificación de tokens del backend siga siendo válida para todas las regiones activas.
4. THE System SHALL proveer estas allow-lists al backend vía configuración de entorno (sin secreto simétrico; no se usa JWT_SECRET).

### Requirement 8: Observabilidad y despliegue como IaC

**User Story:** As a platform operator, I want the multi-region infrastructure defined as code and observable, so that it can be reviewed, reproduced and monitored.

#### Acceptance Criteria

1. THE System SHALL definirse como infraestructura como código (por ejemplo, la herramienta IaC que adopte el proyecto) versionada en el repositorio.
2. THE System SHALL permitir desplegar la misma definición a múltiples regiones de forma parametrizada.
3. THE System SHALL emitir métricas y alarmas para: salud de health checks, tasa de bloqueos de WAF, eventos de riesgo de Cognito, latencia de replicación de DynamoDB y tasa de 429.
4. THE System SHALL documentar un runbook de failover manual como respaldo del failover automático.

## Out of Scope

- Cambios a la lógica de negocio en Python (ya implementada: RS256/JWKS + tenant-agnostic token).
- La creación de la cuenta AWS y credenciales; esta spec se implementará una vez la cuenta esté disponible.
- Diseño de frontend (proyecto separado).
