"""Unit tests for RoleGuard middleware — validates Requirements 10.1, 10.2, 10.3, 10.5, 10.6."""

import json

import pytest

from domain.entities.user_role import (
    PERMISSION_CREATE,
    PERMISSION_DELETE,
    PERMISSION_MANAGE_MEMBERS,
    PERMISSION_MANAGE_ROLES,
    PERMISSION_MANAGE_USERS,
    PERMISSION_READ,
    PERMISSION_UPDATE,
)
from interfaces.http.middleware.role_guard_middleware import (
    check_permission,
    require_permission,
)
from interfaces.http.middleware.tenant_guard_middleware import TenantContext


def _make_context(roles: list[str]) -> TenantContext:
    """Helper to build a TenantContext with the given roles."""
    return TenantContext(
        user_id="user-123",
        tenant_id="tenant-456",
        roles=roles,
        email="user@example.com",
    )


class TestCheckPermissionViewerRole:
    """Viewer role should only have read access (Req 10.1)."""

    def test_viewer_can_read(self) -> None:
        """Viewer has read permission."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_READ)
        assert result is None

    def test_viewer_cannot_create(self) -> None:
        """Viewer cannot create (Req 10.1)."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_CREATE)
        assert result is not None
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["message"] == "Insufficient permissions"

    def test_viewer_cannot_update(self) -> None:
        """Viewer cannot update (Req 10.1)."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_UPDATE)
        assert result is not None
        assert result["statusCode"] == 403

    def test_viewer_cannot_delete(self) -> None:
        """Viewer cannot delete (Req 10.1)."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_DELETE)
        assert result is not None
        assert result["statusCode"] == 403

    def test_viewer_cannot_manage_members(self) -> None:
        """Viewer cannot manage members."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_MANAGE_MEMBERS)
        assert result is not None
        assert result["statusCode"] == 403


class TestCheckPermissionManagerRole:
    """Manager role has CRUD + manage_members but not manage_users/manage_roles (Req 10.2)."""

    def test_manager_can_read(self) -> None:
        """Manager has read permission."""
        ctx = _make_context(["manager"])
        result = check_permission(ctx, PERMISSION_READ)
        assert result is None

    def test_manager_can_create(self) -> None:
        """Manager can create."""
        ctx = _make_context(["manager"])
        result = check_permission(ctx, PERMISSION_CREATE)
        assert result is None

    def test_manager_can_update(self) -> None:
        """Manager can update."""
        ctx = _make_context(["manager"])
        result = check_permission(ctx, PERMISSION_UPDATE)
        assert result is None

    def test_manager_can_delete(self) -> None:
        """Manager can delete (basic delete permission, e.g. account types they own)."""
        ctx = _make_context(["manager"])
        result = check_permission(ctx, PERMISSION_DELETE)
        assert result is None

    def test_manager_can_manage_members(self) -> None:
        """Manager can manage members (but not deactivate — handled by use case)."""
        ctx = _make_context(["manager"])
        result = check_permission(ctx, PERMISSION_MANAGE_MEMBERS)
        assert result is None

    def test_manager_cannot_manage_users(self) -> None:
        """Manager cannot manage_users (Req 10.2)."""
        ctx = _make_context(["manager"])
        result = check_permission(ctx, PERMISSION_MANAGE_USERS)
        assert result is not None
        assert result["statusCode"] == 403

    def test_manager_cannot_manage_roles(self) -> None:
        """Manager cannot manage_roles (Req 10.2)."""
        ctx = _make_context(["manager"])
        result = check_permission(ctx, PERMISSION_MANAGE_ROLES)
        assert result is not None
        assert result["statusCode"] == 403


class TestCheckPermissionAdminRole:
    """Admin role has all permissions (Req 10.3)."""

    def test_admin_can_read(self) -> None:
        ctx = _make_context(["admin"])
        assert check_permission(ctx, PERMISSION_READ) is None

    def test_admin_can_create(self) -> None:
        ctx = _make_context(["admin"])
        assert check_permission(ctx, PERMISSION_CREATE) is None

    def test_admin_can_update(self) -> None:
        ctx = _make_context(["admin"])
        assert check_permission(ctx, PERMISSION_UPDATE) is None

    def test_admin_can_delete(self) -> None:
        ctx = _make_context(["admin"])
        assert check_permission(ctx, PERMISSION_DELETE) is None

    def test_admin_can_manage_users(self) -> None:
        ctx = _make_context(["admin"])
        assert check_permission(ctx, PERMISSION_MANAGE_USERS) is None

    def test_admin_can_manage_roles(self) -> None:
        ctx = _make_context(["admin"])
        assert check_permission(ctx, PERMISSION_MANAGE_ROLES) is None

    def test_admin_can_manage_members(self) -> None:
        ctx = _make_context(["admin"])
        assert check_permission(ctx, PERMISSION_MANAGE_MEMBERS) is None


class TestCheckPermissionMultipleRoles:
    """Multiple roles apply union of permissions — least restrictive (Req 10.6)."""

    def test_viewer_and_manager_can_create(self) -> None:
        """Union of viewer + manager grants create permission."""
        ctx = _make_context(["viewer", "manager"])
        result = check_permission(ctx, PERMISSION_CREATE)
        assert result is None

    def test_viewer_and_manager_cannot_manage_users(self) -> None:
        """Union of viewer + manager still lacks manage_users."""
        ctx = _make_context(["viewer", "manager"])
        result = check_permission(ctx, PERMISSION_MANAGE_USERS)
        assert result is not None
        assert result["statusCode"] == 403

    def test_viewer_and_admin_has_all_permissions(self) -> None:
        """Union of viewer + admin grants everything (admin is superset)."""
        ctx = _make_context(["viewer", "admin"])
        assert check_permission(ctx, PERMISSION_MANAGE_USERS) is None
        assert check_permission(ctx, PERMISSION_MANAGE_ROLES) is None
        assert check_permission(ctx, PERMISSION_DELETE) is None

    def test_empty_roles_deny_everything(self) -> None:
        """No roles means no permissions (Req 10.5)."""
        ctx = _make_context([])
        result = check_permission(ctx, PERMISSION_READ)
        assert result is not None
        assert result["statusCode"] == 403


class TestRequirePermissionFactory:
    """Tests for require_permission() factory function — composable middleware."""

    def test_returns_callable(self) -> None:
        """require_permission returns a callable guard."""
        guard = require_permission(PERMISSION_READ)
        assert callable(guard)

    def test_guard_allows_with_permission(self) -> None:
        """Guard returns None when user has the permission."""
        guard = require_permission(PERMISSION_READ)
        ctx = _make_context(["viewer"])
        assert guard(ctx) is None

    def test_guard_denies_without_permission(self) -> None:
        """Guard returns 403 response when user lacks the permission."""
        guard = require_permission(PERMISSION_CREATE)
        ctx = _make_context(["viewer"])
        result = guard(ctx)
        assert result is not None
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["message"] == "Insufficient permissions"

    def test_guard_composable_with_different_permissions(self) -> None:
        """Multiple guards can be composed for different permissions."""
        read_guard = require_permission(PERMISSION_READ)
        write_guard = require_permission(PERMISSION_CREATE)

        ctx = _make_context(["viewer"])
        assert read_guard(ctx) is None
        assert write_guard(ctx) is not None


class TestForbiddenResponseFormat:
    """Validate the 403 response structure."""

    def test_response_has_status_code(self) -> None:
        """Response includes statusCode 403."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_DELETE)
        assert result is not None
        assert result["statusCode"] == 403

    def test_response_has_content_type_header(self) -> None:
        """Response includes Content-Type header."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_DELETE)
        assert result is not None
        assert result["headers"]["Content-Type"] == "application/json"

    def test_response_body_is_json(self) -> None:
        """Response body is valid JSON with message field."""
        ctx = _make_context(["viewer"])
        result = check_permission(ctx, PERMISSION_DELETE)
        assert result is not None
        body = json.loads(result["body"])
        assert "message" in body
        assert body["message"] == "Insufficient permissions"


class TestTenantContextDataclass:
    """Tests for the TenantContext dataclass."""

    def test_create_tenant_context(self) -> None:
        """TenantContext can be created with all required fields."""
        ctx = TenantContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["admin"],
            email="admin@example.com",
        )
        assert ctx.user_id == "user-1"
        assert ctx.tenant_id == "tenant-1"
        assert ctx.roles == ["admin"]
        assert ctx.email == "admin@example.com"

    def test_tenant_context_is_frozen(self) -> None:
        """TenantContext is immutable (frozen dataclass)."""
        ctx = TenantContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["admin"],
            email="admin@example.com",
        )
        with pytest.raises(AttributeError):
            ctx.user_id = "modified"  # type: ignore[misc]
