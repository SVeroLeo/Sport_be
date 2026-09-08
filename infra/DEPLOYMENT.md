# Deployment Guide — Account Management (single region)

Esta guía es para la persona que **sube la infraestructura a AWS**. No necesitas
conocer CDK ni el código: solo ejecutar los comandos de abajo con credenciales
de la cuenta AWS de destino.

- **Herramienta**: AWS CDK v2 (Python).
- **Región**: `sa-east-1` (São Paulo). Single-region por ahora; el paso a
  multi-región está planificado (ver `../TODO.md` y el spec
  `.kiro/specs/aws-multiregion-infrastructure`).
- **Entornos**: `dev` y `prod`, stacks independientes.
- **Docker**: no se necesita. El bundling de las Lambdas baja wheels de Linux
  con pip automáticamente.

> Cómo funciona la "subida": con CDK no se sube un archivo a mano. El comando
> `cdk deploy` **sintetiza** la plantilla CloudFormation, **empaqueta** el código
> de las Lambdas y **sube** todo a la cuenta AWS creando/actualizando los stacks
> de CloudFormation. Tú solo ejecutas el comando; CDK hace la subida.

---

## 1. Requisitos previos (una sola vez por máquina)

1. **Node.js** (para el CLI de CDK vía `npx`) y **Python 3.11+**.
2. **AWS CLI** configurado con credenciales de la cuenta destino:

   ```powershell
   aws configure
   # o, si usas SSO / perfiles:
   $env:AWS_PROFILE = "mi-perfil"
   ```

   Verifica que apuntas a la cuenta correcta:

   ```powershell
   aws sts get-caller-identity
   ```

3. **Entorno Python del proyecto CDK**:

   ```powershell
   cd infra
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. **Secrets de social login** (una sola vez por cuenta+región, **antes** del
   primer deploy). El stack referencia tres secretos de AWS Secrets Manager por
   nombre. Si no existen, `cdk deploy` falla. Créalos con las credenciales
   reales de las apps de Google/Facebook y un secreto HMAC aleatorio:

   ```powershell
   # Google OAuth (client_id + client_secret del proyecto de Google Cloud)
   aws secretsmanager create-secret --name social/google --region sa-east-1 `
     --secret-string '{"client_id":"<GOOGLE_CLIENT_ID>","client_secret":"<GOOGLE_CLIENT_SECRET>"}'

   # Facebook Login (client_id + client_secret de la app de Meta)
   aws secretsmanager create-secret --name social/facebook --region sa-east-1 `
     --secret-string '{"client_id":"<FB_APP_ID>","client_secret":"<FB_APP_SECRET>"}'

   # Secreto HMAC para firmar el token `state` (CSRF). Genera un valor aleatorio.
   aws secretsmanager create-secret --name social/state --region sa-east-1 `
     --secret-string '{"state_secret":"<VALOR_ALEATORIO_LARGO>"}'
   ```

   > Los secretos son **por región**: si despliegas `dev` y `prod` en la misma
   > región comparten los mismos tres secretos. Para regiones distintas hay que
   > recrearlos en cada una.
   >
   > En la consola de Google/Facebook registra como *Authorized redirect URI* la
   > URL del Hosted UI de Cognito:
   > `https://sport-<env>.auth.sa-east-1.amazoncognito.com/oauth2/idpresponse`.

## 2. Bootstrap de la cuenta/región (una sola vez por cuenta+región)

CDK necesita recursos base (bucket de assets, roles) en la cuenta/región. Se
hace una única vez:

```powershell
# Reemplaza <ACCOUNT_ID> por el id numérico de la cuenta (aws sts get-caller-identity)
npx aws-cdk@2 bootstrap aws://<ACCOUNT_ID>/sa-east-1
```

## 3. Revisar antes de desplegar (recomendado)

```powershell
# Ver qué se va a crear/cambiar sin aplicar nada:
npx aws-cdk@2 diff -c env=dev
```

## 4. Desplegar

