"""Unit tests for UserRole entity and RolePermissions class."""

from datetime import UTC, datetime

import pytest

from domain.entities.user_role import (
    PERMISSION_CREATE,
    PERMISSION_DELETE,
    PERMISSION_INVITE_MEMBERS,
    PERMISSION_MANAGE_MEMBERS,
    PERMISSION_MANAGE_ROLES,
    PERMISSION_MANAGE_USERS,
    PERMISSION_READ,
    PERMISSION_UPDATE,
    RolePermissions,
    UserRole,
    get_permissions_for_roles,
)
from domain.errors.validation_error import ValidationError


class TestRolePermissionsDefinitions:
    """Tests for RolePermissions permission sets — validates Req 10.1, 10.2, 10.3."""

    def test_admin_has_all_permissions(self) -> None:
        """Admin role grants full access (Req 10.3)."""
        expected = {
            PERMISSION_CREATE,
            PERMISSION_READ,
            PERMISSION_UPDATE,
            PERMISSION_DELETE,
            PERMISSION_MANAGE_USERS,
            PERMISSION_MANAGE_ROLES,
            PERMISSION_MANAGE_MEMBERS,
            PERMISSION_INVITE_MEMBERS,
        }
        assert RolePermissions.ADMIN_PERMISSIONS == frozenset(expected)

    def test_manager_permissions(self) -> None:
        """Manager has CRUD + manage_members but not manage_users/manage_roles/invite (Req 10.2)."""
        expected = {
            PERMISSION_CREATE,
            PERMISSION_READ,
            PERMISSION_UPDATE,
            PERMISSION_DELETE,
            PERMISSION_MANAGE_MEMBERS,
        }
        assert RolePermissions.MANAGER_PERMISSIONS == frozenset(expected)

    def test_manager_cannot_manage_users(self) -> None:
        """Manager does not have manage_users permission (Req 10.2)."""
        assert PERMISSION_MANAGE_USERS not in RolePermissions.MANAGER_PERMISSIONS

    def test_manager_cannot_manage_roles(self) -> None:
        """Manager does not have manage_roles permission (Req 10.2)."""
        assert PERMISSION_MANAGE_ROLES not in RolePermissions.MANAGER_PERMISSIONS

    def test_manager_cannot_invite_members(self) -> None:
        """Manager does not have invite_members permission."""
        assert PERMISSION_INVITE_MEMBERS not in RolePermissions.MANAGER_PERMISSIONS

    def test_viewer_read_only(self) -> None:
        """Viewer has only read permission (Req 10.1)."""
        assert RolePermissions.VIEWER_PERMISSIONS == frozenset({PERMISSION_READ})

    def test_viewer_cannot_create(self) -> None:
        """Viewer cannot perform create operations (Req 10.1)."""
        assert PERMISSION_CREATE not in RolePermissions.VIEWER_PERMISSIONS

    def test_viewer_cannot_update(self) -> None:
        """Viewer cannot perform update operations (Req 10.1)."""
        assert PERMISSION_UPDATE not in RolePermissions.VIEWER_PERMISSIONS

    def test_viewer_cannot_delete(self) -> None:
        """Viewer cannot perform delete operations (Req 10.1)."""
        assert PERMISSION_DELETE not in RolePermissions.VIEWER_PERMISSIONS


class TestRolePermissionsGetPermissions:
    """Tests for RolePermissions.get_permissions() class method."""

    def test_get_admin_permissions(self) -> None:
        """get_permissions('admin') returns admin permission set."""
        perms = RolePermissions.get_permissions("admin")
        assert perms == RolePermissions.ADMIN_PERMISSIONS

    def test_get_manager_permissions(self) -> None:
        """get_permissions('manager') returns manager permission set."""
        perms = RolePermissions.get_permissions("manager")
        assert perms == RolePermissions.MANAGER_PERMISSIONS

    def test_get_viewer_permissions(self) -> None:
        """get_permissions('viewer') returns viewer permission set."""
        perms = RolePermissions.get_permissions("viewer")
        assert perms == RolePermissions.VIEWER_PERMISSIONS

    def test_get_permissions_unknown_role_raises(self) -> None:
        """Unknown role name raises ValidationError."""
        with pytest.raises(ValidationError, match="Unknown role"):
            RolePermissions.get_permissions("superadmin")


