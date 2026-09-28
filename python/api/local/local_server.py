"""Local development server for the native auth endpoints (login + register).

Runs the real AWS Lambda handlers in-process against moto-mocked AWS services
(Cognito + DynamoDB), so the Angular frontend can exercise the native
login/register flow against ``http://localhost:8000`` without deploying to AWS.

This module is a DEVELOPMENT TOOL ONLY — it is never bundled into a Lambda and
is not part of the production code path. It deliberately depends on ``moto``
(a dev dependency) and wires up throwaway in-memory AWS resources on startup.

What it does on startup:
1. Starts ``moto``'s ``mock_aws()`` so every boto3 call is served in-memory.
2. Creates the DynamoDB single-table (PK/SK + GSI1/GSI2) and seeds one default
   tenant that allows self-registration.
3. Creates a Cognito User Pool + App Client (admin password auth flow) and
   exports the resulting env vars the composition root reads.
4. Serves HTTP, translating each request into an API Gateway Lambda proxy event
   and dispatching to the real handler (auth / registration).

Local-only convenience behavior:
- After a successful ``POST /auth/register`` the Cognito user is auto-confirmed
  (there is no real verification email locally) and the real Cognito
  Post-Confirmation handler is invoked with a synthesized event, so the User /
  membership / role records land in DynamoDB and the user can log in
  immediately.
- CORS is fully open (mirrors the API Gateway ``ALL_ORIGINS`` config) so the
  Angular dev server can call it from any localhost port.

Run it with::

    python -m api.local.local_server

Requires the dev dependencies (``pip install -e ".[dev]"`` from the repo root,
which includes ``moto[dynamodb,cognitoidp]``).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

logger = logging.getLogger("local_server")

# ──── Configuration ───────────────────────────────────────────────────────────

HOST = os.environ.get("LOCAL_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCAL_PORT", "8000"))
REGION = os.environ.get("REGION", "us-east-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "sport-local-table")

# A fixed default tenant so registers land in a known, self-registration-enabled
# tenant without the frontend having to send a tenant_id.
DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000000"
DEFAULT_TENANT_NAME = "Local Dev Institution"

# A password that satisfies the Cognito policy (upper, lower, digit, symbol),
# used only for the local seed user below.
_SEED_ENABLED = os.environ.get("LOCAL_SEED_USER", "0") == "1"


# ──── moto / AWS resource provisioning ─────────────────────────────────────────


def _create_table() -> None:
    """Create the single-table DynamoDB schema (PK/SK + GSI1 + GSI2)."""
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.meta.client.get_waiter("table_exists").wait(TableName=TABLE_NAME)


def _seed_default_tenant() -> None:
    """Seed the default tenant so self-registration succeeds locally."""
    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    table.put_item(
        Item={
            "PK": f"TENANT#{DEFAULT_TENANT_ID}",
            "SK": "METADATA",
            "tenant_id": DEFAULT_TENANT_ID,
            "name": DEFAULT_TENANT_NAME,
            "plan": "local",
            "status": "active",
            "allow_self_registration": True,
            "default_account_type": "usuario",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _create_cognito_pool() -> tuple[str, str]:
    """Create a Cognito User Pool + App Client and return (pool_id, client_id)."""
    import boto3

    client = boto3.client("cognito-idp", region_name=REGION)
    pool = client.create_user_pool(
        PoolName="LocalPool",
        Policies={
            "PasswordPolicy": {
                "MinimumLength": 8,
                "RequireUppercase": True,
                "RequireLowercase": True,
                "RequireNumbers": True,
                "RequireSymbols": False,
            }
        },
        AutoVerifiedAttributes=["email"],
        Schema=[
            {
                "Name": "email",
                "AttributeDataType": "String",
                "Required": True,
                "Mutable": True,
            },
            {
                "Name": "name",
                "AttributeDataType": "String",
                "Required": False,
                "Mutable": True,
            },
        ],
    )
    pool_id = pool["UserPool"]["Id"]

    app_client = client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName="LocalClient",
        ExplicitAuthFlows=[
            "ALLOW_ADMIN_USER_PASSWORD_AUTH",
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH",
        ],
    )
    client_id = app_client["UserPoolClient"]["ClientId"]
    return pool_id, client_id


def _bootstrap_aws() -> tuple[str, str]:
    """Provision all mocked AWS resources and export the env vars handlers read.

    Returns:
        The (pool_id, client_id) of the created Cognito pool/client.
    """
    _create_table()
    _seed_default_tenant()
    pool_id, client_id = _create_cognito_pool()

    # The composition root and dynamodb client read these on first use.
    os.environ["TABLE_NAME"] = TABLE_NAME
    os.environ["REGION"] = REGION
    os.environ["AWS_DEFAULT_REGION"] = REGION
    os.environ["COGNITO_USER_POOL_ID"] = pool_id
    os.environ["COGNITO_CLIENT_ID"] = client_id
    os.environ["COGNITO_ISSUERS"] = (
        f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}"
    )
    os.environ["COGNITO_CLIENT_IDS"] = client_id
    os.environ["DEFAULT_TENANT_ID"] = DEFAULT_TENANT_ID
    # moto does not require real credentials, but boto3 needs *something*.
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")

    return pool_id, client_id


# ──── Local post-registration provisioning ─────────────────────────────────────


def _auto_confirm_and_provision(pool_id: str, email: str, cognito_sub: str) -> None:
    """Confirm the freshly-registered user and seed their DynamoDB records.

    Locally there is no email verification and no Cognito Post-Confirmation
    trigger, so this mirrors that flow: it admin-confirms the sign-up and then
    invokes the REAL post-confirmation handler with a synthesized event, which
    creates the User / TenantMembership / Member / Role records exactly as
    production would.
    """
    import boto3

    client = boto3.client("cognito-idp", region_name=REGION)
    try:
        client.admin_confirm_sign_up(UserPoolId=pool_id, Username=email)
    except Exception:  # noqa: BLE001 - best-effort in local dev
        logger.exception("admin_confirm_sign_up failed for %s", email)

    # Mark email as verified so admin auth does not treat the account as pending.
    try:
        client.admin_update_user_attributes(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=[{"Name": "email_verified", "Value": "true"}],
        )
    except Exception:  # noqa: BLE001
        logger.exception("admin_update_user_attributes failed for %s", email)

    from api.registration import postConfirmationHandler

    event = {
        "triggerSource": "PostConfirmation_ConfirmSignUp",
        "request": {
            "userAttributes": {
                "sub": cognito_sub,
                "email": email,
                "name": email.split("@")[0],
                "custom:tenant_id": DEFAULT_TENANT_ID,
                "custom:account_type": "usuario",
            }
        },
    }
    try:
        postConfirmationHandler.handler(event, None)
    except Exception:  # noqa: BLE001
        logger.exception("post-confirmation provisioning failed for %s", email)


def _cognito_sub_for(pool_id: str, email: str) -> str:
    """Look up the Cognito sub for a just-registered user (best effort)."""
    import boto3

    client = boto3.client("cognito-idp", region_name=REGION)
    try:
        user = client.admin_get_user(UserPoolId=pool_id, Username=email)
    except Exception:  # noqa: BLE001
        return ""
    for attr in user.get("UserAttributes", []):
        if attr.get("Name") == "sub":
            return attr.get("Value", "")
    return user.get("Username", "")


# ──── HTTP <-> Lambda proxy translation ────────────────────────────────────────


def _make_event(method: str, path: str, body: str) -> dict[str, Any]:
    """Build a minimal API Gateway Lambda proxy event from an HTTP request."""
    return {
        "httpMethod": method,
        "resource": path,
        "path": path,
        "headers": {"Content-Type": "application/json"},
        "body": body or None,
        "isBase64Encoded": False,
    }


class _Router:
    """Dispatches HTTP requests to the real Lambda handlers."""

    def __init__(self, pool_id: str) -> None:
        self._pool_id = pool_id

    def dispatch(self, method: str, path: str, body: str) -> tuple[int, dict[str, str], str]:
        """Route a request and return (status_code, headers, body)."""
        from api.auth import authHandler
        from api.registration import registrationHandler

        event = _make_event(method, path, body)

        if path.endswith("/auth/register"):
            result = registrationHandler.handler(event, None)
            self._maybe_provision_after_register(result, body)
            return _unpack(result)

        # All other /auth/* routes are served by the auth handler.
        if "/auth/" in path or path.endswith("/auth"):
            result = authHandler.handler(event, None)
            return _unpack(result)

        return 404, {}, json.dumps({"error": "Route not found"})

    def _maybe_provision_after_register(
        self, result: dict[str, Any], request_body: str
    ) -> None:
        """After a 201 register, auto-confirm + seed records so login works."""
        if int(result.get("statusCode", 500)) != 201:
            return
        try:
            payload = json.loads(request_body or "{}")
            email = payload.get("email", "")
        except (json.JSONDecodeError, TypeError):
            return
        if not email:
            return
        cognito_sub = _cognito_sub_for(self._pool_id, email)
        if not cognito_sub:
            # Fall back to the sub returned in the register response body.
            try:
                cognito_sub = json.loads(result.get("body") or "{}").get("user_id", "")
            except (json.JSONDecodeError, TypeError):
                cognito_sub = ""
        if cognito_sub:
            _auto_confirm_and_provision(self._pool_id, email, cognito_sub)


def _unpack(result: dict[str, Any]) -> tuple[int, dict[str, str], str]:
    """Convert a Lambda proxy response dict into (status, headers, body)."""
    status = int(result.get("statusCode", 500))
    headers = dict(result.get("headers") or {})
    body = result.get("body")
    if not isinstance(body, str):
        body = json.dumps(body) if body is not None else ""
    return status, headers, body


# ──── HTTP server ───────────────────────────────────────────────────────────


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}


def _build_handler_class(router: _Router) -> type[BaseHTTPRequestHandler]:
    """Build a request handler class bound to the given router."""

    class LocalRequestHandler(BaseHTTPRequestHandler):
        server_version = "SportLocalDev/1.0"

        def _write(self, status: int, headers: dict[str, str], body: str) -> None:
            self.send_response(status)
            for key, value in {**_CORS_HEADERS, **headers}.items():
                self.send_header(key, value)
            encoded = body.encode("utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_OPTIONS(self) -> None:  # noqa: N802 - required name
            self.send_response(204)
            for key, value in _CORS_HEADERS.items():
                self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 - required name
            if self.path.rstrip("/").endswith("/health"):
                self._write(200, {"Content-Type": "application/json"}, json.dumps({"status": "ok"}))
                return
            self._write(404, {"Content-Type": "application/json"}, json.dumps({"error": "Not found"}))

        def do_POST(self) -> None:  # noqa: N802 - required name
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                status, headers, body = router.dispatch("POST", self.path, raw)
            except Exception:  # noqa: BLE001 - never crash the dev server
                logger.exception("Unhandled error dispatching %s", self.path)
                status, headers, body = (
                    500,
                    {"Content-Type": "application/json"},
                    json.dumps({"error": "Internal server error"}),
                )
            self._write(status, headers, body)

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

    return LocalRequestHandler


def main() -> None:
    """Bootstrap mocked AWS, then serve the auth endpoints until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        from moto import mock_aws
    except ImportError:  # pragma: no cover - dev-dependency guard
        raise SystemExit(
            "moto is not installed. Install dev dependencies from the repo root:\n"
            '    python -m pip install -e ".[dev]"'
        )

    mock = mock_aws()
    mock.start()
    try:
        pool_id, client_id = _bootstrap_aws()
        logger.info("Mocked AWS ready — pool=%s client=%s", pool_id, client_id)
        logger.info("Default tenant seeded: %s (%s)", DEFAULT_TENANT_NAME, DEFAULT_TENANT_ID)

        router = _Router(pool_id)
        handler_class = _build_handler_class(router)
        httpd = ThreadingHTTPServer((HOST, PORT), handler_class)
        logger.info("Local BE listening on http://%s:%d", HOST, PORT)
        logger.info("Endpoints: POST /auth/register, POST /auth/login (+ refresh/logout/forgot-password)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down local server")
        finally:
            httpd.server_close()
    finally:
        mock.stop()


if __name__ == "__main__":
    main()
