"""DynamoDB implementation of IUserRepository.

Implements user persistence operations using DynamoDB single table design:
- User records: PK=USER#{email}, SK=PROFILE
- TenantMembership: PK=TENANT#{tenant_id}#USER#{user_id}, SK=MEMBERSHIP
- UserRole: PK=TENANT#{tenant_id}#USER#{user_id}, SK=ROLE#{role_name}
- Member: PK=TENANT#{tenant_id}#MEMBER#{member_id}, SK=PROFILE

Transactional operations use DynamoDB TransactWriteItems for atomicity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from application.ports.i_user_repository import IUserRepository
from domain.entities.member import Member
from domain.entities.tenant_membership import TenantMembership
from domain.entities.user import User
from domain.entities.user_role import UserRole
from domain.value_objects.email import Email
from infrastructure.config.dynamodb_client import get_dynamodb_table
from infrastructure.mappers.member_mapper import member_to_item
from infrastructure.mappers.user_mapper import (
    tenant_membership_to_item,
    user_from_item,
    user_role_from_item,
    user_role_to_item,
    user_to_item,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


class DynamoDBUserRepository(IUserRepository):
    """DynamoDB-backed user repository using single table design.

    All operations use the shared DynamoDB table configured via environment.
    Transactional writes use the DynamoDB client accessed via
    table.meta.client for TransactWriteItems support.
    """

    def __init__(self, table: "Table | None" = None) -> None:
        """Initialize the repository.

        Args:
            table: Optional DynamoDB Table resource. If not provided,
                   uses the singleton from dynamodb_client module.
        """
        self._table = table or get_dynamodb_table()
        self._table_name = self._table.table_name

    # ──── Query Methods ───────────────────────────────────────────────────────

    def find_by_email(self, email: Email) -> User | None:
        """Find a user by their email address.

        Uses GetItem with PK=USER#{email}, SK=PROFILE.

        Args:
            email: Validated Email value object.

        Returns:
            The User entity if found, None otherwise.
        """
        response = self._table.get_item(
            Key={
                "PK": f"USER#{email.value}",
                "SK": "PROFILE",
            }
        )

        item = response.get("Item")
        if item is None:
            return None

        return user_from_item(item)

    def find_by_id(self, user_id: str) -> User | None:
        """Find a user by their unique identifier.

        Since user_id is not part of the primary key (PK=USER#{email}),
        this performs a Scan with a filter on user_id. This is acceptable
        for low-frequency operations (e.g., admin lookups) but not suitable
        for high-throughput access patterns.

        Note: For production at scale, consider adding a GSI with
        PK=USER#{user_id} to enable efficient lookups by user_id.

        Args:
            user_id: UUID string of the user.

        Returns:
            The User entity if found, None otherwise.
        """
        response = self._table.scan(
            FilterExpression="user_id = :uid AND SK = :sk",
            ExpressionAttributeValues={
                ":uid": user_id,
                ":sk": "PROFILE",
            },
            Limit=1,
        )

        items = response.get("Items", [])
        if not items:
            return None

        return user_from_item(items[0])

    def save(self, user: User) -> User:
        """Persist a user entity (create or update).

        Uses PutItem which creates the item if it doesn't exist
        or replaces it entirely if it does.

        Args:
            user: The User entity to persist.

        Returns:
            The persisted User entity.
        """
        item = user_to_item(user)
        self._table.put_item(Item=item)
        return user

    def get_roles_for_tenant(self, user_id: str, tenant_id: str) -> list[UserRole]:
        """Get all roles assigned to a user within a specific tenant.

        Queries with PK=TENANT#{tenant_id}#USER#{user_id}, SK begins_with ROLE#.

        Args:
            user_id: UUID string of the user.
            tenant_id: UUID string of the tenant.

        Returns:
            List of UserRole entities for the user in the given tenant.
        """
        response = self._table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": f"TENANT#{tenant_id}#USER#{user_id}",
                ":sk_prefix": "ROLE#",
            },
        )

        items = response.get("Items", [])
        return [user_role_from_item(item) for item in items]

    # ──── Transactional Methods ───────────────────────────────────────────────

    def register_with_membership(
        self,
        user: User,
        membership: TenantMembership,
        member: Member,
        role: UserRole,
    ) -> None:
        """Atomically create User, TenantMembership, Member, and Role records.

        Used by self-registration flow. All records are persisted in a single
        DynamoDB transaction — if any part fails, no records are created.

        Args:
            user: The new User entity.
            membership: The TenantMembership linking user to tenant.
            member: The Member entity within the tenant.
            role: The default role assignment (typically "viewer").

        Raises:
            ClientError: If the DynamoDB transaction fails.
        """
        user_item = user_to_item(user)
        membership_item = tenant_membership_to_item(membership)
        member_item = member_to_item(member)
        role_item = user_role_to_item(role)

        transact_items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(user_item),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(membership_item),
                }
            },
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(member_item),
                }
            },
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(role_item),
                }
            },
        ]

        client = self._table.meta.client
        client.transact_write_items(TransactItems=transact_items)

    def create_user_with_membership(
        self,
        user: User,
        membership: TenantMembership,
        member: Member,
        roles: list[UserRole],
    ) -> None:
        """Atomically create User, TenantMembership, Member, and multiple Roles.

        Used by admin-invited member creation when the user does not yet exist.
        All records are persisted in a single DynamoDB transaction — if any part
        fails, no records are created.

        Args:
            user: The new User entity (status: pending_confirmation).
            membership: The TenantMembership linking user to tenant.
            member: The Member entity within the tenant.
            roles: List of role assignments for the user in the tenant.

        Raises:
            ClientError: If the DynamoDB transaction fails.
        """
        user_item = user_to_item(user)
        membership_item = tenant_membership_to_item(membership)
        member_item = member_to_item(member)

        transact_items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(user_item),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(membership_item),
                }
            },
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(member_item),
                }
            },
        ]

        for role in roles:
            role_item = user_role_to_item(role)
            transact_items.append(
                {
                    "Put": {
                        "TableName": self._table_name,
                        "Item": _strip_none_values(role_item),
                    }
                }
            )

        client = self._table.meta.client
        client.transact_write_items(TransactItems=transact_items)


# ──── Internal Helpers ────────────────────────────────────────────────────────


def _strip_none_values(item: dict[str, Any]) -> dict[str, Any]:
    """Remove keys with None values from a DynamoDB item.

    DynamoDB does not store null attributes by default. Stripping None
    values ensures the item only contains attributes with real data.

    Args:
        item: Dictionary that may contain None values.

    Returns:
        A new dictionary without None-valued keys.
    """
    return {key: value for key, value in item.items() if value is not None}