```powershell
# Solo dev:
npx aws-cdk@2 deploy -c env=dev

# Solo prod:
npx aws-cdk@2 deploy -c env=prod

# Ambos:
npx aws-cdk@2 deploy -c env=all
```

Para CI o despliegues no interactivos (sin pedir confirmación de cambios de
seguridad IAM):

```powershell
npx aws-cdk@2 deploy -c env=dev --require-approval never
```

## 5. Salidas (outputs) tras el deploy

Al terminar, CloudFormation imprime los outputs del stack. Anótalos, los
necesita el frontend / backend:

| Output              | Para qué sirve                                             |
|---------------------|------------------------------------------------------------|
| `ApiUrl`            | URL base del API (endpoint `execute-api`, HTTPS).          |
| `TableName`         | Nombre de la tabla DynamoDB.                               |
| `UserPoolId`        | Id del User Pool de Cognito.                               |
| `UserPoolClientId`  | Id del app client (para login).                            |
| `CognitoIssuer`     | Issuer RS256 (`https://cognito-idp.sa-east-1...`).         |
| `AlarmTopicArn`     | SNS topic de alarmas (suscribe un email/Slack aquí).       |

También puedes recuperarlos luego:

```powershell
aws cloudformation describe-stacks --stack-name AccountManagement-dev `
  --query "Stacks[0].Outputs" --region sa-east-1
```

## 6. Post-despliegue

- **Suscribir alertas**: el `AlarmTopicArn` no tiene destinatarios por defecto.
  Suscribe un email (o Slack/PagerDuty) para recibir las alarmas:

  ```powershell
  aws sns subscribe --topic-arn <AlarmTopicArn> --protocol email `
    --notification-endpoint alertas@tu-dominio.com --region sa-east-1
  ```

- **Health check**: comprueba que el API responde:

  ```powershell
  curl <ApiUrl>health
  # Espera: {"status":"ok"}
  ```

## Qué se crea (single region)

Por cada entorno (`dev` / `prod`) en `sa-east-1`:

- DynamoDB single-table (`PK`/`SK` + `GSI1` + `GSI2`), pay-per-request.
- Cognito User Pool + app client (tokens RS256; 1h access / 7d refresh).
- Social login: identity providers de Google y Facebook, dominio Hosted UI
  (`https://sport-<env>.auth.sa-east-1.amazoncognito.com`) y grant OAuth
  (authorization code + scopes openid/email/profile). Credenciales tomadas de
  los secretos `social/google` y `social/facebook` (ver paso 1.4).
- 6 Lambdas (auth, registration, account-types, members, post-confirmation y
  oauth para `/auth/social/*`), Python 3.12, empaquetadas desde `../src`.
- REST API Gateway con todas las rutas + `/auth/social/{proxy+}` (social login)
  + `GET /health` público, con throttling de stage.
- WAF Web ACL regional (reglas administradas AWS + rate-based por IP).
- SNS topic de alarmas + alarmas CloudWatch (Lambdas, API, DynamoDB).

No se usa `JWT_SECRET`: la verificación es RS256/JWKS con allow-lists
(`COGNITO_ISSUERS` / `COGNITO_CLIENT_IDS`) derivadas del pool creado.

## Rollback / borrado

```powershell
# Elimina un entorno completo (dev destruye la tabla; prod la retiene):
npx aws-cdk@2 destroy -c env=dev
```

> En `prod` los recursos con estado (tabla, user pool) tienen política
> `RETAIN`, así que un `destroy` no borra los datos: quedan huérfanos en la
> cuenta y deben eliminarse manualmente si de verdad se quieren borrar.

## Próximo paso: multi-región

Esta base single-region es el punto de partida. El endurecimiento multi-región
(DynamoDB Global Tables, Cognito ASF, WAF por región, Route 53 con failover y
health checks, consistencia de allow-lists cross-region) está planificado en el
spec `.kiro/specs/aws-multiregion-infrastructure` y en `../TODO.md`.
