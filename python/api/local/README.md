# Local dev server (native login + register)

Runs the real Lambda handlers in-process against **moto-mocked** AWS
(Cognito + DynamoDB) so the Angular frontend can hit
`http://localhost:8000/auth/*` without deploying to AWS.

> Dev tooling only. This module is never bundled into a Lambda and is not part
> of the production code path.

## Prerequisites

Install the dev dependencies (includes `moto`) from the repo root:

```powershell
python -m pip install -e ".[dev]"
```

## Run

From the `python/` directory:

```powershell
python -m api.local.local_server
```

You should see:

```
Mocked AWS ready — pool=... client=...
Default tenant seeded: Local Dev Institution (00000000-0000-4000-8000-000000000000)
Local BE listening on http://127.0.0.1:8000
```

Leave it running in its own terminal. Stop it with `Ctrl+C`.

## What it exposes

| Method | Path                    | Notes                                             |
| ------ | ----------------------- | ------------------------------------------------- |
| POST   | `/auth/register`        | Body `{ email, password }`. 201 on success.       |
| POST   | `/auth/login`           | Body `{ email, password }`. 200 with token set.   |
| POST   | `/auth/refresh`         | Body `{ refresh_token }`.                         |
| POST   | `/auth/logout`          | Body `{ access_token }`.                          |
| POST   | `/auth/forgot-password` | Body `{ email }`.                                 |
| GET    | `/health`               | Liveness check.                                   |

CORS is fully open (`Access-Control-Allow-Origin: *`), matching the deployed
API Gateway config, so the Angular dev server can call it from any localhost
port.

## Local-only convenience

- The register flow only needs `email` + `password`. `full_name` is derived
  from the email local-part and the tenant defaults to the seeded local tenant
  (`DEFAULT_TENANT_ID`), so no email verification or tenant selection is needed.
- After a successful register the user is auto-confirmed and their
  User / membership / role records are seeded via the real post-confirmation
  handler, so you can log in immediately (no verification email locally).

## Quick smoke test

```powershell
curl.exe -X POST http://127.0.0.1:8000/auth/register -H "Content-Type: application/json" -d '{\"email\":\"jane.doe@example.com\",\"password\":\"SecurePass1\"}'
curl.exe -X POST http://127.0.0.1:8000/auth/login    -H "Content-Type: application/json" -d '{\"email\":\"jane.doe@example.com\",\"password\":\"SecurePass1\"}'
```

The login response returns `access_token`, `id_token`, `refresh_token`,
`expires_in`, `default_tenant_id`, and `roles` — exactly the shape the frontend
`AuthService` expects.

## Configuration (env vars, all optional)

| Var          | Default              | Purpose                          |
| ------------ | -------------------- | -------------------------------- |
| `LOCAL_HOST` | `127.0.0.1`          | Bind address.                    |
| `LOCAL_PORT` | `8000`               | Bind port (FE expects `8000`).   |
| `REGION`     | `us-east-1`          | Mocked AWS region.               |
| `TABLE_NAME` | `sport-local-table`  | Mocked DynamoDB table name.      |

> Data lives entirely in memory and resets every time you restart the server.
