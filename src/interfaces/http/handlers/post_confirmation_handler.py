"""Lambda handler for the Cognito Post Confirmation trigger.

When a user confirms their email in Cognito, this trigger fires. Per the
Account Management design (Requirement 3.2), the confirmed self-registration
must create the User, TenantMembership, Member, and default "viewer" Role
records atomically in DynamoDB, with the User status set to "active".

NOTE: This is currently a MINIMAL PLACEHOLDER. It logs the event and returns
it unchanged so Cognito completes the sign-up flow. The atomic record creation
is intentionally not implemented yet and is tracked as a TODO (see TODO.md).
Implementing it should reuse the registration domain logic / repositories in a
single DynamoDB transaction.

A Post Confirmation Lambda MUST return the (possibly unmodified) event object;
raising or returning an error would fail the user's confirmation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Cognito Post Confirmation trigger entry point.

    Args:
        event: The Cognito Post Confirmation trigger event. Relevant fields:
            - triggerSource: e.g. "PostConfirmation_ConfirmSignUp".
            - userName: the Cognito username.
            - request.userAttributes: the confirmed user's attributes (sub, email, ...).
        context: Lambda context object (unused).

    Returns:
        The event object, unchanged, so Cognito can complete the flow.
    """
    trigger_source = event.get("triggerSource", "")
    user_attributes = (event.get("request") or {}).get("userAttributes") or {}

    # Only act on the confirm-signup source (ignore e.g. forgot-password confirms).
    if trigger_source == "PostConfirmation_ConfirmSignUp":
        logger.info(
            "PostConfirmation received for sub=%s email=%s (record creation not yet implemented)",
            user_attributes.get("sub", "<unknown>"),
            user_attributes.get("email", "<unknown>"),
        )
        # TODO: create User(status="active") + TenantMembership + Member + "viewer"
        # Role atomically in DynamoDB (Requirement 3.2). Reuse registration
        # repositories/use case within a single TransactWriteItems.
    else:
        logger.info("PostConfirmation ignored for triggerSource=%s", trigger_source)

    # Always return the event so the confirmation flow succeeds.
    return event
