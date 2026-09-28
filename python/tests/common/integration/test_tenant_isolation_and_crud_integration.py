"""Integration tests for tenant isolation and CRUD operations.

Tests exercise real DynamoDB repositories (via moto) and use cases together
to verify multi-tenant data isolation, account type CRUD, member management,
and pagination correctness.

**Validates: Requirements 5.1, 5.4, 6.1, 6.4, 8.1, 9.1, 9.3**
**Property 1: Tenant Data Isolation**
**Property 18: Pagination Bounded Response**
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from api.accountType.createAccountTypeInputDto import CreateAccountTypeInputDTO
from api.accountType.updateAccountTypeInputDto import UpdateAccountTypeInputDTO
from api.member.updateMemberInputDto import UpdateMemberInputDTO
from api.common.ports.sharedTypes import MemberFilters, PaginatedResult, PaginationParams
from api.accountType.createAccountTypeUseCase import CreateAccountTypeUseCase
from api.accountType.deleteAccountTypeUseCase import DeleteAccountTypeUseCase
from api.accountType.listAccountTypesUseCase import ListAccountTypesUseCase
from api.accountType.updateAccountTypeUseCase import UpdateAccountTypeUseCase
from api.member.deactivateMemberUseCase import DeactivateMemberUseCase
from api.member.updateMemberUseCase import UpdateMemberUseCase
from api.accountType.accountType import AccountType
from api.member.member import Member
from api.common.tenant.tenant import Tenant
from api.common.user.users import User
from api.common.errors.conflictError import ConflictError
from api.common.errors.domainError import DomainError
from api.common.errors.notFoundError import NotFoundError
from api.common.errors.validationError import ValidationError
from api.common.tenant.tenantId import TenantId
from api.common.tenant.tenantMapper import tenant_to_item
from api.accountType.dynamodbAccountTypeRepository import DynamoDBAccountTypeRepository
from api.member.dynamodbMemberRepository import DynamoDBMemberRepository


# â”€â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

TABLE_NAME = "test-table"
REGION = "us-east-1"
TENANT_A_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_ID_1 = "11111111-1111-1111-1111-111111111111"
USER_ID_2 = "22222222-2222-2222-2222-222222222222"
ACCOUNT_TYPE_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


# â”€â”€â”€ Fixtures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required environment variables for DynamoDB client."""
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("REGION", REGION)
    monkeypatch.setenv("TOKEN_EXPIRY", "3600")
    monkeypatch.setenv("SALT_ROUNDS", "4")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "test-pool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "test-client")


@pytest.fixture(autouse=True)
def _reset_singletons() -> Generator[None, None, None]:
    """Reset module-level singletons between tests."""
    import api.common.config.dynamodbClient as dc_mod
    import api.common.config.environment as env_mod

    env_mod._config = None
    dc_mod._dynamodb_resource = None
    dc_mod._table = None
    yield
    env_mod._config = None
    dc_mod._dynamodb_resource = None
    dc_mod._table = None


def _create_table(dynamodb_resource: Any) -> Any:
    """Create the DynamoDB table with PK, SK, GSI1, and GSI2."""
    table = dynamodb_resource.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _seed_tenant(table: Any, tenant_id: str) -> None:
    """Insert a tenant metadata record into DynamoDB."""
    now = datetime.now(UTC).isoformat()
    table.put_item(Item={
        "PK": f"TENANT#{tenant_id}",
        "SK": "METADATA",
        "tenant_id": tenant_id,
        "name": f"Tenant {tenant_id[:8]}",
        "plan": "basic",
        "status": "active",
        "allow_self_registration": True,
        "default_account_type": "usuario",
        "created_at": now,
    })


