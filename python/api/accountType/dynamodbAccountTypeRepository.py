"""DynamoDB implementation of the IAccountTypeRepository port.

Uses single table design with:
- PK=TENANT#{tenant_id}#ACCTYPE, SK=ACCTYPE#{account_type_id}
- GSI1PK=TENANT#{tenant_id}#ACCTYPE, GSI1SK=NAME#{lowercase(name)}
"""

from __future__ import annotations

import base64
import json
from typing import Any

from api.accountType.iAccountTypeRepository import IAccountTypeRepository
from api.common.ports.sharedTypes import PaginatedResult, PaginationParams
from api.accountType.accountType import AccountType
from api.common.config.dynamodbClient import get_dynamodb_table
from api.accountType.accountTypeMapper import (
    account_type_from_item,
    account_type_to_item,
)


class DynamoDBAccountTypeRepository(IAccountTypeRepository):
    """DynamoDB-backed repository for AccountType entities.

    All operations are scoped to a single tenant via partition key design.
    """

    def __init__(self) -> None:
        self._table = get_dynamodb_table()

    async def find_by_id(
        self, tenant_id: str, account_type_id: str
    ) -> AccountType | None:
        """Find an account type by tenant and ID using GetItem.

        Uses PK=TENANT#{tenant_id}#ACCTYPE, SK=ACCTYPE#{account_type_id}.
        """
        response = self._table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#ACCTYPE",
                "SK": f"ACCTYPE#{account_type_id}",
            }
        )

        item = response.get("Item")
        if item is None:
            return None

        return account_type_from_item(item)

    async def find_by_name_in_tenant(
        self, tenant_id: str, name: str
    ) -> AccountType | None:
        """Find an account type by name within a tenant using GSI1.

        Queries GSI1 with exact match:
        GSI1PK=TENANT#{tenant_id}#ACCTYPE, GSI1SK=NAME#{lowercase(name)}.
        """
        response = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk AND GSI1SK = :sk",
            ExpressionAttributeValues={
                ":pk": f"TENANT#{tenant_id}#ACCTYPE",
                ":sk": f"NAME#{name.lower()}",
            },
            Limit=1,
        )

        items = response.get("Items", [])
        if not items:
            return None

        return account_type_from_item(items[0])

    async def find_all_by_tenant(
        self, tenant_id: str, pagination: PaginationParams
    ) -> PaginatedResult[AccountType]:
        """List all account types for a tenant with cursor-based pagination.

        Queries the base table with PK=TENANT#{tenant_id}#ACCTYPE and
        SK begins_with "ACCTYPE#" to retrieve all account types for the tenant.
        """
        query_params: dict[str, Any] = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {
                ":pk": f"TENANT#{tenant_id}#ACCTYPE",
                ":sk_prefix": "ACCTYPE#",
            },
            "Limit": pagination.limit,
        }

        if pagination.cursor:
            exclusive_start_key = self._decode_cursor(pagination.cursor)
            if exclusive_start_key:
                query_params["ExclusiveStartKey"] = exclusive_start_key

        response = self._table.query(**query_params)

        items = response.get("Items", [])
        account_types = [account_type_from_item(item) for item in items]

        next_cursor: str | None = None
        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key:
            next_cursor = self._encode_cursor(last_evaluated_key)

        return PaginatedResult(items=account_types, next_cursor=next_cursor)

    async def save(self, account_type: AccountType) -> AccountType:
        """Persist a new account type using PutItem."""
        item = account_type_to_item(account_type)
        self._table.put_item(Item=item)
        return account_type

    async def update(self, account_type: AccountType) -> AccountType:
        """Update an existing account type using full item replacement (PutItem)."""
        item = account_type_to_item(account_type)
        self._table.put_item(Item=item)
        return account_type

    @staticmethod
    def _encode_cursor(last_evaluated_key: dict[str, Any]) -> str:
        """Encode DynamoDB LastEvaluatedKey as a base64 JSON string."""
        json_bytes = json.dumps(last_evaluated_key).encode("utf-8")
        return base64.urlsafe_b64encode(json_bytes).decode("utf-8")

    @staticmethod
    def _decode_cursor(cursor: str) -> dict[str, Any] | None:
        """Decode a base64 JSON cursor back to a DynamoDB ExclusiveStartKey."""
        try:
            json_bytes = base64.urlsafe_b64decode(cursor.encode("utf-8"))
            return json.loads(json_bytes)  # type: ignore[no-any-return]
        except (ValueError, json.JSONDecodeError):
            return None