class TestGetPermissionsForRoles:
    """Tests for get_permissions_for_roles() — validates Req 10.6."""

    def test_single_role(self) -> None:
        """Single role returns its own permissions."""
        perms = get_permissions_for_roles(["viewer"])
        assert perms == {PERMISSION_READ}

    def test_union_of_multiple_roles(self) -> None:
        """Multiple roles return the union of all permissions (Req 10.6)."""
        perms = get_permissions_for_roles(["viewer", "manager"])
        expected = RolePermissions.VIEWER_PERMISSIONS | RolePermissions.MANAGER_PERMISSIONS
        assert perms == expected

    def test_admin_and_viewer_union(self) -> None:
        """Admin + viewer union equals admin (admin is superset)."""
        perms = get_permissions_for_roles(["admin", "viewer"])
        assert perms == set(RolePermissions.ADMIN_PERMISSIONS)

    def test_empty_roles_list(self) -> None:
        """Empty roles list returns empty permission set."""
        perms = get_permissions_for_roles([])
        assert perms == set()

    def test_invalid_role_in_list_raises(self) -> None:
        """Invalid role in the list raises ValidationError."""
        with pytest.raises(ValidationError, match="Unknown role"):
            get_permissions_for_roles(["viewer", "invalid_role"])


class TestUserRoleCreate:
    """Tests for UserRole.create() factory method."""

    def test_create_with_valid_data(self) -> None:
        """Valid inputs produce a UserRole entity."""
        role = UserRole.create(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            tenant_id="660e8400-e29b-41d4-a716-446655440000",
            role_name="admin",
        )
        assert role.user_id == "550e8400-e29b-41d4-a716-446655440000"
        assert role.tenant_id == "660e8400-e29b-41d4-a716-446655440000"
        assert role.role_name == "admin"
        assert role.assigned_at is not None

    def test_create_normalizes_role_name(self) -> None:
        """Role name is normalized to lowercase."""
        role = UserRole.create(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            tenant_id="660e8400-e29b-41d4-a716-446655440000",
            role_name="  Admin  ",
        )
        assert role.role_name == "admin"

    def test_create_sets_assigned_at(self) -> None:
        """create() sets assigned_at to current time."""
        before = datetime.now(UTC)
        role = UserRole.create(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            tenant_id="660e8400-e29b-41d4-a716-446655440000",
            role_name="viewer",
        )
        after = datetime.now(UTC)
        assert before <= role.assigned_at <= after

    def test_create_with_empty_user_id_raises(self) -> None:
        """Empty user_id raises ValidationError."""
        with pytest.raises(ValidationError, match="User ID cannot be empty"):
            UserRole.create(
                user_id="",
                tenant_id="660e8400-e29b-41d4-a716-446655440000",
                role_name="admin",
            )

    def test_create_with_whitespace_user_id_raises(self) -> None:
        """Whitespace-only user_id raises ValidationError."""
        with pytest.raises(ValidationError, match="User ID cannot be empty"):
            UserRole.create(
                user_id="   ",
                tenant_id="660e8400-e29b-41d4-a716-446655440000",
                role_name="admin",
            )

    def test_create_with_empty_tenant_id_raises(self) -> None:
        """Empty tenant_id raises ValidationError."""
        with pytest.raises(ValidationError, match="Tenant ID cannot be empty"):
            UserRole.create(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                tenant_id="",
                role_name="admin",
            )

    def test_create_with_empty_role_name_raises(self) -> None:
        """Empty role_name raises ValidationError."""
        with pytest.raises(ValidationError, match="Role name cannot be empty"):
            UserRole.create(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                tenant_id="660e8400-e29b-41d4-a716-446655440000",
                role_name="",
            )

    def test_create_with_invalid_role_name_raises(self) -> None:
        """Invalid role_name raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid role name"):
            UserRole.create(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                tenant_id="660e8400-e29b-41d4-a716-446655440000",
                role_name="superadmin",
            )


class TestUserRoleReconstitute:
    """Tests for UserRole.reconstitute() method."""

    def test_reconstitute_valid(self) -> None:
        """Reconstitute builds a UserRole from persisted data."""
        now = datetime.now(UTC)
        role = UserRole.reconstitute(
            user_id="uid-1",
            tenant_id="tid-1",
            role_name="manager",
            assigned_at=now,
        )
        assert role.user_id == "uid-1"
        assert role.tenant_id == "tid-1"
        assert role.role_name == "manager"
        assert role.assigned_at == now

    def test_reconstitute_invalid_role_raises(self) -> None:
        """Reconstitute rejects invalid role name."""
        with pytest.raises(ValidationError, match="Invalid role name"):
            UserRole.reconstitute(
                user_id="uid-1",
                tenant_id="tid-1",
                role_name="unknown",
                assigned_at=datetime.now(UTC),
            )


class TestUserRolePermissions:
    """Tests for UserRole.permissions property and has_permission() method."""

    def test_admin_role_permissions_property(self) -> None:
        """Admin UserRole exposes admin permissions via property."""
        role = UserRole.create(
            user_id="uid-1",
            tenant_id="tid-1",
            role_name="admin",
        )
        assert role.permissions == RolePermissions.ADMIN_PERMISSIONS

    def test_has_permission_true(self) -> None:
        """has_permission returns True when permission is granted."""
        role = UserRole.create(
            user_id="uid-1",
            tenant_id="tid-1",
            role_name="admin",
        )
        assert role.has_permission(PERMISSION_MANAGE_USERS) is True

    def test_has_permission_false(self) -> None:
        """has_permission returns False when permission is not granted."""
        role = UserRole.create(
            user_id="uid-1",
            tenant_id="tid-1",
            role_name="viewer",
        )
        assert role.has_permission(PERMISSION_CREATE) is False


class TestUserRoleImmutability:
    """Tests for UserRole immutability."""

    def test_cannot_set_attribute(self) -> None:
        """UserRole attributes cannot be set directly."""
        role = UserRole.create(
            user_id="uid-1",
            tenant_id="tid-1",
            role_name="admin",
        )
        with pytest.raises(AttributeError, match="Cannot modify immutable"):
            role.role_name = "viewer"  # type: ignore[misc]


class TestUserRoleEquality:
    """Tests for UserRole equality and hashing."""

    def test_same_composite_key_are_equal(self) -> None:
        """UserRoles with same user_id, tenant_id, role_name are equal."""
        now = datetime.now(UTC)
        role1 = UserRole.reconstitute("uid-1", "tid-1", "admin", now)
        role2 = UserRole.reconstitute("uid-1", "tid-1", "admin", now)
        assert role1 == role2

    def test_different_role_name_not_equal(self) -> None:
        """UserRoles with different role_name are not equal."""
        now = datetime.now(UTC)
        role1 = UserRole.reconstitute("uid-1", "tid-1", "admin", now)
        role2 = UserRole.reconstitute("uid-1", "tid-1", "viewer", now)
        assert role1 != role2

    def test_hash_consistent(self) -> None:
        """Equal UserRoles have the same hash."""
        now = datetime.now(UTC)
        role1 = UserRole.reconstitute("uid-1", "tid-1", "admin", now)
        role2 = UserRole.reconstitute("uid-1", "tid-1", "admin", now)
        assert hash(role1) == hash(role2)

    def test_not_equal_to_non_user_role(self) -> None:
        """UserRole is not equal to a non-UserRole object."""
        role = UserRole.create(
            user_id="uid-1",
            tenant_id="tid-1",
            role_name="admin",
        )
        assert role != "not-a-role"
