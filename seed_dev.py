"""Seed script: inserts a 'talar' tenant into the dev DynamoDB table."""

import boto3
from datetime import datetime, timezone

TABLE_NAME = "sport-account-management-dev"
REGION = "sa-east-1"
PROFILE = "talar"

session = boto3.Session(profile_name=PROFILE, region_name=REGION)
dynamodb = session.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

TENANT_ID = "00000000-0000-0000-0000-000000000001"
now = datetime.now(timezone.utc).isoformat()

# Insert tenant record
table.put_item(Item={
    "PK": f"TENANT#{TENANT_ID}",
    "SK": "METADATA",
    "tenant_id": TENANT_ID,
    "name": "Talar Sport",
    "status": "active",
    "plan": "basic",
    "allow_self_registration": True,
    "default_account_type": None,
    "created_at": now,
})
print(f"✅  Tenant '{TENANT_ID}' creado")
