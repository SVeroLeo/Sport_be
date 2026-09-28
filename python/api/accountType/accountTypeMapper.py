"""AccountType entity ↔ DynamoDB item mapper.

Maps AccountType entities to/from DynamoDB items using the single table design:
- PK=TENANT#{tenant_id}#ACCTYPE, SK=ACCTYPE#{account_type_id}
- GSI1PK=TENANT#{tenant_id}#ACCTYPE, GSI1SK=NAME#{lowercase(name)}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.accountType.accountType import AccountType


def account_type_to_item(account_type: AccountType) -> dict[str, Any]:
    """Convert an AccountType entity to a DynamoDB item.

    Args:
        account_type: The AccountType domain entity.

    Returns:
        A dictionary representing the DynamoDB item with all key attributes.
    """
    item: dict[str, Any] = {
        "PK": f"TENANT#{account_type.tenant_id}#ACCTYPE",
        "SK": f"ACCTYPE#{account_type.account_type_id}",
        "GSI1PK": f"TENANT#{account_type.tenant_id}#ACCTYPE",
        "GSI1SK": f"NAME#{account_type.name.lower()}",
        "account_type_id": account_type.account_type_id,
        "tenant_id": account_type.tenant_id,
        "name": account_type.name,
        "description": account_type.description,
        "config": account_type.config,
        "status": account_type.status,
        "created_at": account_type.created_at.isoformat(),
        "updated_at": account_type.updated_at.isoformat(),
    }

    return item


def account_type_from_item(item: dict[str, Any]) -> AccountType:
    """Convert a DynamoDB item to an AccountType entity.

    Uses the AccountType.reconstitute() factory method to rebuild the entity
    from persisted data without validation.

    Args:
        item: The DynamoDB item dictionary.

    Returns:
        An AccountType domain entity.
    """
    return AccountType.reconstitute(
        account_type_id=item["account_type_id"],
        tenant_id=item["tenant_id"],
        name=item["name"],
        description=item.get("description"),
        config=item.get("config"),
        status=item["status"],
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )
