"""Lambda handler for the Cognito Post Confirmation trigger.

When a user confirms their email in Cognito, this trigger fires. Per the
Account Management design (Requirement 3.2), the confirmed self-registration
creates the User, TenantMembership, Member, and default "viewer" Role
records atomically in DynamoDB, with the User status set to "active".

The tenant_id and account_type are read from the Cognito custom attributes
stored during sign_up (custom:tenant_id, custom:account_type).

A Post Confirmation Lambda MUST return the (possibly unmodified) event object;
raising or returning an error would fail the user's confirmation.

Design notes:
- Does NOT use the composition_root (get_container()) because the
  PostConfirmationFn has different env vars than the other Lambdas —
  it intentionally has no COGNITO_USER_POOL_ID to avoid a CDK circular
  dependency. Repositories are wired directly here.
- The Member entity requires account_type_id (a UUID). When the resolved
  account_type exists in DynamoDB we use its id; otherwise we generate a
  sentinel UUID so the atomic write never fails silently.
- Idempotency: the User Put uses attribute_not_exists(PK) so re-invocations
  (e.g. Cognito retry) are safe — subsequent calls are no-ops.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ──── Lazy singletons (reused across warm invocations) ────────────────────────

_user_repository: Any = None
_account_type_repository: Any = None


def _get_repositories() -> tuple[Any, Any]:
    """Return the singleton repository instances, creating them on cold start."""
    global _user_repository, _account_type_repository  # noqa: PLW0603
    if _user_repository is None:
        from infrastructure.persistence.dynamodb_user_repository import (
            DynamoDBUserRepository,
        )
        from infrastructure.persistence.dynamodb_account_type_repository import (
            DynamoDBAccountTypeRepository,
        )
        _user_repository = DynamoDBUserRepository()
        _account_type_repository = DynamoDBAccountTypeRepository()
    return _user_repository, _account_type_repository


# ──── Handler ─────────────────────────────────────────────────────────────────


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Cognito Post Confirmation trigger entry point.

    Creates User + TenantMembership + Member + viewer Role atomically in
    DynamoDB when a self-registered user confirms their email.

    Args:
        event: The Cognito Post Confirmation trigger event. Relevant fields:
            - triggerSource: e.g. "PostConfirmation_ConfirmSignUp".
            - request.userAttributes: the confirmed user's attributes.
              Expected custom attributes: custom:tenant_id, custom:account_type.
        context: Lambda context object (unused).

    Returns:
        The event object, unchanged, so Cognito can complete the flow.
    """
    trigger_source = event.get("triggerSource", "")

    if trigger_source != "PostConfirmation_ConfirmSignUp":
        logger.info("PostConfirmation ignored for triggerSource=%s", trigger_source)
        return event

    user_attributes = (event.get("request") or {}).get("userAttributes") or {}

    cognito_sub = user_attributes.get("sub", "")
    email = user_attributes.get("email", "")
    full_name = user_attributes.get("name", "") or email.split("@")[0]
    tenant_id = user_attributes.get("custom:tenant_id", "")
    account_type = user_attributes.get("custom:account_type", "usuario")

    logger.info(
        "PostConfirmation: sub=%s email=%s tenant_id=%s account_type=%s",
        cognito_sub,
        email,
        tenant_id,
        account_type,
    )

    if not cognito_sub or not email or not tenant_id:
        logger.error(
            "PostConfirmation: missing required attributes — sub=%s email=%s tenant_id=%s. "
            "Skipping record creation to avoid blocking confirmation.",
            cognito_sub,
            email,
            tenant_id,
        )
        return event

    try:
        _create_user_records(
            cognito_sub=cognito_sub,
            email=email,
            full_name=full_name,
            tenant_id=tenant_id,
            account_type=account_type,
        )
        logger.info(
            "PostConfirmation: records created for sub=%s tenant_id=%s",
            cognito_sub,
            tenant_id,
        )
    except Exception:
        # Log but do NOT re-raise: raising here would fail the user's confirmation
        # in Cognito, making recovery very difficult. The missing records can be
        # repaired via an admin script.
        logger.exception(
            "PostConfirmation: failed to create DynamoDB records for sub=%s. "
            "User confirmation succeeded in Cognito but DB records are missing.",
            cognito_sub,
        )

    return event


# ──── Internal helpers ────────────────────────────────────────────────────────


def _create_user_records(
    *,
    cognito_sub: str,
    email: str,
    full_name: str,
    tenant_id: str,
    account_type: str,
) -> None:
    """Create User + TenantMembership + Member + viewer Role atomically.

    Resolves the account_type_id from DynamoDB when available;
    falls back to a generated UUID sentinel so the transaction never
    silently skips the record.

    Args:
        cognito_sub: Cognito sub attribute (used as cognito_sub on User).
        email: User's email address.
        full_name: User's full name.
        tenant_id: UUID of the tenant the user registered into.
        account_type: Resolved account type name (e.g. "usuario").
    """
    from domain.entities.member import Member
    from domain.entities.tenant_membership import TenantMembership
    from domain.entities.user import User
    from domain.entities.user_role import UserRole

    user_repo, account_type_repo = _get_repositories()

    # Resolve account_type_id — best-effort, fall back to sentinel UUID.
    account_type_id = _resolve_account_type_id(
        account_type_repo=account_type_repo,
        tenant_id=tenant_id,
        account_type=account_type,
    )

    # Build domain entities
    user = User.create(
        email=email,
        cognito_sub=cognito_sub,
        full_name=full_name,
        status="active",
        default_tenant_id=tenant_id,
    )
    membership = TenantMembership.create(
        user_id=user.user_id,
        tenant_id=tenant_id,
    )
    member = Member.create(
        tenant_id=tenant_id,
        user_id=user.user_id,
        account_type=account_type,
        account_type_id=account_type_id,
        full_name=full_name,
        email=email,
        registration_type="self",
        status="active",
    )
    role = UserRole.create(
        user_id=user.user_id,
        tenant_id=tenant_id,
        role_name="viewer",
    )

    # Atomic write: User + TenantMembership + Member + Role
    user_repo.register_with_membership(
        user=user,
        membership=membership,
        member=member,
        role=role,
    )


def _resolve_account_type_id(
    *,
    account_type_repo: Any,
    tenant_id: str,
    account_type: str,
) -> str:
    """Resolve the account_type_id UUID for the given account type name.

    Queries DynamoDB synchronously. Falls back to a generated sentinel UUID
    if the account type is not found, so the atomic write proceeds without
    blocking the confirmation flow.

    Args:
        account_type_repo: DynamoDBAccountTypeRepository instance.
        tenant_id: UUID of the tenant to search within.
        account_type: Account type name to look up.

    Returns:
        The account_type_id UUID string (real or sentinel).
    """
    import asyncio

    try:
        result = asyncio.run(
            account_type_repo.find_by_name_in_tenant(
                tenant_id=tenant_id,
                name=account_type,
            )
        )
        if result is not None:
            return result.account_type_id
    except Exception:
        logger.warning(
            "PostConfirmation: could not resolve account_type_id for "
            "tenant=%s account_type=%s — using sentinel UUID",
            tenant_id,
            account_type,
            exc_info=True,
        )

    # Sentinel: deterministic UUID derived from tenant + account_type so the
    # same user re-triggering gets the same value (idempotency-friendly).
    sentinel = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{account_type}"))
    logger.info(
        "PostConfirmation: using sentinel account_type_id=%s for account_type=%s",
        sentinel,
        account_type,
    )
    return sentinel
