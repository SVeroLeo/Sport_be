# Account Management — AWS CDK Infrastructure

CDK (Python) that deploys the Account Management backend for two environments
(`dev` and `prod`) in a single region: **sa-east-1 (Sao Paulo)**.

Multi-region concerns (Route 53 failover, DynamoDB Global Tables, WAF, Cognito
ASF) are tracked in the `.kiro/specs/aws-multiregion-infrastructure` spec and are
intentionally out of scope here.

## What it provisions (per environment)

- DynamoDB single table (`PK`/`SK` + `GSI1` + `GSI2`), pay-per-request.
- Cognito User Pool + app client (RS256 tokens, 1h access / 7d refresh).
- Four Lambda functions (auth, registration, account-types, members) packaged
  from `../src`, Python 3.12.
- REST API Gateway wiring all routes + a public `GET /health`.

The Lambdas receive `COGNITO_ISSUERS` / `COGNITO_CLIENT_IDS` derived from the
created User Pool — matching the backend's RS256/JWKS, tenant-agnostic design.
No JWT secret is used.

## How Lambda code is bundled

The app depends on `pydantic` and `PyJWT[crypto]`, which are not in the Lambda
runtime. Bundling (`lambda_assets/lambda_bundling.py`) installs them into the
deployment asset alongside `../src`, targeting the **Linux x86_64** Lambda
platform via pip download flags (`--platform manylinux2014_x86_64
--only-binary=:all:`).

This means **no Docker is required** on Windows/macOS/Linux: pip downloads the
correct Linux wheels (including native ones like `cryptography`) without
building anything on the host. If local bundling ever fails, CDK falls back to
Docker with the Lambda build image.

Runtime deps live in `lambda-requirements.txt` (kept in sync with the non-boto
dependencies in the root `pyproject.toml`).

## Observability (CloudWatch + SNS)

Each environment provisions an SNS alarm topic (`AlarmTopicArn` output) and
CloudWatch alarms wired to it:

- Per Lambda (auth, registration, account-types, members, post-confirmation):
  errors and throttles.
- API Gateway: 5XX count and p99 latency.
- DynamoDB: user errors and system errors (scoped to the operations the app uses).

The topic has no subscriptions by default — subscribe an email/Slack/PagerDuty
endpoint to `AlarmTopicArn` per environment (tracked in `TODO.md`).

## Cognito Post Confirmation trigger

The User Pool has a Post Confirmation Lambda trigger
(`interfaces.http.handlers.post_confirmation_handler.handler`). Per Requirement
3.2, on email confirmation it should create the User (status "active"),
TenantMembership, Member and default "viewer" Role atomically in DynamoDB.

Today the handler is a **placeholder** that logs the event and returns it so the
sign-up flow completes; the atomic record creation is a TODO (see `TODO.md`).

## WAF (edge protection)

Each environment attaches a **regional** WAF Web ACL to the API Gateway stage
(`lambda_assets/api_waf.py`) with:

- AWS managed common rule set and known-bad-inputs rule set.
- A rate-based rule (per source IP): dev 2000 / prod 10000 requests per 5-minute
  window before an IP is temporarily blocked.

This is the single-region subset of the WAF design in the
`aws-multiregion-infrastructure` spec.

## Tests

CDK unit tests live in `tests/` and assert on the synthesized CloudFormation
template (via `aws_cdk.assertions`), with Lambda bundling stubbed so they run
fast and offline:

```powershell
cd infra
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest tests -o addopts="" -o testpaths="tests"
```

They cover the table + GSIs, the five Python Lambdas and their env, the Cognito
user pool + post-confirmation trigger, the API routes, the WAF Web ACL, the SNS
topic and CloudWatch alarms, and guard against a `JWT_SECRET` leaking in.

## Prerequisites

- AWS CDK v2 CLI (or use `npx aws-cdk@2 ...`): `npm install -g aws-cdk`
- Python 3.11+ and a virtualenv for the CDK deps:

```powershell
cd infra
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

- Bootstrap the account/region once:

```powershell
cdk bootstrap aws://<ACCOUNT_ID>/sa-east-1
```

## Usage

```powershell
cdk synth                       # synthesize both dev and prod
cdk deploy -c env=dev           # deploy only dev
cdk deploy -c env=prod          # deploy only prod
cdk deploy -c env=all           # deploy both
```

## TODO

- Custom domain (Route 53 hosted zone + ACM certificate + API mapping) — left as
  a TODO per project decision; the API is currently exposed on the default
  `execute-api` URL.
- Multi-region hardening — see the `aws-multiregion-infrastructure` spec.


