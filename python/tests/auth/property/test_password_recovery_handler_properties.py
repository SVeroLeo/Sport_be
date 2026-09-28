"""Property-based test for the auth_handler non-POST method handling.

**Validates: Requirements 4.5**

Property tested (see design.md "Correctness Properties"):
- Property 7: Non-POST method yields 405 with Allow: POST

The handler is exercised with a mocked container (get_container patched) so that
no controller method may be invoked on the rejected non-POST path.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import hypothesis.strategies as st
from hypothesis import given, settings

from api.auth import authHandler as auth_handler

# ─── Strategies ───────────────────────────────────────────────────────────────

# Any HTTP method other than POST (case-insensitive: the handler upper-cases).
non_post_methods = st.sampled_from(
    ["GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "get", "Delete", ""]
)

auth_resources = st.sampled_from(
    [
        "/auth/forgot-password",
        "/auth/confirm-forgot-password",
        "/auth/respond-to-challenge",
    ]
)


# ─── Property 7: Non-POST method yields 405 with Allow: POST ───────────────────


# Feature: password-recovery-challenge, Property 7: Non-POST method yields 405 with Allow POST
class TestProperty7NonPost405:
    """Property 7 — Non-POST method yields 405 with Allow: POST.

    For any HTTP method other than POST over any of the three recovery/challenge
    resources, the handler responds 405 with an Allow: POST header and body
    {"error": <non-empty>}, and no controller method is invoked.

    **Validates: Requirements 4.5**
    """

    @given(method=non_post_methods, resource=auth_resources)
    @settings(max_examples=200)
    def test_non_post_returns_405_allow_post_no_controller_call(
        self, method: str, resource: str
    ) -> None:
        """**Validates: Requirements 4.5**"""
        # A controller whose every method, if touched, would flag the failure.
        controller = MagicMock()
        container = MagicMock()
        container.auth_controller = controller

        event: dict[str, Any] = {
            "httpMethod": method,
            "resource": resource,
            "body": json.dumps({"email": "user@example.com"}),
        }

        with patch(
            "api.common.compositionRoot.get_container", return_value=container
        ):
            resp = auth_handler.handler(event, context=None)

        assert resp["statusCode"] == 405
        assert resp["headers"]["Allow"] == "POST"

        body = json.loads(resp["body"])
        assert set(body.keys()) == {"error"}
        assert isinstance(body["error"], str) and len(body["error"]) >= 1

        # No controller method was invoked on the rejected non-POST path.
        controller.handle_forgot_password.assert_not_called()
        controller.handle_confirm_forgot_password.assert_not_called()
        controller.handle_respond_to_challenge.assert_not_called()
        controller.handle_login.assert_not_called()
        controller.handle_refresh.assert_not_called()
        controller.handle_logout.assert_not_called()
