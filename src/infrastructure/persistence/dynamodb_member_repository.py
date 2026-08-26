"""DynamoDB implementation of IMemberRepository.

Implements member persistence using single table design with the following key patterns:
- PK=TENANT#{tenant_id}#MEMBER#{member_id}, SK=PROFILE
- GSI1PK=TENANT#{tenant_id}#MEMBER#ACCTYPE#{account_type_lowercase}, GSI1SK=MEMBER#{member_id}
- GSI2PK=TENANT#{tenant_id}#USER#{user_id}, GSI2SK=MEMBER#{member_id}
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

from application.ports.i_member_repository import IMemberRepository
from application.ports.shared_types import MemberFilters, PaginatedResult, PaginationParams
from infrastructure.config.dynamodb_client import get_dynamodb_table
from infrastructure.config.environment import get_environment_config
from infrastructure.mappers.member_mapper import member_from_item, member_to_item
from infrastructure.mappers.user_mapper import tenant_membership_to_item, user_role_to_item

if TYPE_CHECKING:
    from domain.entities.member import Member
    from domain.entities.tenant_membership import TenantMembership
    from domain.entities.user_role import UserRole


class DynamoDBMemberRepository(IMemberRepository):
    """DynamoDB-based repository for Member entities.

    Uses the application's single DynamoDB table with partition key patterns
    to isolate data per tenant and enable efficient access patterns via GSIs.
    """

    def find_by_id(self, tenant_id: str, member_id: str) -> Member | None:
        """Find a member by tenant and member ID using GetItem.

        Key pattern: PK=TENANT#{tenant_id}#MEMBER#{member_id}, SK=PROFILE
        """
        table = get_dynamodb_table()

        response = table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#MEMBER#{member_id}",
                "SK": "PROFILE",
            }
        )

        item = response.get("Item")
        if item is None:
            return None

        return member_from_item(item)

    def find_by_user_in_tenant(self, tenant_id: str, user_id: str) -> Member | None:
        """Find a member by user ID within a specific tenant using GSI2.

        Key pattern: GSI2PK=TENANT#{tenant_id}#USER#{user_id}
        """
        table = get_dynamodb_table()

        response = table.query(
            IndexName="GSI2",
            KeyConditionExpression="GSI2PK = :pk",
            ExpressionAttributeValues={
                ":pk": f"TENANT#{tenant_id}#USER#{user_id}",
            },
            Limit=1,
        )

        items = response.get("Items", [])
        if not items:
            return None

        return member_from_item(items[0])

    def find_by_tenant_and_filters(
        self,
        tenant_id: str,
        filters: MemberFilters,
        pagination: PaginationParams,
    ) -> PaginatedResult[Member]:
        """Query members within a tenant with optional filters and pagination.

        When account_type filter is provided, queries GSI1 with:
            GSI1PK=TENANT#{tenant_id}#MEMBER#ACCTYPE#{account_type.lower()}

        When no account_type filter, uses Scan with FilterExpression on tenant_id
        attribute. This is acceptable for MVP and can be optimized with a
        dedicated GSI later.

        Status filter is always applied as a FilterExpression.
        Pagination uses base64-encoded LastEvaluatedKey as cursor.
        """
        table = get_dynamodb_table()
        limit = pagination.limit

        # Build query/scan parameters
        if filters.account_type:
            # Use GSI1 for account_type filtering (case-insensitive via lowercase key)
            params = self._build_gsi1_query_params(tenant_id, filters, limit, pagination.cursor)
            response = table.query(**params)
        else:
            # No account_type filter — use Scan with tenant_id filter
            params = self._build_scan_params(tenant_id, filters, limit, pagination.cursor)
            response = table.scan(**params)

        items = response.get("Items", [])
        members = [member_from_item(item) for item in items]

        # Encode pagination cursor
        next_cursor: str | None = None
        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key:
            next_cursor = self._encode_cursor(last_evaluated_key)

        return PaginatedResult(items=members, next_cursor=next_cursor)

    def count_active_by_account_type(self, tenant_id: str, account_type_name: str) -> int:
        """Count active members using a specific account type within a tenant.

        Queries GSI1 with GSI1PK=TENANT#{tenant_id}#MEMBER#ACCTYPE#{name.lower()}
        and applies FilterExpression on status='active'.

        Uses Select='COUNT' to avoid transferring item data.
        """
        table = get_dynamodb_table()

        gsi1pk = f"TENANT#{tenant_id}#MEMBER#ACCTYPE#{account_type_name.lower()}"

        response = table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            FilterExpression="#s = :active_status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":pk": gsi1pk,
                ":active_status": "active",
            },
            Select="COUNT",
        )

        count: int = response.get("Count", 0)

        # Handle pagination for large result sets
        while "LastEvaluatedKey" in response:
            response = table.query(
                IndexName="GSI1",
                KeyConditionExpression="GSI1PK = :pk",
                FilterExpression="#s = :active_status",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":pk": gsi1pk,
                    ":active_status": "active",
                },
                Select="COUNT",
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            count += response.get("Count", 0)

        return count

    def save(self, member: Member) -> Member:
        """Persist a new member entity using PutItem.

        Converts the Member entity to a DynamoDB item using the member mapper
        and writes it to the table.
        """
        table = get_dynamodb_table()
        item = member_to_item(member)
        table.put_item(Item=item)
        return member

    def update(self, member: Member) -> Member:
        """Update an existing member entity using PutItem (full item replacement).

        Overwrites the entire item with the updated member data.
        This is acceptable because the mapper produces the complete item
        including all key attributes.
        """
        table = get_dynamodb_table()
        item = member_to_item(member)
        table.put_item(Item=item)
        return member

    def create_member_with_roles(
        self,
        membership: TenantMembership,
        member: Member,
        roles: list[UserRole],
    ) -> None:
        """Atomically create a tenant membership, member, and role assignments.

        Uses DynamoDB TransactWriteItems to persist all records in a single
        atomic transaction (Req 12.2). Either all records are created or none.

        The transaction includes:
        - TenantMembership item (PK=TENANT#{tid}#USER#{uid}, SK=MEMBERSHIP)
        - Member item (PK=TENANT#{tid}#MEMBER#{mid}, SK=PROFILE)
        - UserRole items (PK=TENANT#{tid}#USER#{uid}, SK=ROLE#{role_name})
        """
        config = get_environment_config()
        table = get_dynamodb_table()
        table_name = config.table_name

        # Build transaction items
        transact_items: list[dict[str, Any]] = []

        # 1. TenantMembership
        membership_item = tenant_membership_to_item(membership)
        transact_items.append({
            "Put": {
                "TableName": table_name,
                "Item": membership_item,
            }
        })

        # 2. Member
        member_item = member_to_item(member)
        transact_items.append({
            "Put": {
                "TableName": table_name,
                "Item": member_item,
            }
        })

        # 3. UserRole(s)
        for role in roles:
            role_item = user_role_to_item(role)
            transact_items.append({
                "Put": {
                    "TableName": table_name,
                    "Item": role_item,
                }
            })

        # Execute atomic transaction via the low-level client
        client = table.meta.client
        client.transact_write_items(TransactItems=transact_items)

    # ─── Private Helpers ──────────────────────────────────────────────────────

    def _build_gsi1_query_params(
        self,
        tenant_id: str,
        filters: MemberFilters,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        """Build query parameters for GSI1 (account_type filter)."""
        account_type = filters.account_type or ""
        gsi1pk = f"TENANT#{tenant_id}#MEMBER#ACCTYPE#{account_type.lower()}"

        params: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": "GSI1PK = :pk",
            "ExpressionAttributeValues": {":pk": gsi1pk},
            "Limit": limit,
        }

        # Apply status filter if provided
        if filters.status:
            params["FilterExpression"] = "#s = :status_val"
            params["ExpressionAttributeNames"] = {"#s": "status"}
            params["ExpressionAttributeValues"][":status_val"] = filters.status

        # Apply pagination cursor
        if cursor:
            params["ExclusiveStartKey"] = self._decode_cursor(cursor)

        return params

    def _build_scan_params(
        self,
        tenant_id: str,
        filters: MemberFilters,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        """Build scan parameters for listing all members in a tenant."""
        filter_parts: list[str] = ["tenant_id = :tid", "SK = :sk"]
        expr_values: dict[str, Any] = {
            ":tid": tenant_id,
            ":sk": "PROFILE",
        }
        expr_names: dict[str, str] = {}

        # Apply status filter if provided
        if filters.status:
            filter_parts.append("#s = :status_val")
            expr_names["#s"] = "status"
            expr_values[":status_val"] = filters.status

        params: dict[str, Any] = {
            "FilterExpression": " AND ".join(filter_parts),
            "ExpressionAttributeValues": expr_values,
            "Limit": limit,
        }

        if expr_names:
            params["ExpressionAttributeNames"] = expr_names

        # Apply pagination cursor
        if cursor:
            params["ExclusiveStartKey"] = self._decode_cursor(cursor)

        return params

    @staticmethod
    def _encode_cursor(last_evaluated_key: dict[str, Any]) -> str:
        """Encode DynamoDB LastEvaluatedKey as a base64 JSON string."""
        json_str = json.dumps(last_evaluated_key, default=str)
        return base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _decode_cursor(cursor: str) -> dict[str, Any]:
        """Decode a base64 pagination cursor back to DynamoDB ExclusiveStartKey."""
        json_str = base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
        result: dict[str, Any] = json.loads(json_str)
        return result
