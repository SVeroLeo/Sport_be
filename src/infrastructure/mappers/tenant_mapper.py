"""Tenant entity ↔ DynamoDB item mapper.

Maps Tenant entities to/from DynamoDB items using the single table design:
- PK=TENANT#{tenant_id}, SK=METADATA
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from domain.entities.tenant import Tenant
from domain.value_objects.tenant_id import TenantId


def tenant_to_item(tenant: Tenant) -> dict[str, Any]:
    """Convert a Tenant entity to a DynamoDB item.

    Args:
        tenant: The Tenant domain entity.

    Returns:
        A dictionary representing the DynamoDB item.
    """
    return {
        "PK": f"TENANT#{tenant.tenant_id.value}",
        "SK": "METADATA",
        "tenant_id": tenant.tenant_id.value,
        "name": tenant.name,
        "plan": tenant.plan,
        "status": tenant.status,
        "allow_self_registration": tenant.allow_self_registration,
        "default_account_type": tenant.default_account_type,
        "created_at": tenant.created_at.isoformat(),
    }


def tenant_from_item(item: dict[str, Any]) -> Tenant:
    """Convert a DynamoDB item to a Tenant entity.

    Uses the Tenant.create() factory method to rebuild the entity
    from persisted data.

    Args:
        item: The DynamoDB item dictionary.

    Returns:
        A Tenant domain entity.
    """
    return Tenant.create(
        tenant_id=TenantId(item["tenant_id"]),
        name=item["name"],
        plan=item.get("plan"),
        status=item["status"],
        allow_self_registration=item.get("allow_self_registration", False),
        default_account_type=item.get("default_account_type"),
        created_at=datetime.fromisoformat(item["created_at"]),
    )
