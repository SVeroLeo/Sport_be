# TODO

Lista de pendientes.

- [ ] Revisar el requirements.md de la spec `aws-multiregion-infrastructure` y decidir ajustes: fijar las regiones concretas, elegir latency-based vs failover como política por defecto, y definir los valores de RTO/RPO.
- [ ] CDK: agregar custom domain para la API (Route 53 hosted zone + certificado ACM + base path mapping en API Gateway). Hoy la API queda en el endpoint `execute-api` por defecto.
- [ ] Implementar la lógica real del handler post-confirmation de Cognito (`src/interfaces/http/handlers/post_confirmation_handler.py`): crear User (status "active") + TenantMembership + Member + rol "viewer" de forma atómica en DynamoDB (Requirement 3.2), reutilizando repositorios/use case en una sola transacción, con tests. Hoy es un placeholder que solo loguea el evento.
- [ ] Observabilidad CDK: suscribir un endpoint (email/Slack/PagerDuty) al SNS topic de alarmas (`AlarmTopicArn`) por entorno. Hoy el topic existe pero no tiene suscripciones.
