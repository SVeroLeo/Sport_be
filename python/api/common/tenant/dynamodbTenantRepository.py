"""DynamoDB implementation of ITenantRepository.

Uses single table design with key pattern:
- PK=TENANT#{tenant_id}, SK=METADATA
"""

from __future__ import annotations

from api.common.tenant.iTenantRepository import ITenantRepository
from api.common.tenant.tenant import Tenant
from api.common.config.dynamodbClient import get_dynamodb_table
from api.common.tenant.tenantMapper import tenant_from_item


class DynamoDBTenantRepository(ITenantRepository):
    """DynamoDB-backed tenant repository.

    Reads tenant records from a single DynamoDB table using
    the PK=TENANT#{tenant_id}, SK=METADATA key schema.
    """

    async def find_by_id(self, tenant_id: str) -> Tenant | None:
        """Find a tenant by its ID.

        Performs a GetItem against DynamoDB with:
        - PK: TENANT#{tenant_id}
        - SK: METADATA

        Args:
            tenant_id: The tenant UUID to look up.

        Returns:
            The Tenant entity if found, or None.
        """
        table = get_dynamodb_table()

        response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}",
                "SK": "METADATA",
            }
        )

        item = response.get("Item")
        if item is None:
            return None

        return tenant_from_item(item)
