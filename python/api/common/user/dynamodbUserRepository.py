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

from api.common.user.iUserRepository import IUserRepository
from api.member.member import Member
from api.common.tenant.tenantMembership import TenantMembership
from api.common.user.user import User
from api.common.user.userRole import UserRole
from api.common.valueObjects.email import Email
from api.common.config.dynamodbClient import get_dynamodb_table
from api.member.memberMapper import member_to_item
from api.common.user.userMapper import (
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

    # ──── Social Login (implemented in task 6) ────────────────────────────────

    def find_by_cognito_sub(self, cognito_sub: str) -> User | None:
        """Find a user by their Cognito subject identifier.

        Since cognito_sub is not part of the primary key (PK=USER#{email}),
        this performs a Scan with a filter on cognito_sub. This mirrors the
        find_by_id pattern and is acceptable for low-frequency operations
        (e.g., the social-login callback flow) but not suitable for
        high-throughput access patterns.

        Note: For production at scale, consider adding a GSI with
        PK=USER#{cognito_sub} to enable efficient lookups by cognito_sub.

        Args:
            cognito_sub: The Cognito ``sub`` claim of the user.

        Returns:
            The User entity if found, None otherwise.
        """
        response = self._table.scan(
            FilterExpression="cognito_sub = :sub AND SK = :sk",
            ExpressionAttributeValues={
                ":sub": cognito_sub,
                ":sk": "PROFILE",
            },
            Limit=1,
        )

        items = response.get("Items", [])
        if not items:
            return None

        return user_from_item(items[0])

    def register_social_user(
        self,
        user: User,
        membership: TenantMembership | None,
        member: Member | None,
        role: UserRole | None,
    ) -> None:
        """Atomically provision a social-login user (idempotently).

        Builds a single ``TransactWriteItems`` request containing the User
        record and, when the tenant is known, the TenantMembership, Member,
        and UserRole records. The User Put carries an
        ``attribute_not_exists(PK)`` condition so that a concurrent or repeated
        invocation for the same user does not create duplicate records.

        Idempotency: if the User already exists, DynamoDB cancels the
        transaction with a conditional-check failure on the User item. That
        outcome is treated as success (the user is already provisioned) and is
        swallowed silently, so re-invocation of the callback flow is safe.

        Args:
            user: The new Social_User entity (registration_type="social").
            membership: Optional TenantMembership, included only when the
                tenant is known (auto-assigned).
            member: Optional Member entity, included only when the tenant is
                known.
            role: Optional default UserRole, included only when the tenant is
                known.

        Raises:
            ClientError: If the DynamoDB transaction fails for any reason other
                than a conditional-check failure on the User item.
        """
        transact_items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _strip_none_values(user_to_item(user)),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            }
        ]

        if membership is not None:
            transact_items.append(
                {
                    "Put": {
                        "TableName": self._table_name,
                        "Item": _strip_none_values(
                            tenant_membership_to_item(membership)
                        ),
                    }
                }
            )

        if member is not None:
            transact_items.append(
                {
                    "Put": {
                        "TableName": self._table_name,
                        "Item": _strip_none_values(member_to_item(member)),
                    }
                }
            )

        if role is not None:
            transact_items.append(
                {
                    "Put": {
                        "TableName": self._table_name,
                        "Item": _strip_none_values(user_role_to_item(role)),
                    }
                }
            )

        client = self._table.meta.client
        try:
            client.transact_write_items(TransactItems=transact_items)
        except ClientError as error:
            if _is_user_conditional_check_failure(error):
                # User already exists — idempotent re-invocation. Treat as
                # success and return without raising.
                return
            raise

    def associate_tenant(
        self,
        user_id: str,
        membership: TenantMembership,
        member: Member,
        role: UserRole,
        new_status: str,
        new_default_tenant_id: str,
    ) -> None:
        """Atomically associate a pending-tenant user with a tenant.

        Performs a single ``TransactWriteItems`` request that writes the new
        TenantMembership, Member, and UserRole records and updates the existing
        User record's ``default_tenant_id`` and ``status`` attributes. Because
        the transaction is atomic, no partial write is ever observable — either
        all four mutations succeed or none are applied.

        Resolving the User key: the User's primary key is email-based
        (PK=``USER#{email}``, SK=``PROFILE``), but this method only receives the
        ``user_id``. The email is therefore obtained by first loading the User
        via :meth:`find_by_id` (which scans by ``user_id``) and reading its
        email off the reconstituted entity. That email is used to build the
        ``Update`` action's ``Key``.

        Args:
            user_id: UUID string of the user to associate.
            membership: The TenantMembership linking user to tenant.
            member: The Member entity within the tenant.
            role: The default role assignment (typically "viewer").
            new_status: The new User status (typically "active").
            new_default_tenant_id: The tenant to record as the user's default.

        Raises:
            ValueError: If no User exists for the given user_id.
            ClientError: If the DynamoDB transaction fails.
        """
        user = self.find_by_id(user_id)
        if user is None:
            raise ValueError(f"User not found for user_id: {user_id}")

        membership_item = tenant_membership_to_item(membership)
        member_item = member_to_item(member)
        role_item = user_role_to_item(role)

        transact_items: list[dict[str, Any]] = [
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
            {
                "Update": {
                    "TableName": self._table_name,
                    "Key": {
                        "PK": f"USER#{user.email.value}",
                        "SK": "PROFILE",
                    },
                    "UpdateExpression": (
                        "SET default_tenant_id = :tid, #s = :status"
                    ),
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {
                        ":tid": new_default_tenant_id,
                        ":status": new_status,
                    },
                }
            },
        ]

        client = self._table.meta.client
        client.transact_write_items(TransactItems=transact_items)


# ──── Internal Helpers ────────────────────────────────────────────────────────


def _is_user_conditional_check_failure(error: ClientError) -> bool:
    """Return True when a transaction was cancelled by the User's condition.

    ``TransactWriteItems`` reports a failing ``attribute_not_exists(PK)``
    condition as a ``TransactionCanceledException`` whose ``CancellationReasons``
    list the per-item outcomes in request order. The User Put is always the
    first item in ``register_social_user``, so a ``ConditionalCheckFailed``
    reason at index 0 means the user already exists.

    Args:
        error: The ClientError raised by transact_write_items.

    Returns:
        True if the User item's conditional check failed, False otherwise.
    """
    error_info = error.response.get("Error", {})
    if error_info.get("Code") != "TransactionCanceledException":
        return False

    reasons = error.response.get("CancellationReasons")
    if not reasons:
        return False

    first_reason = reasons[0]
    return bool(first_reason) and first_reason.get("Code") == "ConditionalCheckFailed"


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
