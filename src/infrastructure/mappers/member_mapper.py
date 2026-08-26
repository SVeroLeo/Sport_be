"""Member entity ↔ DynamoDB item mapper.

Maps Member entities to/from DynamoDB items using the single table design:
- PK=TENANT#{tenant_id}#MEMBER#{member_id}, SK=PROFILE
- GSI1PK=TENANT#{tenant_id}#MEMBER#ACCTYPE#{account_type_lowercase}, GSI1SK=MEMBER#{member_id}
- GSI2PK=TENANT#{tenant_id}#USER#{user_id}, GSI2SK=MEMBER#{member_id}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from domain.entities.member import Member


def member_to_item(member: Member) -> dict[str, Any]:
    """Convert a Member entity to a DynamoDB item.

    Args:
        member: The Member domain entity.

    Returns:
        A dictionary representing the DynamoDB item with all key attributes.
    """
    item: dict[str, Any] = {
        "PK": f"TENANT#{member.tenant_id}#MEMBER#{member.member_id}",
        "SK": "PROFILE",
        "GSI1PK": f"TENANT#{member.tenant_id}#MEMBER#ACCTYPE#{member.account_type.lower()}",
        "GSI1SK": f"MEMBER#{member.member_id}",
        "GSI2PK": f"TENANT#{member.tenant_id}#USER#{member.user_id}",
        "GSI2SK": f"MEMBER#{member.member_id}",
        "member_id": member.member_id,
        "tenant_id": member.tenant_id,
        "user_id": member.user_id,
        "account_type": member.account_type,
        "account_type_id": member.account_type_id,
        "full_name": member.full_name,
        "email": member.email,
        "status": member.status,
        "registration_type": member.registration_type,
        "invited_by": member.invited_by,
        "metadata": member.metadata,
        "created_at": member.created_at.isoformat(),
        "updated_at": member.updated_at.isoformat(),
    }

    return item


def member_from_item(item: dict[str, Any]) -> Member:
    """Convert a DynamoDB item to a Member entity.

    Uses the Member.reconstitute() factory method to rebuild the entity
    from persisted data without validation.

    Args:
        item: The DynamoDB item dictionary.

    Returns:
        A Member domain entity.
    """
    return Member.reconstitute(
        member_id=item["member_id"],
        tenant_id=item["tenant_id"],
        user_id=item["user_id"],
        account_type=item["account_type"],
        account_type_id=item["account_type_id"],
        full_name=item["full_name"],
        email=item["email"],
        status=item["status"],
        registration_type=item["registration_type"],
        invited_by=item.get("invited_by"),
        metadata=item.get("metadata"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )
