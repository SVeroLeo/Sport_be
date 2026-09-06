# TODO

## Estado actual: infraestructura single-region

La infraestructura AWS se despliega hoy como **CDK en Python** (`infra/`) en una
**sola región: `sa-east-1` (São Paulo)**, para los entornos `dev` y `prod`. Es
el punto de partida para dar los primeros pasos en AWS. Guía de despliegue para
quien sube a AWS: `infra/DEPLOYMENT.md`.

Ya provisiona (por entorno): tabla DynamoDB single-table (PK/SK + GSI1 + GSI2),
Cognito User Pool + app client (RS256, sin ASF), 5 Lambdas, API Gateway con
todas las rutas + `GET /health` + throttling, WAF regional (reglas administradas
+ rate-based por IP), y observabilidad (SNS topic + alarmas CloudWatch).

El paso a **multi-región** está planificado y rastreado en el spec
`.kiro/specs/aws-multiregion-infrastructure` (Fase 2). Los ítems de abajo separan
lo que aplica ya (single-region) de lo que llega con multi-región.

## Pendientes — single-region (aplican ya)

- [x] Implementar la lógica real del handler post-confirmation de Cognito
  (`src/interfaces/http/handlers/post_confirmation_handler.py`): crear User
  (status "active") + TenantMembership + Member + rol "viewer" de forma atómica
  en DynamoDB (Requirement 3.2), reutilizando repositorios/use case en una sola
  transacción, con tests. ✅ Implementado y testeado (9 unit tests).
- [ ] Observabilidad CDK: suscribir un endpoint (email/Slack/PagerDuty) al SNS
  topic de alarmas (`AlarmTopicArn`) por entorno. Hoy el topic existe pero no
  tiene suscripciones. (Ver `infra/DEPLOYMENT.md`, sección post-despliegue.)

## Pendientes — transición a multi-región (Fase 2)

> Antes de empezar la Fase 2 hay que **fijar los parámetros abiertos** (afectan a
> las tareas 1.2, 6.2 y 6.4 del spec):
- [ ] Fijar las **regiones concretas** adicionales a `sa-east-1`.
- [ ] Elegir la **política de enrutamiento por defecto**: latency-based vs
  failover (activo-pasivo).
- [ ] Definir los valores objetivo de **RTO / RPO** para el failover regional.

Trabajo de infraestructura multi-región (detalle en el `tasks.md` del spec):

- [ ] Custom domain para la API: Route 53 hosted zone + certificado ACM + base
  path mapping en API Gateway. Hoy la API queda en el endpoint `execute-api`
  por defecto (single-region). (Spec tarea 5.1 / 6.1)
- [ ] DynamoDB Global Tables: convertir la tabla única en Global Table con
  réplica por región. (Spec tarea 2.x)
- [ ] Cognito ASF (Advanced Security Features) + pools por región y consistencia
  de las allow-lists de verificación de tokens cross-region. (Spec tareas 3.2,
  3.3, 7.2)
- [ ] WAF por región: logging a observabilidad central + allow-list de orígenes
  de confianza. (Spec tarea 4.4)
- [ ] Route 53: health checks por región + failover automático + error
  controlado si todas las regiones caen. (Spec tarea 6.x)
- [ ] Observabilidad multi-región: alarmas de health checks, tasa de bloqueos de
  WAF, eventos de riesgo de Cognito, latencia de replicación de DynamoDB y tasa
  de 429; runbook de failover manual. (Spec tareas 8.1, 8.2)
- [ ] Validación post-deploy en cuenta AWS real (portabilidad de tokens
  cross-region, consistencia de allow-lists, failover, convergencia de réplicas,
  rate limiting, HTTPS-only). (Spec tareas 9 y 10)
