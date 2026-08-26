"""Session entity ↔ DynamoDB item mapper.

Maps session data to/from DynamoDB items using the single table design:
- PK=SESSION#{user_id}, SK=TOKEN#{token_id}
- TTL attribute for automatic DynamoDB expiration

Note: Since Cognito manages sessions externally, this mapper provides
a lightweight dictionary-based approach without a full Session entity class.
The to_item/from_item functions work with plain dictionaries representing
session data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def session_to_item(session: dict[str, Any]) -> dict[str, Any]:
    """Convert session data to a DynamoDB item.

    Args:
        session: Dictionary containing session data with keys:
            - user_id: UUID of the user
            - token_id: Unique token identifier
            - refresh_token: The hashed refresh token
            - tenant_id: UUID of the tenant
            - expires_at: Expiration epoch timestamp (int)
            - created_at: Creation datetime

    Returns:
        A dictionary representing the DynamoDB item with TTL.
    """
    created_at = session["created_at"]
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()

    return {
        "PK": f"SESSION#{session['user_id']}",
        "SK": f"TOKEN#{session['token_id']}",
        "user_id": session["user_id"],
        "token_id": session["token_id"],
        "refresh_token": session["refresh_token"],
        "tenant_id": session["tenant_id"],
        "expires_at": session["expires_at"],
        "created_at": created_at,
        "ttl": session["expires_at"],
    }


def session_from_item(item: dict[str, Any]) -> dict[str, Any]:
    """Convert a DynamoDB item to session data.

    Args:
        item: The DynamoDB item dictionary.

    Returns:
        A dictionary containing session data.
    """
    return {
        "user_id": item["user_id"],
        "token_id": item["token_id"],
        "refresh_token": item["refresh_token"],
        "tenant_id": item["tenant_id"],
        "expires_at": item["expires_at"],
        "created_at": item["created_at"],
    }
