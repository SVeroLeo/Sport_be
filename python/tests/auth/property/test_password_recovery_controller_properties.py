"""Property-based tests for the password-recovery & challenge AuthController handlers.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4,
2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9,
4.1, 4.4, 4.6**

Properties tested (see design.md "Correctness Properties"):
- Property 1: Anti-enumeration of forgot-password
- Property 2: Input validation without side effect (and single call on valid input)
- Property 3: XOR distinguishability of respond-to-challenge
- Property 4: Error shape and no sensitive-material leak
- Property 5: confirm-forgot-password success has no tokens
- Property 6: DomainError -> HTTP status mapping

The AuthController is exercised directly with a mocked ICognitoService
(AsyncMock for the recovery/challenge methods). Async handlers are driven with
``asyncio.run`` inside synchronous Hypothesis tests, mirroring how the Lambda
handler runs the coroutines.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
from hypothesis import assume, given, settings

from api.auth.respondToChallengeInputDto import SUPPORTED_CHALLENGES
from api.auth.challengeResult import ChallengeResult
from api.auth.tokenPair import TokenPair
from api.common.errors.domainError import DomainError
from api.common.errors.invalidCredentialsError import InvalidCredentialsError
from api.common.errors.rateLimitError import RateLimitError
from api.common.errors.validationError import ValidationError
from api.auth.authController import AuthController

# ─── Constants & strategies ───────────────────────────────────────────────────

TOKEN_KEYS = ("access_token", "id_token", "refresh_token")
NEXT_CHALLENGE_KEYS = ("challenge_name", "session")


def _make_controller() -> tuple[AuthController, MagicMock]:
    """Build an AuthController with a fully mocked cognito service.

    Returns:
        (controller, cognito_service_mock). The three recovery/challenge
        methods are AsyncMock instances so they can be awaited.
    """
    login_use_case = MagicMock()
    cognito_service = MagicMock()
    cognito_service.forgot_password = AsyncMock(return_value=None)
    cognito_service.confirm_forgot_password = AsyncMock(return_value=None)
    cognito_service.respond_to_challenge = AsyncMock()
    controller = AuthController(login_use_case, cognito_service)
    return controller, cognito_service


def _event(body: Any) -> dict[str, Any]:
    """Wrap a body value as an API Gateway proxy event.

    A dict/list body is JSON-encoded; a str is passed through; None yields a
    missing body.
    """
    if body is None:
        return {"httpMethod": "POST"}
    if isinstance(body, str):
        return {"httpMethod": "POST", "body": body}
    return {"httpMethod": "POST", "body": json.dumps(body)}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# Syntactically valid emails: single '@', non-empty local/domain, total 3..254.
_local = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=40,
)
_domain_label = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=20,
)


@st.composite
def valid_emails(draw: st.DrawFn) -> str:
    """Generate syntactically valid emails per the DTO rules."""
    local = draw(_local)
    dom1 = draw(_domain_label)
    tld = draw(st.sampled_from(["com", "org", "net", "io", "es"]))
    email = f"{local}@{dom1}.{tld}"
    assume(3 <= len(email) <= 254)
    return email


valid_codes = st.text(min_size=1, max_size=64).filter(lambda s: s.strip() != "")
valid_passwords = st.text(min_size=1, max_size=64).filter(lambda s: s.strip() != "")
valid_sessions = st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != "")
challenge_names = st.sampled_from(sorted(SUPPORTED_CHALLENGES))
challenge_responses = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=st.text(min_size=0, max_size=40),
    min_size=1,
    max_size=5,
)


# ─── Property 1: Anti-enumeration of forgot-password ───────────────────────────


# Feature: password-recovery-challenge, Property 1: Anti-enumeration of forgot-password
class TestProperty1AntiEnumeration:
    """Property 1 — Anti-enumeration of forgot-password.

    For any syntactically valid email, the HTTP response (statusCode + serialized
    body) of handle_forgot_password is byte-identical whether the Cognito service
    completes normally (registered email) or the adapter swallowed a
    UserNotFoundException (unregistered email), and in both cases it is 200.

    **Validates: Requirements 1.2, 1.3**
    """

    @given(email=valid_emails())
    @settings(max_examples=200)
    def test_forgot_password_response_is_byte_identical_and_200(self, email: str) -> None:
        """**Validates: Requirements 1.2, 1.3**"""
        # Case A — registered email: adapter returns None (success).
        controller_a, service_a = _make_controller()
        service_a.forgot_password = AsyncMock(return_value=None)
        resp_a = _run(controller_a.handle_forgot_password(_event({"email": email})))

        # Case B — unregistered email: adapter also swallows UserNotFound -> None.
        controller_b, service_b = _make_controller()
        service_b.forgot_password = AsyncMock(return_value=None)
        resp_b = _run(controller_b.handle_forgot_password(_event({"email": email})))

        assert resp_a["statusCode"] == 200
        assert resp_b["statusCode"] == 200
        # Byte-identical status + body.
        assert resp_a["statusCode"] == resp_b["statusCode"]
        assert resp_a["body"] == resp_b["body"]


# ─── Property 2: Input validation without side effect ──────────────────────────


# Feature: password-recovery-challenge, Property 2: Input validation without side effect
class TestProperty2InputValidation:
    """Property 2 — Input validation without side effect (single call on valid input).

    For any invalid body per endpoint (missing body, non-dict body, empty/whitespace
    fields, malformed email, unsupported challenge_name, empty challenge_responses),
    the controller responds 400 with body {"error": <non-empty str>} and does NOT
    call the cognito service. For valid inputs, the corresponding service method is
    called exactly once.

    **Validates: Requirements 1.1, 1.4, 1.5, 2.1, 2.4, 2.5, 2.6, 3.1, 3.4, 3.5, 3.6**
    """

    @staticmethod
    def _assert_400_no_call(resp: dict[str, Any], method: AsyncMock) -> None:
        assert resp["statusCode"] == 400
        parsed = json.loads(resp["body"])
        assert set(parsed.keys()) == {"error"}
        assert isinstance(parsed["error"], str) and len(parsed["error"]) >= 1
        method.assert_not_called()

    # ---- forgot-password ----

    @given(
        email=st.one_of(
            st.just(""),
            st.text(alphabet=" \t\n", min_size=1, max_size=5),  # whitespace-only
            st.text(min_size=1, max_size=10).filter(lambda s: "@" not in s),  # no @
            st.just("a@b@c.com"),  # two @
            st.just("@domain.com"),  # empty local
            st.just("local@"),  # empty domain
        ),
    )
    @settings(max_examples=200)
    def test_forgot_password_invalid_email_400_no_call(self, email: str) -> None:
        """**Validates: Requirements 1.4, 1.5**"""
        controller, service = _make_controller()
        resp = _run(controller.handle_forgot_password(_event({"email": email})))
        self._assert_400_no_call(resp, service.forgot_password)

    @given(
        body=st.one_of(
            st.none(),  # missing body
            st.just("not-json{"),  # malformed JSON
            st.just("[1, 2, 3]"),  # top-level not an object
            st.just("42"),  # top-level scalar
        ),
    )
    @settings(max_examples=200)
    def test_forgot_password_bad_body_400_no_call(self, body: Any) -> None:
        """**Validates: Requirements 1.4**"""
        controller, service = _make_controller()
        resp = _run(controller.handle_forgot_password(_event(body)))
        self._assert_400_no_call(resp, service.forgot_password)

    @given(email=valid_emails())
    @settings(max_examples=200)
    def test_forgot_password_valid_calls_service_once(self, email: str) -> None:
        """**Validates: Requirements 1.1**"""
        controller, service = _make_controller()
        resp = _run(controller.handle_forgot_password(_event({"email": email})))
        assert resp["statusCode"] == 200
        service.forgot_password.assert_awaited_once_with(email)

    # ---- confirm-forgot-password ----

    @given(
        data=st.fixed_dictionaries(
            {
                "email": valid_emails(),
                "confirmation_code": valid_codes,
                "new_password": valid_passwords,
            }
        ),
        drop=st.sampled_from(["email", "confirmation_code", "new_password"]),
        blank=st.sampled_from(["", "   ", "\t"]),
    )
    @settings(max_examples=200)
    def test_confirm_missing_or_blank_field_400_no_call(
        self, data: dict[str, str], drop: str, blank: str
    ) -> None:
        """**Validates: Requirements 2.5, 2.6**"""
        controller, service = _make_controller()
        body = dict(data)
        body[drop] = blank  # blank out a required field
        resp = _run(controller.handle_confirm_forgot_password(_event(body)))
        self._assert_400_no_call(resp, service.confirm_forgot_password)

    @given(
        body=st.one_of(st.none(), st.just("nope{"), st.just("true"), st.just('"x"')),
    )
    @settings(max_examples=200)
    def test_confirm_bad_body_400_no_call(self, body: Any) -> None:
        """**Validates: Requirements 2.4**"""
        controller, service = _make_controller()
        resp = _run(controller.handle_confirm_forgot_password(_event(body)))
        self._assert_400_no_call(resp, service.confirm_forgot_password)

    @given(
        email=valid_emails(),
        code=valid_codes,
        password=valid_passwords,
    )
    @settings(max_examples=200)
    def test_confirm_valid_calls_service_once(
        self, email: str, code: str, password: str
    ) -> None:
        """**Validates: Requirements 2.1**"""
        controller, service = _make_controller()
        resp = _run(
            controller.handle_confirm_forgot_password(
                _event(
                    {
                        "email": email,
                        "confirmation_code": code,
                        "new_password": password,
                    }
                )
            )
        )
        assert resp["statusCode"] == 200
        # Exactly one delegated call with the parsed values.
        service.confirm_forgot_password.assert_awaited_once()
        args = service.confirm_forgot_password.await_args.args
        assert args[0] == email
        assert args[2] == password

    # ---- respond-to-challenge ----

    @given(
        name=st.text(min_size=1, max_size=20).filter(lambda s: s not in SUPPORTED_CHALLENGES),
        session=valid_sessions,
        responses=challenge_responses,
    )
    @settings(max_examples=200)
    def test_respond_unsupported_challenge_name_400_no_call(
        self, name: str, session: str, responses: dict[str, str]
    ) -> None:
        """**Validates: Requirements 3.6**"""
        controller, service = _make_controller()
        resp = _run(
            controller.handle_respond_to_challenge(
                _event(
                    {
                        "challenge_name": name,
                        "session": session,
                        "challenge_responses": responses,
                    }
                )
            )
        )
        self._assert_400_no_call(resp, service.respond_to_challenge)

    @given(
        name=challenge_names,
        session=st.sampled_from(["", "   ", "\t"]),
        responses=challenge_responses,
    )
    @settings(max_examples=200)
    def test_respond_empty_session_400_no_call(
        self, name: str, session: str, responses: dict[str, str]
    ) -> None:
        """**Validates: Requirements 3.5**"""
        controller, service = _make_controller()
        resp = _run(
            controller.handle_respond_to_challenge(
                _event(
                    {
                        "challenge_name": name,
                        "session": session,
                        "challenge_responses": responses,
                    }
                )
            )
        )
        self._assert_400_no_call(resp, service.respond_to_challenge)

    @given(
        name=challenge_names,
        session=valid_sessions,
        responses=st.one_of(
            st.just({}),  # empty map
            st.lists(st.integers(), min_size=1, max_size=3),  # not a map
            st.text(min_size=1, max_size=5),  # not a map
        ),
    )
    @settings(max_examples=200)
    def test_respond_invalid_responses_400_no_call(
        self, name: str, session: str, responses: Any
    ) -> None:
        """**Validates: Requirements 3.5**"""
        controller, service = _make_controller()
        resp = _run(
            controller.handle_respond_to_challenge(
                _event(
                    {
                        "challenge_name": name,
                        "session": session,
                        "challenge_responses": responses,
                    }
                )
            )
        )
        self._assert_400_no_call(resp, service.respond_to_challenge)

    @given(
        body=st.one_of(st.none(), st.just("bad{"), st.just("[1,2]"), st.just("null")),
    )
    @settings(max_examples=200)
    def test_respond_bad_body_400_no_call(self, body: Any) -> None:
        """**Validates: Requirements 3.4**"""
        controller, service = _make_controller()
        resp = _run(controller.handle_respond_to_challenge(_event(body)))
        self._assert_400_no_call(resp, service.respond_to_challenge)

    @given(
        name=challenge_names,
        session=valid_sessions,
        responses=challenge_responses,
    )
    @settings(max_examples=200)
    def test_respond_valid_calls_service_once(
        self, name: str, session: str, responses: dict[str, str]
    ) -> None:
        """**Validates: Requirements 3.1**"""
        controller, service = _make_controller()
        service.respond_to_challenge = AsyncMock(
            return_value=ChallengeResult.next_challenge("SMS_MFA", "next-session")
        )
        resp = _run(
            controller.handle_respond_to_challenge(
                _event(
                    {
                        "challenge_name": name,
                        "session": session,
                        "challenge_responses": responses,
                    }
                )
            )
        )
        assert resp["statusCode"] == 200
        service.respond_to_challenge.assert_awaited_once_with(name, session.strip(), responses)


# ─── Property 3: XOR distinguishability of respond-to-challenge ────────────────


# Feature: password-recovery-challenge, Property 3: XOR distinguishability of respond-to-challenge
class TestProperty3XorDistinguishability:
    """Property 3 — XOR distinguishability of respond-to-challenge.

    For any success ChallengeResult, the response body contains EXACTLY ONE of
    the field sets {access_token, id_token, refresh_token, expires_in} XOR
    {challenge_name, session}; never both and never neither. Status is always
    200 and the authenticated case has no challenge_name key.

    **Validates: Requirements 3.2, 3.3**
    """

    @given(
        authenticated=st.booleans(),
        access_token=st.text(min_size=1, max_size=40),
        id_token=st.text(min_size=1, max_size=40),
        refresh_token=st.text(min_size=1, max_size=40),
        expires_in=st.integers(min_value=1, max_value=100000),
        next_name=challenge_names,
        next_session=valid_sessions,
    )
    @settings(max_examples=200)
    def test_exactly_one_field_set_present(
        self,
        authenticated: bool,
        access_token: str,
        id_token: str,
        refresh_token: str,
        expires_in: int,
        next_name: str,
        next_session: str,
    ) -> None:
        """**Validates: Requirements 3.2, 3.3**"""
        controller, service = _make_controller()

        if authenticated:
            token_pair = TokenPair(access_token, id_token, refresh_token, expires_in)
            result = ChallengeResult.authenticated(token_pair)
        else:
            result = ChallengeResult.next_challenge(next_name, next_session)

        service.respond_to_challenge = AsyncMock(return_value=result)

        resp = _run(
            controller.handle_respond_to_challenge(
                _event(
                    {
                        "challenge_name": "SMS_MFA",
                        "session": "abc",
                        "challenge_responses": {"k": "v"},
                    }
                )
            )
        )

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])

        has_tokens = all(k in body for k in ("access_token", "id_token", "refresh_token", "expires_in"))
        has_next = all(k in body for k in NEXT_CHALLENGE_KEYS)

        # Exactly one field-set present (XOR).
        assert has_tokens != has_next

        if authenticated:
            assert has_tokens
            assert "challenge_name" not in body
            assert body["access_token"] == access_token
        else:
            assert has_next
            assert not any(k in body for k in TOKEN_KEYS)
            assert body["challenge_name"] == next_name


# ─── Property 4: Error shape and no sensitive-material leak ─────────────────────


# Feature: password-recovery-challenge, Property 4: Error shape and no sensitive-material leak
class TestProperty4ErrorShapeNoLeak:
    """Property 4 — Error shape and no sensitive-material leak.

    For any request to any of the three endpoints that yields status >= 400, the
    body is exactly {"error": s} with 1 <= len(s) <= 500 and s does NOT contain
    any injected secret substring (password, confirmation_code, session, tokens).

    **Validates: Requirements 4.1, 4.6**
    """

    @staticmethod
    def _assert_error_shape_no_leak(resp: dict[str, Any], secrets: list[str]) -> None:
        assert resp["statusCode"] >= 400
        body = json.loads(resp["body"])
        assert set(body.keys()) == {"error"}
        msg = body["error"]
        assert isinstance(msg, str)
        assert 1 <= len(msg) <= 500
        for secret in secrets:
            if secret and len(secret) >= 4:  # only meaningful substrings
                assert secret not in msg

    @given(
        secret_pw=st.text(min_size=8, max_size=40),
        secret_code=st.text(min_size=8, max_size=40),
        error=st.sampled_from(
            [
                ValidationError("policy violated"),
                RateLimitError(),
                RuntimeError("boom"),
            ]
        ),
    )
    @settings(max_examples=200)
    def test_confirm_error_shape_no_leak(
        self, secret_pw: str, secret_code: str, error: Exception
    ) -> None:
        """**Validates: Requirements 4.1, 4.6**"""
        controller, service = _make_controller()
        service.confirm_forgot_password = AsyncMock(side_effect=error)
        resp = _run(
            controller.handle_confirm_forgot_password(
                _event(
                    {
                        "email": "user@example.com",
                        "confirmation_code": secret_code,
                        "new_password": secret_pw,
                    }
                )
            )
        )
        self._assert_error_shape_no_leak(resp, [secret_pw, secret_code])

    @given(
        secret_session=st.text(min_size=8, max_size=60),
        error=st.sampled_from(
            [
                InvalidCredentialsError(),
                ValidationError("bad password policy"),
                RuntimeError("unexpected"),
            ]
        ),
    )
    @settings(max_examples=200)
    def test_respond_error_shape_no_leak(
        self, secret_session: str, error: Exception
    ) -> None:
        """**Validates: Requirements 4.1, 4.6**"""
        controller, service = _make_controller()
        service.respond_to_challenge = AsyncMock(side_effect=error)
        resp = _run(
            controller.handle_respond_to_challenge(
                _event(
                    {
                        "challenge_name": "NEW_PASSWORD_REQUIRED",
                        "session": secret_session,
                        "challenge_responses": {"NEW_PASSWORD": "s3cr3t-pass"},
                    }
                )
            )
        )
        self._assert_error_shape_no_leak(resp, [secret_session, "s3cr3t-pass"])

    @given(
        error=st.sampled_from([RateLimitError(), RuntimeError("kaboom")]),
    )
    @settings(max_examples=200)
    def test_forgot_error_shape_no_leak(self, error: Exception) -> None:
        """**Validates: Requirements 4.1, 4.6**"""
        controller, service = _make_controller()
        service.forgot_password = AsyncMock(side_effect=error)
        resp = _run(
            controller.handle_forgot_password(_event({"email": "user@example.com"}))
        )
        self._assert_error_shape_no_leak(resp, [])


# ─── Property 5: confirm-forgot-password success has no tokens ──────────────────


# Feature: password-recovery-challenge, Property 5: confirm-forgot-password success has no tokens
class TestProperty5ConfirmNoTokens:
    """Property 5 — confirm-forgot-password success has no tokens.

    For any valid (email, confirmation_code, new_password) with a successful
    service call, the 200 response body has none of access_token / id_token /
    refresh_token.

    **Validates: Requirements 2.2, 2.3**
    """

    @given(
        email=valid_emails(),
        code=valid_codes,
        password=valid_passwords,
    )
    @settings(max_examples=200)
    def test_confirm_success_has_no_tokens(
        self, email: str, code: str, password: str
    ) -> None:
        """**Validates: Requirements 2.2, 2.3**"""
        controller, service = _make_controller()
        service.confirm_forgot_password = AsyncMock(return_value=None)
        resp = _run(
            controller.handle_confirm_forgot_password(
                _event(
                    {
                        "email": email,
                        "confirmation_code": code,
                        "new_password": password,
                    }
                )
            )
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert not any(k in body for k in TOKEN_KEYS)


# ─── Property 6: DomainError -> HTTP status mapping ─────────────────────────────


# Feature: password-recovery-challenge, Property 6: DomainError to HTTP status mapping
class TestProperty6DomainErrorMapping:
    """Property 6 — DomainError -> HTTP status mapping.

    For any DomainError subtype raised by the service, the controller maps
    ValidationError -> 400, InvalidCredentialsError -> 401, RateLimitError -> 429,
    and any non-domain Exception -> 500, per the per-endpoint error tables.

    **Validates: Requirements 1.6, 1.7, 2.7, 2.8, 2.9, 2.10, 2.11, 3.7, 3.8, 3.9, 4.4**
    """

    @given(
        case=st.sampled_from(
            [
                (RateLimitError(), 429),  # Req 1.6
                (RuntimeError("x"), 500),  # Req 1.7
            ]
        ),
    )
    @settings(max_examples=200)
    def test_forgot_error_mapping(self, case: tuple[Exception, int]) -> None:
        """**Validates: Requirements 1.6, 1.7**"""
        error, expected = case
        controller, service = _make_controller()
        service.forgot_password = AsyncMock(side_effect=error)
        resp = _run(
            controller.handle_forgot_password(_event({"email": "user@example.com"}))
        )
        assert resp["statusCode"] == expected

    @given(
        case=st.sampled_from(
            [
                (ValidationError("policy"), 400),  # Req 2.7/2.8/2.9
                (RateLimitError(), 429),  # Req 2.10
                (RuntimeError("x"), 500),  # Req 2.11
            ]
        ),
    )
    @settings(max_examples=200)
    def test_confirm_error_mapping(self, case: tuple[Exception, int]) -> None:
        """**Validates: Requirements 2.7, 2.8, 2.9, 2.10, 2.11, 4.4**"""
        error, expected = case
        controller, service = _make_controller()
        service.confirm_forgot_password = AsyncMock(side_effect=error)
        resp = _run(
            controller.handle_confirm_forgot_password(
                _event(
                    {
                        "email": "user@example.com",
                        "confirmation_code": "code123",
                        "new_password": "NewPass123!",
                    }
                )
            )
        )
        assert resp["statusCode"] == expected

    @given(
        case=st.sampled_from(
            [
                (InvalidCredentialsError(), 401),  # Req 3.7
                (ValidationError("password policy"), 400),  # Req 3.8
                (RuntimeError("x"), 500),  # Req 3.9
            ]
        ),
    )
    @settings(max_examples=200)
    def test_respond_error_mapping(self, case: tuple[Exception, int]) -> None:
        """**Validates: Requirements 3.7, 3.8, 3.9, 4.4**"""
        error, expected = case
        controller, service = _make_controller()
        service.respond_to_challenge = AsyncMock(side_effect=error)
        resp = _run(
            controller.handle_respond_to_challenge(
                _event(
                    {
                        "challenge_name": "NEW_PASSWORD_REQUIRED",
                        "session": "sess-xyz",
                        "challenge_responses": {"NEW_PASSWORD": "p"},
                    }
                )
            )
        )
        assert resp["statusCode"] == expected

    @given(
        base_domain_error=st.builds(lambda m: DomainError(m), st.just("generic domain error")),
    )
    @settings(max_examples=200)
    def test_generic_domain_error_maps_to_500_on_confirm(
        self, base_domain_error: DomainError
    ) -> None:
        """A non-Validation/InvalidCredentials/RateLimit DomainError maps to 500.

        **Validates: Requirements 4.4**
        """
        controller, service = _make_controller()
        service.confirm_forgot_password = AsyncMock(side_effect=base_domain_error)
        resp = _run(
            controller.handle_confirm_forgot_password(
                _event(
                    {
                        "email": "user@example.com",
                        "confirmation_code": "code123",
                        "new_password": "NewPass123!",
                    }
                )
            )
        )
        assert resp["statusCode"] == 500
