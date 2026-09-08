"""SocialCallbackUseCase — orchestrates the OAuth callback for social login.

This use case backs the ``GET /auth/social/callback`` endpoint. It is the
central orchestration point of the federated login flow: it validates the CSRF
``state`` token, exchanges the authorization ``code`` for a Cognito token set,
decodes the ``id_token`` to identify the federated user, and then routes to one
of three outcomes:

* **existing_user** — a returning social user (matched by ``cognito_sub``) is
  fast-pathed straight to their tokens.
* **linked_user** — an existing native (email/password) user with the same
  email has the social provider linked to their account (see ``_link_provider``,
  task 9.3).
* **new_user** — a brand-new social user is provisioned in DynamoDB (see
  ``_provision_new_user``, task 9.2).

The internal ``_provision_new_user`` and ``_link_provider`` methods are
implemented by tasks 9.2 and 9.3 respectively; this task provides their
signatures, docstrings, and the routing that calls them.

Requirements satisfied (orchestration/skeleton): 3.1-3.9, 6, 7.1, 7.3, 7.4,
8.4, 8.5, 9.3-9.6, 10.1, 10.2, 10.3
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from application.dtos.social_login_dtos import SocialLoginOutputDTO
from application.services import state_token
from domain.entities.user import User
from domain.errors.domain_error import DomainError
from domain.errors.validation_error import ValidationError
from domain.value_objects.email import Email

if TYPE_CHECKING:
    from application.ports.i_cognito_service import ICognitoService
    from application.ports.i_tenant_repository import ITenantRepository
    from application.ports.i_user_repository import IUserRepository
    from domain.entities.token_pair import TokenPair

logger = logging.getLogger(__name__)

# Error codes surfaced to the HTTP layer (see design "Error Handling" table).
_INVALID_STATE = "invalid_state"
_INVALID_PROVIDER_EMAIL = "invalid_provider_email"
_PROVISIONING_FAILED = "provisioning_failed"

# CloudWatch metric + namespace for the SocialLoginAttempt metric (Req 10.3).
_METRICS_NAMESPACE = "SportBe/SocialLogin"
_ATTEMPT_METRIC = "SocialLoginAttempt"

# Provisioning metrics (Req 9.5, 9.6).
_PROVISIONING_SUCCESS_METRIC = "SocialLoginProvisioningSuccess"
_PROVISIONING_FAILURE_METRIC = "SocialLoginProvisioningFailure"

# Maps the lowercase provider value carried through the callback flow
# ("google"/"facebook") to the Cognito identity-provider name expected by
# AdminLinkProviderForUser ("Google"/"Facebook") — see design "New Application
# Port Methods" and Req 6.1.
_PROVIDER_IDP_NAMES = {"google": "Google", "facebook": "Facebook"}

# Status assigned to a social user whose tenant cannot be resolved during
# provisioning (Req 4.5). The membership/member/role records stay pending until
# the user selects a tenant (Requirement 5).
_STATUS_PENDING_TENANT = "pending_tenant"

# Callback outcomes (Req 10.2, 10.3).
_OUTCOME_EXISTING_USER = "existing_user"
_OUTCOME_LINKED_USER = "linked_user"
_OUTCOME_NEW_USER = "new_user"

# Number of leading characters of the cognito_sub kept in structured logs so the
# identifier is traceable without exposing the full value (Req 10.1).
_MASK_PREFIX_LEN = 8


class SocialCallbackUseCase:
    """Application use case for handling the OAuth callback.

    Orchestrates the full social-login callback:

    1. Validate the ``state`` token (HMAC + 10-minute TTL). Raise
       ``ValidationError("invalid_state")`` on failure (Req 3.2, 3.3, 8.1, 8.2).
    2. Exchange the authorization ``code`` for a Cognito token set (Req 3.4).
    3. Decode the ``id_token`` JWT payload (no signature verification — Cognito
       already validated it) to extract ``sub``, ``email``, ``name`` and
       ``custom:provider`` (Req 3.6).
    4. Sanitize/validate the email with the ``Email`` value object; raise
       ``ValidationError("invalid_provider_email")`` when it is absent or
       invalid (Req 8.4, 8.5).
    5. Look up the ``User`` by ``cognito_sub``; if found, fast-path return the
       tokens as an existing social user (Req 3.7).
    6. Otherwise look up the ``User`` by ``email`` and route to
       ``_link_provider`` (existing native user, Req 3.8, 6) or
       ``_provision_new_user`` (new social user, Req 3.7, 4).
    7. Build and return a ``SocialLoginOutputDTO`` including
       ``requires_tenant_selection`` when the user is ``pending_tenant``
       (Req 7.1, 7.3, 7.4).

    Structured JSON log events are emitted at the start and end of each callback
    (Req 10.1, 10.2) and a ``SocialLoginAttempt`` CloudWatch metric is emitted
    with ``Provider`` and ``Outcome`` dimensions (Req 10.3).

    The Cognito configuration needed for token exchange (``redirect_uri``,
    ``hosted_ui_domain``) and the HMAC signing secret are injected via the
    constructor so the use case stays free of environment/config coupling,
    consistent with ``SocialAuthorizeUseCase``.
    """

    def __init__(
        self,
        user_repository: IUserRepository,
        cognito_service: ICognitoService,
        tenant_repository: ITenantRepository,
        redirect_uri: str,
        hosted_ui_domain: str,
        state_secret: str,
    ) -> None:
        self._user_repository = user_repository
        self._cognito_service = cognito_service
        self._tenant_repository = tenant_repository
        self._redirect_uri = redirect_uri
        self._hosted_ui_domain = hosted_ui_domain
        self._state_secret = state_secret

    async def execute(self, code: str, state: str) -> SocialLoginOutputDTO:
        """Handle an OAuth callback and return the user's token set.

        Args:
            code: The authorization code returned by the Cognito Hosted UI.
            state: The signed CSRF state token echoed back by the Hosted UI.

        Returns:
            A :class:`SocialLoginOutputDTO` wrapping the Cognito token set and a
            ``requires_tenant_selection`` flag.

        Raises:
            ValidationError: With code ``"invalid_state"`` when the state token
                is tampered or expired, or ``"invalid_provider_email"`` when the
                provider did not supply a valid email.
        """
        start = time.monotonic()

        # 1. Validate the state token (HMAC + TTL) before doing anything else
        #    (Req 3.2, 3.3, 8.1, 8.2). Any failure raises ValidationError("invalid_state").
        state_token.validate_state(state, self._state_secret)

        # 2. Exchange the authorization code for a Cognito token set (Req 3.4, 3.5).
        token_pair = await self._cognito_service.exchange_code_for_tokens(
            code=code,
            redirect_uri=self._redirect_uri,
            hosted_ui_domain=self._hosted_ui_domain,
        )

        # 3. Decode the id_token payload (no signature verification) (Req 3.6).
        claims = self._decode_jwt_payload(token_pair.id_token)
        cognito_sub = str(claims.get("sub", ""))
        raw_email = claims.get("email")
        full_name = str(claims.get("name", "") or "")
        provider = str(claims.get("custom:provider", "") or "")

        # Structured start-of-callback log event (Req 10.1).
        self._log_event(
            event_type="social_callback_received",
            provider=provider,
            cognito_sub=self._mask(cognito_sub),
            timestamp=datetime.now(UTC).isoformat(),
        )

        # 4. Sanitize/validate the provider email via the Email value object
        #    (Req 8.4, 8.5). No DynamoDB records are created when it is invalid.
        email = self._validate_provider_email(raw_email)

        # 5. Fast path: returning social user identified by cognito_sub (Req 3.7).
        existing_by_sub = self._user_repository.find_by_cognito_sub(cognito_sub)
        if existing_by_sub is not None:
            return self._finalize(
                user=existing_by_sub,
                token_pair=token_pair,
                provider=provider,
                outcome=_OUTCOME_EXISTING_USER,
                start=start,
            )

        # 6. Route by email: link an existing native user, or provision a new
        #    social user (Req 3.8, 6 / Req 3.7, 4).
        existing_by_email = self._user_repository.find_by_email(email)
        if existing_by_email is not None:
            user = await self._link_provider(
                user=existing_by_email,
                cognito_sub=cognito_sub,
                provider=provider,
            )
            outcome = _OUTCOME_LINKED_USER
        else:
            user = await self._provision_new_user(
                cognito_sub=cognito_sub,
                email=email,
                full_name=full_name,
                provider=provider,
            )
            outcome = _OUTCOME_NEW_USER

        # 7. Build the response and emit end-of-callback observability.
        return self._finalize(
            user=user,
            token_pair=token_pair,
            provider=provider,
            outcome=outcome,
            start=start,
        )

    # ──── Routing targets (implemented by tasks 9.2 / 9.3) ─────────────────────

    async def _provision_new_user(
        self,
        cognito_sub: str,
        email: Email,
        full_name: str,
        provider: str,
    ) -> User:
        """Provision DynamoDB records for a brand-new social user.

        Implemented by task 9.2. Auto-assigns a tenant from the email domain
        when possible; otherwise creates the ``User`` with
        ``status="pending_tenant"`` and ``default_tenant_id=None`` and leaves the
        membership/member/role records pending. Persists atomically via
        ``user_repository.register_social_user`` (idempotent), sets the
        ``custom:provider`` Cognito attribute, and emits provisioning metrics.

        Args:
            cognito_sub: The Cognito ``sub`` of the federated user.
            email: The validated provider email value object.
            full_name: The user's full name from the provider (may be empty).
            provider: The social provider used (``"google"`` / ``"facebook"``).

        Returns:
            The provisioned (or already-existing) ``User`` entity.

        Raises:
            DomainError: With code ``"provisioning_failed"`` when the atomic
                DynamoDB write fails for a reason other than the idempotency
                condition check (which ``register_social_user`` treats as
                success). The HTTP layer maps this to a 500 response (Req 9.3).
        """
        # Tenant auto-assignment (Req 4.4): the ITenantRepository port currently
        # exposes only find_by_id — there is no email-domain lookup available —
        # so no tenant can be determined automatically here. Per Req 4.5 we
        # create the User in the pending-tenant state and leave the
        # TenantMembership / Member / UserRole records pending until the user
        # completes tenant selection (Requirement 5). Domain-based
        # auto-assignment would require a new repository method and is
        # intentionally not implemented via scanning.
        user = User.create(
            email=email.value,
            cognito_sub=cognito_sub,
            full_name=full_name,
            status=_STATUS_PENDING_TENANT,
            default_tenant_id=None,
            registration_type="social",
        )

        try:
            # Idempotent atomic write (Req 4.6, 4.7, 9.1, 9.2). With no tenant
            # resolved, the membership/member/role records are omitted (Req 4.5).
            self._user_repository.register_social_user(
                user=user,
                membership=None,
                member=None,
                role=None,
            )

            # Record which provider was used on the Cognito user (Req 4, design
            # custom-attribute table). Kept inside the try so a failure here is
            # surfaced as a provisioning failure rather than a silent gap.
            await self._cognito_service.admin_update_user_attributes(
                cognito_sub=cognito_sub,
                attributes={"custom:provider": provider},
            )
        except Exception as exc:
            # Non-conditional failure: log at ERROR with masked cognito_sub and
            # email domain only (Req 9.3), emit the failure metric (Req 9.6),
            # and raise so the HTTP layer returns 500 "provisioning_failed".
            failure_reason = type(exc).__name__
            self._log_event(
                event_type="social_provisioning_failed",
                provider=provider,
                cognito_sub=self._mask(cognito_sub),
                email_domain=self._email_domain(email),
                failure_reason=failure_reason,
                level="ERROR",
            )
            self._emit_provisioning_metric(
                metric=_PROVISIONING_FAILURE_METRIC,
                provider=provider,
                failure_reason=failure_reason,
            )
            raise DomainError(_PROVISIONING_FAILED) from exc

        # Provisioning succeeded (Req 9.5): emit the success metric.
        self._emit_provisioning_metric(
            metric=_PROVISIONING_SUCCESS_METRIC,
            provider=provider,
        )
        return user

    async def _link_provider(
        self,
        user: User,
        cognito_sub: str,
        provider: str,
    ) -> User:
        """Link a social provider to an existing native user.

        Implemented by task 9.3. Calls
        ``cognito_service.admin_link_provider_for_user`` to attach the federated
        identity to the existing native Cognito user, updates the
        ``custom:provider`` attribute, and returns the existing user's data
        without creating duplicate DynamoDB records.

        Args:
            user: The existing native ``User`` matched by email.
            cognito_sub: The Cognito ``sub`` of the federated identity.
            provider: The social provider used (``"google"`` / ``"facebook"``).

        Returns:
            The existing ``User`` entity (unchanged records).

        Raises:
            ConflictError: With code ``"provider_link_failed"`` when the Cognito
                ``AdminLinkProviderForUser`` call fails. Raised by the
                ``CognitoAuthService`` adapter and allowed to propagate so the
                HTTP layer returns 409 (Req 6.5). No DynamoDB records are created
                in this path (Req 6.3).
        """
        # Map the lowercase provider value ("google"/"facebook") to the Cognito
        # IDP name expected by AdminLinkProviderForUser ("Google"/"Facebook").
        # An unrecognized value is passed through capitalized as a best-effort
        # fallback rather than silently dropped.
        provider_name = _PROVIDER_IDP_NAMES.get(provider.lower(), provider.capitalize())

        # Link the federated identity to the existing native Cognito user
        # (Req 6.1). The destination is the EXISTING native user's cognito_sub
        # (user.cognito_sub); the source (provider_user_id) is the federated
        # identity's cognito_sub passed into this method. On failure the adapter
        # raises ConflictError("provider_link_failed") (Req 6.5), which is left
        # to propagate — no register_social_user call, so no duplicate records
        # (Req 6.3).
        await self._cognito_service.admin_link_provider_for_user(
            destination_cognito_sub=user.cognito_sub,
            provider_name=provider_name,
            provider_user_id=cognito_sub,
        )

        # Linking succeeded: record the linked provider on the existing native
        # Cognito user via custom:provider (Req 6.2). Updated on the existing
        # user's cognito_sub, not the federated identity's.
        await self._cognito_service.admin_update_user_attributes(
            cognito_sub=user.cognito_sub,
            attributes={"custom:provider": provider},
        )

        self._log_event(
            event_type="social_provider_linked",
            provider=provider,
            cognito_sub=self._mask(user.cognito_sub),
        )

        # Return the existing user's data unchanged — no new DynamoDB records
        # are created (Req 6.3).
        return user

    # ──── Internal helpers ─────────────────────────────────────────────────────

    def _finalize(
        self,
        user: User,
        token_pair: TokenPair,
        provider: str,
        outcome: str,
        start: float,
    ) -> SocialLoginOutputDTO:
        """Build the output DTO and emit end-of-callback observability.

        Args:
            user: The resolved ``User`` (existing, linked, or newly provisioned).
            token_pair: The Cognito token set returned to the client.
            provider: The social provider used.
            outcome: One of ``"new_user"``, ``"linked_user"``, ``"existing_user"``.
            start: ``time.monotonic()`` value captured at callback start.

        Returns:
            The :class:`SocialLoginOutputDTO` for the HTTP layer.
        """
        duration_ms = int((time.monotonic() - start) * 1000)

        # End-of-callback structured log (Req 10.2).
        self._log_event(
            event_type="social_callback_result",
            outcome=outcome,
            provider=provider,
            duration_ms=duration_ms,
        )

        # SocialLoginAttempt metric with Provider + Outcome dimensions (Req 10.3).
        self._emit_attempt_metric(provider=provider, outcome=outcome)

        # requires_tenant_selection is True only for pending-tenant users (Req 7.4).
        return SocialLoginOutputDTO(
            access_token=token_pair.access_token,
            id_token=token_pair.id_token,
            refresh_token=token_pair.refresh_token,
            expires_in=token_pair.expires_in,
            user_id=user.user_id,
            requires_tenant_selection=user.status == "pending_tenant",
        )

    def _validate_provider_email(self, raw_email: Any) -> Email:
        """Validate/sanitize the email supplied by the social provider (Req 8.4, 8.5).

        Args:
            raw_email: The raw ``email`` claim from the id_token (any type).

        Returns:
            A validated :class:`Email` value object.

        Raises:
            ValidationError: With code ``"invalid_provider_email"`` when the
                email is missing or fails validation.
        """
        if not isinstance(raw_email, str) or not raw_email:
            raise ValidationError(_INVALID_PROVIDER_EMAIL, field="email")
        try:
            return Email.create(raw_email)
        except ValidationError as exc:
            raise ValidationError(_INVALID_PROVIDER_EMAIL, field="email") from exc

    @staticmethod
    def _decode_jwt_payload(id_token: str) -> dict[str, Any]:
        """Decode a JWT payload without verifying the signature (Req 3.6).

        Cognito has already validated the token during the code exchange, so we
        only need to read the claims. Decodes the middle (payload) segment of the
        ``header.payload.signature`` JWT structure as base64url JSON.

        Args:
            id_token: The compact-serialization JWT id_token from Cognito.

        Returns:
            The decoded claims dictionary. Returns an empty dict for a malformed
            token; callers surface the appropriate error via email validation.
        """
        segments = id_token.split(".")
        if len(segments) < 2:
            return {}

        payload_segment = segments[1]
        # Restore base64url padding, which JWTs strip.
        padding = "=" * (-len(payload_segment) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload_segment + padding)
            claims = json.loads(decoded)
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return {}

        return claims if isinstance(claims, dict) else {}

    @staticmethod
    def _mask(cognito_sub: str) -> str:
        """Mask a cognito_sub to its first 8 characters for logging (Req 10.1)."""
        return cognito_sub[:_MASK_PREFIX_LEN]

    @staticmethod
    def _email_domain(email: Email) -> str:
        """Return only the domain part of an email for logging (Req 9.3, 10.1).

        The local part is dropped so provisioning error logs never contain the
        full email address, only the domain (e.g. ``"example.com"``).
        """
        _, _, domain = email.value.partition("@")
        return domain

    @staticmethod
    def _log_event(event_type: str, level: str = "INFO", **fields: Any) -> None:
        """Emit a structured JSON log event (Req 10.1, 10.2, 9.3).

        Args:
            event_type: The structured event name.
            level: Log level — ``"ERROR"`` routes to ``logger.error`` (used for
                provisioning failures, Req 9.3); anything else uses
                ``logger.info``.
            **fields: Additional structured fields to include in the payload.
        """
        payload = json.dumps({"event_type": event_type, "level": level, **fields})
        if level == "ERROR":
            logger.error(payload)
        else:
            logger.info(payload)

    @staticmethod
    def _emit_attempt_metric(provider: str, outcome: str) -> None:
        """Emit the ``SocialLoginAttempt`` CloudWatch metric (Req 10.3).

        Uses the CloudWatch Embedded Metric Format (EMF): a structured JSON log
        line that CloudWatch automatically ingests as a metric with the given
        dimensions. This keeps the use case free of a direct CloudWatch client
        dependency while still emitting a real metric, consistent with the
        codebase's stdlib-logging convention.
        """
        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": _METRICS_NAMESPACE,
                        "Dimensions": [["Provider", "Outcome"]],
                        "Metrics": [{"Name": _ATTEMPT_METRIC, "Unit": "Count"}],
                    }
                ],
            },
            "Provider": provider,
            "Outcome": outcome,
            _ATTEMPT_METRIC: 1,
        }
        logger.info(json.dumps(emf))

    @staticmethod
    def _emit_provisioning_metric(
        metric: str,
        provider: str,
        failure_reason: str | None = None,
    ) -> None:
        """Emit a provisioning CloudWatch metric via EMF (Req 9.5, 9.6).

        Emits ``SocialLoginProvisioningSuccess`` with a ``Provider`` dimension
        on success, or ``SocialLoginProvisioningFailure`` with ``Provider`` and
        ``FailureReason`` dimensions on failure. Reuses the same Embedded Metric
        Format convention as :meth:`_emit_attempt_metric` so no direct
        CloudWatch client dependency is introduced.

        Args:
            metric: The metric name — ``SocialLoginProvisioningSuccess`` or
                ``SocialLoginProvisioningFailure``.
            provider: The social provider used (metric dimension).
            failure_reason: The failure classification; required for the failure
                metric (adds the ``FailureReason`` dimension). Ignored for the
                success metric.
        """
        properties: dict[str, Any] = {"Provider": provider, metric: 1}
        dimensions = ["Provider"]

        if failure_reason is not None:
            properties["FailureReason"] = failure_reason
            dimensions.append("FailureReason")

        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": _METRICS_NAMESPACE,
                        "Dimensions": [dimensions],
                        "Metrics": [{"Name": metric, "Unit": "Count"}],
                    }
                ],
            },
            **properties,
        }
        logger.info(json.dumps(emf))
