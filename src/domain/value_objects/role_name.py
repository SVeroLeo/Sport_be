"""RoleName value object — constrained to admin, manager, viewer."""

from __future__ import annotations

from domain.errors.validation_error import ValidationError

_VALID_ROLES = frozenset({"admin", "manager", "viewer"})


class RoleName:
    """Immutable value object representing a role name.

    Must be exactly one of: "admin", "manager", "viewer".
    Input is case-insensitive; stored value is always lowercase.
    """

    __slots__ = ("_value",)
    _value: str

    ADMIN: RoleName
    MANAGER: RoleName
    VIEWER: RoleName

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", value)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    @property
    def value(self) -> str:
        return self._value

    @staticmethod
    def create(value: str) -> RoleName:
        """Create a RoleName from a string, validating it is one of the allowed roles."""
        if not value or not value.strip():
            raise ValidationError("Invalid role name", field="role_name")
        normalized = value.strip().lower()
        if normalized not in _VALID_ROLES:
            raise ValidationError(
                f"Invalid role name: must be one of {sorted(_VALID_ROLES)}",
                field="role_name",
            )
        return RoleName(normalized)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RoleName):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"RoleName({self._value!r})"

    def __str__(self) -> str:
        return self._value


# Class-level constants for convenience
RoleName.ADMIN = RoleName("admin")
RoleName.MANAGER = RoleName("manager")
RoleName.VIEWER = RoleName("viewer")