@pytest.fixture
def dynamodb_env() -> Generator[tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository], None, None]:
    """Provide real repositories backed by moto DynamoDB with both tenants seeded."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = _create_table(dynamodb)

        # Seed both tenants
        _seed_tenant(table, TENANT_A_ID)
        _seed_tenant(table, TENANT_B_ID)

        account_type_repo = DynamoDBAccountTypeRepository()
        member_repo = DynamoDBMemberRepository()

        yield account_type_repo, member_repo


def _make_member(
    member_id: str,
    tenant_id: str,
    user_id: str,
    account_type: str = "socio",
    status: str = "active",
    full_name: str = "Test User",
    email: str = "test@example.com",
) -> Member:
    """Factory for creating a Member entity."""
    now = datetime.now(UTC)
    return Member.reconstitute(
        member_id=member_id,
        tenant_id=tenant_id,
        user_id=user_id,
        account_type=account_type,
        account_type_id=ACCOUNT_TYPE_ID,
        full_name=full_name,
        email=email,
        status=status,
        registration_type="self",
        invited_by=None,
        metadata=None,
        created_at=now,
        updated_at=now,
    )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Property 1: Tenant Data Isolation
# Validates: Requirements 9.1, 9.3
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestTenantDataIsolation:
    """Verify that data queries are completely isolated per tenant.

    **Validates: Requirements 9.1, 9.3**
    """

    @pytest.mark.asyncio
    async def test_account_types_isolated_between_tenants(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Account types created in Tenant A are invisible to Tenant B."""
        account_type_repo, _ = dynamodb_env

        # Create account types in Tenant A
        at_a = AccountType.reconstitute(
            account_type_id="at-a-001",
            tenant_id=TENANT_A_ID,
            name="Socio Premium",
            description="Premium membership",
            config=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await account_type_repo.save(at_a)

        # Create account types in Tenant B
        at_b = AccountType.reconstitute(
            account_type_id="at-b-001",
            tenant_id=TENANT_B_ID,
            name="Profesional",
            description="Professional membership",
            config=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await account_type_repo.save(at_b)

        # Query Tenant A â€” should only see Tenant A's data
        result_a = await account_type_repo.find_all_by_tenant(
            TENANT_A_ID, PaginationParams(limit=100)
        )
        assert len(result_a.items) == 1
        assert result_a.items[0].name == "Socio Premium"
        assert result_a.items[0].tenant_id == TENANT_A_ID

        # Query Tenant B â€” should only see Tenant B's data
        result_b = await account_type_repo.find_all_by_tenant(
            TENANT_B_ID, PaginationParams(limit=100)
        )
        assert len(result_b.items) == 1
        assert result_b.items[0].name == "Profesional"
        assert result_b.items[0].tenant_id == TENANT_B_ID

    @pytest.mark.asyncio
    async def test_find_by_id_does_not_cross_tenants(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """find_by_id returns None for valid ID when queried from wrong tenant."""
        account_type_repo, _ = dynamodb_env

        at = AccountType.reconstitute(
            account_type_id="at-cross-001",
            tenant_id=TENANT_A_ID,
            name="VIP",
            description=None,
            config=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await account_type_repo.save(at)

        # Querying from Tenant B should return None
        result = await account_type_repo.find_by_id(TENANT_B_ID, "at-cross-001")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_name_does_not_cross_tenants(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """find_by_name_in_tenant respects tenant boundaries."""
        account_type_repo, _ = dynamodb_env

        at = AccountType.reconstitute(
            account_type_id="at-name-001",
            tenant_id=TENANT_A_ID,
            name="Coach",
            description=None,
            config=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await account_type_repo.save(at)

        # Same name lookup in Tenant B returns None
        result = await account_type_repo.find_by_name_in_tenant(TENANT_B_ID, "Coach")
        assert result is None

    @pytest.mark.asyncio
    async def test_members_isolated_between_tenants(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Members created in Tenant A are invisible to Tenant B."""
        _, member_repo = dynamodb_env

        # Create members in Tenant A
        member_a = _make_member("mem-a-001", TENANT_A_ID, USER_ID_1, full_name="Alice")
        member_repo.save(member_a)

        # Create members in Tenant B
        member_b = _make_member("mem-b-001", TENANT_B_ID, USER_ID_2, full_name="Bob")
        member_repo.save(member_b)

        # Query Tenant A
        result_a = member_repo.find_by_tenant_and_filters(
            TENANT_A_ID, MemberFilters(), PaginationParams(limit=100)
        )
        assert len(result_a.items) == 1
        assert result_a.items[0].full_name == "Alice"

        # Query Tenant B
        result_b = member_repo.find_by_tenant_and_filters(
            TENANT_B_ID, MemberFilters(), PaginationParams(limit=100)
        )
        assert len(result_b.items) == 1
        assert result_b.items[0].full_name == "Bob"

    @pytest.mark.asyncio
    async def test_member_find_by_id_does_not_cross_tenants(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Member find_by_id returns None when queried from wrong tenant."""
        _, member_repo = dynamodb_env

        member = _make_member("mem-iso-001", TENANT_A_ID, USER_ID_1)
        member_repo.save(member)

        # Cross-tenant access returns None (Req 9.3)
        result = member_repo.find_by_id(TENANT_B_ID, "mem-iso-001")
        assert result is None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Account Type CRUD Integration Tests
# Validates: Requirements 5.1, 5.4
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestAccountTypeCRUD:
    """Test account type create, list, update, and delete operations end-to-end.

    **Validates: Requirements 5.1, 5.4**
    """

    @pytest.mark.asyncio
    async def test_create_list_update_delete_flow(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Full CRUD lifecycle: create â†’ list â†’ update â†’ soft-delete."""
        account_type_repo, member_repo = dynamodb_env

        # --- CREATE ---
        from api.common.tenant.dynamodbTenantRepository import DynamoDBTenantRepository

        tenant_repo = DynamoDBTenantRepository()
        create_uc = CreateAccountTypeUseCase(account_type_repo, tenant_repo)

        input_dto = CreateAccountTypeInputDTO(
            tenant_id=TENANT_A_ID,
            name="Socio",
            description="Regular member",
            config={"color": "blue"},
        )
        created = await create_uc.execute(input_dto)

        assert created.name == "Socio"
        assert created.status == "active"
        assert created.tenant_id == TENANT_A_ID
        assert created.description == "Regular member"
        assert created.account_type_id is not None

        # --- LIST ---
        list_uc = ListAccountTypesUseCase(account_type_repo)
        listed = await list_uc.execute(TENANT_A_ID, PaginationParams(limit=100))

        assert len(listed.items) == 1
        assert listed.items[0].name == "Socio"

        # --- UPDATE ---
        update_uc = UpdateAccountTypeUseCase(account_type_repo)
        update_dto = UpdateAccountTypeInputDTO(
            tenant_id=TENANT_A_ID,
            account_type_id=created.account_type_id,
            name="Socio Gold",
            description="Premium member",
        )
        updated = await update_uc.execute(update_dto)

        assert updated.name == "Socio Gold"
        assert updated.description == "Premium member"
        assert updated.updated_at >= created.updated_at

        # Verify old name not findable
        old_found = await account_type_repo.find_by_name_in_tenant(TENANT_A_ID, "Socio")
        assert old_found is None

        # --- DELETE (soft) ---
        delete_uc = DeleteAccountTypeUseCase(account_type_repo, member_repo)
        await delete_uc.execute(TENANT_A_ID, created.account_type_id)

        # Verify status is now "inactive"
        deleted = await account_type_repo.find_by_id(TENANT_A_ID, created.account_type_id)
        assert deleted is not None
        assert deleted.status == "inactive"

    @pytest.mark.asyncio
    async def test_create_account_type_name_uniqueness_case_insensitive(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Creating an account type with the same name (different case) raises ConflictError."""
        account_type_repo, _ = dynamodb_env

        from api.common.tenant.dynamodbTenantRepository import DynamoDBTenantRepository

        tenant_repo = DynamoDBTenantRepository()
        create_uc = CreateAccountTypeUseCase(account_type_repo, tenant_repo)

        # Create first
        await create_uc.execute(CreateAccountTypeInputDTO(
            tenant_id=TENANT_A_ID,
            name="socio",
        ))

        # Try to create with different case â€” should raise ConflictError
        with pytest.raises(ConflictError, match="already exists"):
            await create_uc.execute(CreateAccountTypeInputDTO(
                tenant_id=TENANT_A_ID,
                name="Socio",
            ))

    @pytest.mark.asyncio
    async def test_delete_account_type_rejected_with_active_members(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Deleting an account type fails when active members reference it."""
        account_type_repo, member_repo = dynamodb_env

        # Create account type
        at = AccountType.reconstitute(
            account_type_id="at-del-001",
            tenant_id=TENANT_A_ID,
            name="Profesional",
            description=None,
            config=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await account_type_repo.save(at)

        # Create an active member using this account type
        member = _make_member(
            "mem-del-001", TENANT_A_ID, USER_ID_1,
            account_type="profesional",
        )
        member_repo.save(member)

        # Attempt delete â€” should be rejected
        delete_uc = DeleteAccountTypeUseCase(account_type_repo, member_repo)
        with pytest.raises(DomainError, match="active members are using it"):
            await delete_uc.execute(TENANT_A_ID, "at-del-001")

        # Verify account type is still active
        still_active = await account_type_repo.find_by_id(TENANT_A_ID, "at-del-001")
        assert still_active is not None
        assert still_active.status == "active"


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Member Management Integration Tests
# Validates: Requirements 6.1, 6.4, 8.1
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestMemberManagement:
    """Test member list with filters, update, and deactivation.

    **Validates: Requirements 6.1, 6.4, 8.1**
    """

    @pytest.mark.asyncio
    async def test_list_members_with_account_type_filter(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Filtering by account_type returns only matching members."""
        _, member_repo = dynamodb_env

        # Create members with different account types
        member_repo.save(_make_member("mem-f-001", TENANT_A_ID, "u1", account_type="socio", email="a@x.com"))
        member_repo.save(_make_member("mem-f-002", TENANT_A_ID, "u2", account_type="profesional", email="b@x.com"))
        member_repo.save(_make_member("mem-f-003", TENANT_A_ID, "u3", account_type="socio", email="c@x.com"))

        # Test filtering directly through the repository (integration-level)
        result = member_repo.find_by_tenant_and_filters(
            TENANT_A_ID,
            MemberFilters(account_type="socio"),
            PaginationParams(limit=100),
        )

        assert len(result.items) == 2
        assert all(item.account_type == "socio" for item in result.items)

    @pytest.mark.asyncio
    async def test_list_members_with_status_filter(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Filtering by status returns only matching members."""
        _, member_repo = dynamodb_env

        member_repo.save(_make_member("mem-s-001", TENANT_A_ID, "u1", status="active", email="a@x.com"))
        member_repo.save(_make_member("mem-s-002", TENANT_A_ID, "u2", status="inactive", email="b@x.com"))
        member_repo.save(_make_member("mem-s-003", TENANT_A_ID, "u3", status="active", email="c@x.com"))

        # Test filtering directly through the repository (integration-level)
        result = member_repo.find_by_tenant_and_filters(
            TENANT_A_ID,
            MemberFilters(status="active"),
            PaginationParams(limit=100),
        )

        assert len(result.items) == 2
        assert all(item.status == "active" for item in result.items)

    @pytest.mark.asyncio
    async def test_update_member_full_name_and_account_type(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Updating a member's full_name and account_type persists changes correctly."""
        account_type_repo, member_repo = dynamodb_env

        # Use a valid UUID for the account type ID
        at_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"

        # Create the target account type (must exist and be active for validation)
        at = AccountType.reconstitute(
            account_type_id=at_id,
            tenant_id=TENANT_A_ID,
            name="Profesional",
            description=None,
            config=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await account_type_repo.save(at)

        # Create initial member with a valid UUID account_type_id
        initial_at_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        member = Member.reconstitute(
            member_id="mem-upd-001",
            tenant_id=TENANT_A_ID,
            user_id=USER_ID_1,
            account_type="socio",
            account_type_id=initial_at_id,
            full_name="Original Name",
            email="orig@x.com",
            status="active",
            registration_type="self",
            invited_by=None,
            metadata=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        member_repo.save(member)

        # Update via use case
        update_uc = UpdateMemberUseCase(member_repo, account_type_repo)
        update_dto = UpdateMemberInputDTO(
            tenant_id=TENANT_A_ID,
            member_id="mem-upd-001",
            full_name="Updated Name",
            account_type="Profesional",
        )
        result = await update_uc.execute(update_dto)

        assert result.full_name == "Updated Name"
        assert result.account_type == "Profesional"
        assert result.account_type_id == at_id
        # Immutable fields preserved
        assert result.registration_type == "self"
        assert result.created_at == member.created_at

    @pytest.mark.asyncio
    async def test_deactivate_member(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Deactivating a member sets status to 'inactive' and calls Cognito disable."""
        _, member_repo = dynamodb_env

        # Create member
        member = _make_member("mem-deact-001", TENANT_A_ID, USER_ID_1, email="deact@x.com")
        member_repo.save(member)

        # Create a mock user repository and cognito service
        mock_user_repo = MagicMock()
        mock_user = User.reconstitute(
            user_id=USER_ID_1,
            email="deact@x.com",
            cognito_sub="cognito-sub-123",
            full_name="Test User",
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_user_repo.find_by_id.return_value = mock_user

        mock_cognito = AsyncMock()
        mock_cognito.admin_disable_user.return_value = None

        deactivate_uc = DeactivateMemberUseCase(
            member_repository=member_repo,
            user_repository=mock_user_repo,
            cognito_service=mock_cognito,
        )

        await deactivate_uc.execute(TENANT_A_ID, "mem-deact-001")

        # Verify member status changed
        deactivated = member_repo.find_by_id(TENANT_A_ID, "mem-deact-001")
        assert deactivated is not None
        assert deactivated.status == "inactive"

        # Verify Cognito was called
        mock_cognito.admin_disable_user.assert_called_once_with("cognito-sub-123")

    @pytest.mark.asyncio
    async def test_deactivate_already_inactive_raises_error(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Deactivating an already inactive member raises ValidationError."""
        _, member_repo = dynamodb_env

        # Create already-inactive member
        member = _make_member(
            "mem-inact-001", TENANT_A_ID, USER_ID_1,
            status="inactive", email="inact@x.com",
        )
        member_repo.save(member)

        mock_user_repo = MagicMock()
        mock_cognito = AsyncMock()

        deactivate_uc = DeactivateMemberUseCase(
            member_repository=member_repo,
            user_repository=mock_user_repo,
            cognito_service=mock_cognito,
        )

        with pytest.raises(ValidationError):
            await deactivate_uc.execute(TENANT_A_ID, "mem-inact-001")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Property 18: Pagination Bounded Response
# Validates: Requirements 5.4, 6.1, 6.4
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestPaginationBoundedResponse:
    """Verify pagination returns bounded responses and non-overlapping pages.

    **Validates: Requirements 5.4, 6.1, 6.4**
    """

    @pytest.mark.asyncio
    async def test_account_type_pagination_max_100_per_page(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Creating >100 account types and requesting limit=100 returns exactly 100 with cursor."""
        account_type_repo, _ = dynamodb_env

        # Create 105 account types
        for i in range(105):
            at = AccountType.reconstitute(
                account_type_id=f"at-page-{i:04d}",
                tenant_id=TENANT_A_ID,
                name=f"Type{i:04d}",
                description=None,
                config=None,
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await account_type_repo.save(at)

        # Request with limit=100
        result = await account_type_repo.find_all_by_tenant(
            TENANT_A_ID, PaginationParams(limit=100)
        )

        assert len(result.items) <= 100
        assert result.next_cursor is not None

    @pytest.mark.asyncio
    async def test_account_type_pagination_no_overlap(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Following the pagination cursor produces non-overlapping results."""
        account_type_repo, _ = dynamodb_env

        # Create 25 account types
        for i in range(25):
            at = AccountType.reconstitute(
                account_type_id=f"at-pg-{i:03d}",
                tenant_id=TENANT_A_ID,
                name=f"PageType{i:03d}",
                description=None,
                config=None,
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await account_type_repo.save(at)

        # Page through with limit=10
        all_ids: list[str] = []
        cursor: str | None = None

        for _ in range(5):  # At most 5 pages
            result = await account_type_repo.find_all_by_tenant(
                TENANT_A_ID, PaginationParams(limit=10, cursor=cursor)
            )
            page_ids = [item.account_type_id for item in result.items]
            all_ids.extend(page_ids)
            cursor = result.next_cursor
            if cursor is None:
                break

        # All 25 items retrieved with no duplicates
        assert len(all_ids) == 25
        assert len(set(all_ids)) == 25

    @pytest.mark.asyncio
    async def test_member_pagination_bounded_and_non_overlapping(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """Member pagination respects limits and produces non-overlapping pages."""
        _, member_repo = dynamodb_env

        # Create 15 members with same account_type for GSI1 query
        for i in range(15):
            m = _make_member(
                f"mem-pg-{i:03d}", TENANT_A_ID, f"user-pg-{i:03d}",
                account_type="socio", email=f"pg{i}@x.com",
            )
            member_repo.save(m)

        # Page through with limit=5
        all_ids: list[str] = []
        cursor: str | None = None

        for _ in range(5):  # At most 5 pages
            result = member_repo.find_by_tenant_and_filters(
                TENANT_A_ID,
                MemberFilters(account_type="socio"),
                PaginationParams(limit=5, cursor=cursor),
            )
            page_ids = [item.member_id for item in result.items]
            all_ids.extend(page_ids)
            cursor = result.next_cursor
            if cursor is None:
                break

        # All 15 items retrieved with no duplicates
        assert len(all_ids) == 15
        assert len(set(all_ids)) == 15

    @pytest.mark.asyncio
    async def test_pagination_cursor_present_when_more_results(
        self,
        dynamodb_env: tuple[DynamoDBAccountTypeRepository, DynamoDBMemberRepository],
    ) -> None:
        """next_cursor is present when more results exist, absent on last page (Req 6.4)."""
        account_type_repo, _ = dynamodb_env

        # Create 5 account types
        for i in range(5):
            at = AccountType.reconstitute(
                account_type_id=f"at-cur-{i:03d}",
                tenant_id=TENANT_A_ID,
                name=f"CursorType{i}",
                description=None,
                config=None,
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await account_type_repo.save(at)

        # Request page smaller than total
        page1 = await account_type_repo.find_all_by_tenant(
            TENANT_A_ID, PaginationParams(limit=3)
        )
        assert page1.next_cursor is not None
        assert len(page1.items) == 3

        # Request remaining â€” should have no cursor
        page2 = await account_type_repo.find_all_by_tenant(
            TENANT_A_ID, PaginationParams(limit=10, cursor=page1.next_cursor)
        )
        assert len(page2.items) == 2
        assert page2.next_cursor is None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Property-Based Tests: Tenant Isolation and Pagination
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestPropertyTenantIsolation:
    """Property-based tests for tenant data isolation.

    **Property 1: Tenant Data Isolation**
    **Validates: Requirements 9.1, 9.3**
    """

    @settings(max_examples=20, deadline=10000)
    @given(
        names_a=st.lists(
            st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))),
            min_size=1,
            max_size=5,
            unique=True,
        ),
        names_b=st.lists(
            st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))),
            min_size=1,
            max_size=5,
            unique=True,
        ),
    )
    def test_tenant_queries_never_return_other_tenant_data(
        self, names_a: list[str], names_b: list[str]
    ) -> None:
        """For any set of account type names, queries for Tenant A never include Tenant B data."""
        import asyncio

        async def _run() -> None:
            with mock_aws():
                import api.common.config.dynamodbClient as dc_mod
                import api.common.config.environment as env_mod

                env_mod._config = None
                dc_mod._dynamodb_resource = None
                dc_mod._table = None

                dynamodb = boto3.resource("dynamodb", region_name=REGION)
                _create_table(dynamodb)
                _seed_tenant(dynamodb.Table(TABLE_NAME), TENANT_A_ID)
                _seed_tenant(dynamodb.Table(TABLE_NAME), TENANT_B_ID)

                repo = DynamoDBAccountTypeRepository()

                # Seed Tenant A
                for i, name in enumerate(names_a):
                    at = AccountType.reconstitute(
                        account_type_id=f"prop-a-{i}",
                        tenant_id=TENANT_A_ID,
                        name=name,
                        description=None,
                        config=None,
                        status="active",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    await repo.save(at)

                # Seed Tenant B
                for i, name in enumerate(names_b):
                    at = AccountType.reconstitute(
                        account_type_id=f"prop-b-{i}",
                        tenant_id=TENANT_B_ID,
                        name=name,
                        description=None,
                        config=None,
                        status="active",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    await repo.save(at)

                # Assert isolation
                result_a = await repo.find_all_by_tenant(TENANT_A_ID, PaginationParams(limit=100))
                result_b = await repo.find_all_by_tenant(TENANT_B_ID, PaginationParams(limit=100))

                assert all(item.tenant_id == TENANT_A_ID for item in result_a.items)
                assert all(item.tenant_id == TENANT_B_ID for item in result_b.items)
                assert len(result_a.items) == len(names_a)
                assert len(result_b.items) == len(names_b)

                # Cleanup singletons
                env_mod._config = None
                dc_mod._dynamodb_resource = None
                dc_mod._table = None

        asyncio.run(_run())


class TestPropertyPaginationBounded:
    """Property-based tests for pagination bounded responses.

    **Property 18: Pagination Bounded Response**
    **Validates: Requirements 5.4, 6.1, 6.4**
    """

    @settings(max_examples=15, deadline=15000)
    @given(
        total_items=st.integers(min_value=1, max_value=50),
        page_size=st.integers(min_value=1, max_value=100),
    )
    def test_pagination_always_returns_at_most_limit_items(
        self, total_items: int, page_size: int
    ) -> None:
        """No page ever returns more items than the specified limit."""
        import asyncio

        async def _run() -> None:
            with mock_aws():
                import api.common.config.dynamodbClient as dc_mod
                import api.common.config.environment as env_mod

                env_mod._config = None
                dc_mod._dynamodb_resource = None
                dc_mod._table = None

                dynamodb = boto3.resource("dynamodb", region_name=REGION)
                _create_table(dynamodb)

                repo = DynamoDBAccountTypeRepository()

                # Seed items
                for i in range(total_items):
                    at = AccountType.reconstitute(
                        account_type_id=f"pbt-{i:04d}",
                        tenant_id=TENANT_A_ID,
                        name=f"PBT{i:04d}",
                        description=None,
                        config=None,
                        status="active",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    await repo.save(at)

                # Page through all results
                all_ids: list[str] = []
                cursor: str | None = None

                for _ in range(total_items + 1):  # Safety bound
                    result = await repo.find_all_by_tenant(
                        TENANT_A_ID, PaginationParams(limit=page_size, cursor=cursor)
                    )
                    # Each page respects the limit
                    assert len(result.items) <= page_size

                    all_ids.extend(item.account_type_id for item in result.items)
                    cursor = result.next_cursor
                    if cursor is None:
                        break

                # All items retrieved without duplicates
                assert len(all_ids) == total_items
                assert len(set(all_ids)) == total_items

                # Cleanup singletons
                env_mod._config = None
                dc_mod._dynamodb_resource = None
                dc_mod._table = None

        asyncio.run(_run())
