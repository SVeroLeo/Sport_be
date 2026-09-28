"""Unit tests for the User entity ↔ DynamoDB item mapper.

Focus areas:
- Round-trip fidelity (entity → item → entity) with and without default_tenant_id.
- Backward compatibility: items persisted before default_tenant_id existed lack
  the attribute and must reconstitute to None.
- Item shape: default_tenant_id is only written when set, keeping legacy-style
  items clean.
"""

from __future__ import annotations

from datetime import UTC, datetime

from api.common.user.users import User
from api.common.user.userMapper import user_from_item, user_to_item

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_user(*, default_tenant_id: str | None) -> User:
    """Build a reconstituted User with a fixed identity and timestamps."""
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    return User.reconstitute(
        user_id="660e8400-e29b-41d4-a716-446655440111",
        email="user@example.com",
        cognito_sub="cognito-sub-xyz",
        full_name="Test User",
        status="active",
        created_at=now,
        updated_at=now,
        default_tenant_id=default_tenant_id,
    )


class TestUserToItem:
    """Tests for user_to_item()."""

    def test_maps_core_attributes(self) -> None:
        """Core attributes and key schema map onto the item."""
        user = _make_user(default_tenant_id=None)

        item = user_to_item(user)

        assert item["PK"] == "USER#user@example.com"
        assert item["SK"] == "PROFILE"
        assert item["user_id"] == "660e8400-e29b-41d4-a716-446655440111"
        assert item["email"] == "user@example.com"
        assert item["cognito_sub"] == "cognito-sub-xyz"
        assert item["full_name"] == "Test User"
        assert item["status"] == "active"
        assert item["created_at"] == "2024-01-01T12:00:00+00:00"
        assert item["updated_at"] == "2024-01-01T12:00:00+00:00"

    def test_omits_default_tenant_id_when_none(self) -> None:
        """When default_tenant_id is None, the attribute is not written."""
        user = _make_user(default_tenant_id=None)

        item = user_to_item(user)

        assert "default_tenant_id" not in item

    def test_writes_default_tenant_id_when_set(self) -> None:
        """When default_tenant_id is set, it is persisted on the item."""
        user = _make_user(default_tenant_id=TENANT_ID)

        item = user_to_item(user)

        assert item["default_tenant_id"] == TENANT_ID


class TestUserFromItem:
    """Tests for user_from_item()."""

    def test_reconstitutes_core_attributes(self) -> None:
        """A well-formed item reconstitutes into a matching User."""
        item = {
            "PK": "USER#user@example.com",
            "SK": "PROFILE",
            "user_id": "660e8400-e29b-41d4-a716-446655440111",
            "email": "user@example.com",
            "cognito_sub": "cognito-sub-xyz",
            "full_name": "Test User",
            "status": "active",
            "created_at": "2024-01-01T12:00:00+00:00",
            "updated_at": "2024-01-01T12:00:00+00:00",
            "default_tenant_id": TENANT_ID,
        }

        user = user_from_item(item)

        assert user.user_id == "660e8400-e29b-41d4-a716-446655440111"
        assert user.email.value == "user@example.com"
        assert user.cognito_sub == "cognito-sub-xyz"
        assert user.full_name.value == "Test User"
        assert user.status == "active"
        assert user.default_tenant_id == TENANT_ID

    def test_missing_default_tenant_id_reconstitutes_to_none(self) -> None:
        """Legacy items without default_tenant_id tolerate the missing attribute."""
        item = {
            "PK": "USER#user@example.com",
            "SK": "PROFILE",
            "user_id": "660e8400-e29b-41d4-a716-446655440111",
            "email": "user@example.com",
            "cognito_sub": "cognito-sub-xyz",
            "full_name": "Test User",
            "status": "active",
            "created_at": "2024-01-01T12:00:00+00:00",
            "updated_at": "2024-01-01T12:00:00+00:00",
        }

        user = user_from_item(item)

        assert user.default_tenant_id is None


class TestUserRoundTrip:
    """Round-trip fidelity: entity → item → entity."""

    def test_round_trip_with_default_tenant_id(self) -> None:
        """A user with default_tenant_id survives a round-trip unchanged."""
        original = _make_user(default_tenant_id=TENANT_ID)

        restored = user_from_item(user_to_item(original))

        assert restored.user_id == original.user_id
        assert restored.email.value == original.email.value
        assert restored.cognito_sub == original.cognito_sub
        assert restored.full_name.value == original.full_name.value
        assert restored.status == original.status
        assert restored.created_at == original.created_at
        assert restored.updated_at == original.updated_at
        assert restored.default_tenant_id == original.default_tenant_id

    def test_round_trip_without_default_tenant_id(self) -> None:
        """A user without default_tenant_id survives a round-trip as None."""
        original = _make_user(default_tenant_id=None)

        restored = user_from_item(user_to_item(original))

        assert restored.user_id == original.user_id
        assert restored.default_tenant_id is None
