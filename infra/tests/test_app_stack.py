"""CDK unit tests for the Account Management stack.

These tests synthesize the stack in-memory and assert on the produced
CloudFormation template using `aws_cdk.assertions`. Lambda code bundling is
mocked (replaced with an inline stub) so the tests run fast and offline —
we are asserting on infrastructure wiring, not on the bundled application code.
"""

from __future__ import annotations

from unittest.mock import patch

import aws_cdk as cdk
import pytest
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template

from config import get_env_config

# Social login is gated behind a config flag (default off until the social/*
# secrets exist). The social-only snapshot tests below are skipped while the
# flag is off, since a social-disabled synth intentionally omits that infra.
_SOCIAL_ENABLED = get_env_config("dev").social_login_enabled


def _synth_template(env_name: str) -> Template:
    """Synthesize the stack for an environment and return its Template.

    The backend code asset is stubbed with an inline Code so no bundling
    (pip/Docker) runs during tests.
    """
    # Import here so the patch target is the symbol used inside app_stack.
    with patch(
        "stacks.app_stack.build_backend_code",
        return_value=lambda_.Code.from_inline("def handler(e, c):\n    return e"),
    ):
        from stacks.app_stack import AccountManagementStack

        app = cdk.App()
        cfg = get_env_config(env_name)
        stack = AccountManagementStack(
            app,
            f"AccountManagement-{cfg.name}",
            config=cfg,
            env=cdk.Environment(account="111111111111", region=cfg.region),
        )
        return Template.from_stack(stack)


@pytest.fixture(scope="module")
def dev_template() -> Template:
    return _synth_template("dev")


@pytest.fixture(scope="module")
def prod_template() -> Template:
    return _synth_template("prod")


# ── DynamoDB ──────────────────────────────────────────────────────────────

def test_single_table_with_two_gsis(dev_template: Template) -> None:
    dev_template.resource_count_is("AWS::DynamoDB::Table", 1)
    dev_template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "GlobalSecondaryIndexes": Match.array_with(
                [
                    Match.object_like({"IndexName": "GSI1"}),
                    Match.object_like({"IndexName": "GSI2"}),
                ]
            ),
        },
    )


def test_prod_table_has_pitr_and_retain(prod_template: Template) -> None:
    prod_template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}},
    )
    prod_template.has_resource(
        "AWS::DynamoDB::Table", {"DeletionPolicy": "Retain"}
    )


def test_dev_table_is_destroyable(dev_template: Template) -> None:
    dev_template.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Delete"})


# ── Lambda ──────────────────────────────────────────────────────────────

def test_five_python_lambdas(dev_template: Template) -> None:
    # 4 API handlers + 1 post-confirmation trigger = 5 app functions.
    # (A log-retention helper Lambda may also exist depending on CDK internals,
    # so assert on the app functions via their handlers instead of a exact count.)
    for handler in (
        "api.auth.authHandler.handler",
        "api.registration.registrationHandler.handler",
        "api.accountType.accountTypeHandler.handler",
        "api.member.memberHandler.handler",
        "api.registration.postConfirmationHandler.handler",
    ):
        dev_template.has_resource_properties(
            "AWS::Lambda::Function",
            {"Handler": handler, "Runtime": "python3.12"},
        )


def test_lambdas_have_token_allowlist_env(dev_template: Template) -> None:
    dev_template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "api.auth.authHandler.handler",
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "REGION": "sa-east-1",
                        "COGNITO_ISSUERS": Match.any_value(),
                        "COGNITO_CLIENT_IDS": Match.any_value(),
                    }
                )
            },
        },
    )


def test_no_jwt_secret_env(dev_template: Template) -> None:
    # The RS256/JWKS design forbids a symmetric secret — ensure none leaks in.
    template_json = dev_template.to_json()
    assert "JWT_SECRET" not in str(template_json)


# ── Cognito ──────────────────────────────────────────────────────────────

def test_user_pool_and_client(dev_template: Template) -> None:
    dev_template.resource_count_is("AWS::Cognito::UserPool", 1)
    dev_template.resource_count_is("AWS::Cognito::UserPoolClient", 1)


def test_post_confirmation_trigger_wired(dev_template: Template) -> None:
    dev_template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {"LambdaConfig": Match.object_like({"PostConfirmation": Match.any_value()})},
    )


# ── API Gateway ──────────────────────────────────────────────────────────

def test_rest_api_exists(dev_template: Template) -> None:
    dev_template.resource_count_is("AWS::ApiGateway::RestApi", 1)


def test_api_has_expected_routes(dev_template: Template) -> None:
    # Resource paths (path parts) that must exist in the API.
    for path_part in (
        "auth",
        "login",
        "refresh",
        "logout",
        "register",
        "forgot-password",
        "confirm-forgot-password",
        "respond-to-challenge",
        "account-types",
        "members",
        "health",
        "{id}",
        "{member_id}",
    ):
        dev_template.has_resource_properties(
            "AWS::ApiGateway::Resource", {"PathPart": path_part}
        )


def test_password_recovery_routes_present(dev_template: Template) -> None:
    # The three password-recovery / challenge POST routes live under /auth,
    # served by the same AuthFn LambdaIntegration (public, no authorizer).
    for path_part in (
        "forgot-password",
        "confirm-forgot-password",
        "respond-to-challenge",
    ):
        dev_template.has_resource_properties(
            "AWS::ApiGateway::Resource", {"PathPart": path_part}
        )


def test_authfn_has_password_recovery_cognito_actions(dev_template: Template) -> None:
    # AuthFn's IAM policy must grant the client-based Cognito operations the
    # password-recovery / challenge endpoints call. Asserting the exact policy
    # statement is brittle (the actions live inside an Action array alongside
    # the admin ops), so verify each action string appears in the template.
    template_json = str(dev_template.to_json())
    for action in (
        "cognito-idp:ForgotPassword",
        "cognito-idp:ConfirmForgotPassword",
        "cognito-idp:RespondToAuthChallenge",
    ):
        assert action in template_json


# ── WAF ──────────────────────────────────────────────────────────────────

def test_regional_web_acl_with_rules(dev_template: Template) -> None:
    dev_template.has_resource_properties(
        "AWS::WAFv2::WebACL",
        {
            "Scope": "REGIONAL",
            "Rules": Match.array_with(
                [
                    Match.object_like({"Name": "AWSManagedCommon"}),
                    Match.object_like({"Name": "AWSManagedKnownBadInputs"}),
                    Match.object_like({"Name": "RateLimitPerIp"}),
                ]
            ),
        },
    )


def test_web_acl_association(dev_template: Template) -> None:
    dev_template.resource_count_is("AWS::WAFv2::WebACLAssociation", 1)


def test_dev_prod_rate_limits_differ() -> None:
    assert get_env_config("dev").waf_rate_limit_per_5min == 2000
    assert get_env_config("prod").waf_rate_limit_per_5min == 10000


# ── Observability ──────────────────────────────────────────────────────────

def test_sns_alarm_topic(dev_template: Template) -> None:
    dev_template.resource_count_is("AWS::SNS::Topic", 1)


def test_alarms_exist_and_notify_topic(dev_template: Template) -> None:
    # lambdas x 2 (errors+throttles) + api 5xx + api latency + ddb user + ddb system.
    # With social ENABLED there are 6 lambdas (4 API handlers + post-confirmation
    # trigger + OAuth handler): 6x2 + 4 = 16. With social DISABLED there are 5
    # lambdas (no OAuth handler): 5x2 + 4 = 14.
    expected = 16 if _SOCIAL_ENABLED else 14
    dev_template.resource_count_is("AWS::CloudWatch::Alarm", expected)


# ── Social login (CDK snapshot tests) ──────────────────────────────────────
#
# These snapshot tests assert the synthesized template wires the social-login
# infrastructure (tasks 17.1–17.4): the Google/Facebook Cognito Identity
# Providers, the OAuthHandlerFn Lambda, the /auth/social/* API routes, and the
# WAF protection covering them. They also enforce Requirement 8.7 — no secret
# material may appear in the template; social credentials must be rendered
# exclusively as Secrets Manager dynamic references.


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_social_identity_provider_google(dev_template: Template) -> None:
    # Google IDP synthesizes to AWS::Cognito::UserPoolIdentityProvider with
    # ProviderType="Google" (Requirement 1.1).
    dev_template.has_resource_properties(
        "AWS::Cognito::UserPoolIdentityProvider",
        {"ProviderType": "Google"},
    )


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_social_identity_provider_facebook(dev_template: Template) -> None:
    # Facebook IDP synthesizes to AWS::Cognito::UserPoolIdentityProvider with
    # ProviderType="Facebook" (Requirement 1.2).
    dev_template.has_resource_properties(
        "AWS::Cognito::UserPoolIdentityProvider",
        {"ProviderType": "Facebook"},
    )


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_exactly_two_identity_providers(dev_template: Template) -> None:
    # Precisely one Google + one Facebook provider — no more, no fewer.
    dev_template.resource_count_is("AWS::Cognito::UserPoolIdentityProvider", 2)


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_oauth_handler_lambda_present(dev_template: Template) -> None:
    # OAuthHandlerFn serves the /auth/social/* routes (task 17.3).
    dev_template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "api.socialLogin.oauthHandler.handler",
            "Runtime": "python3.12",
        },
    )


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_oauth_handler_has_social_env(dev_template: Template) -> None:
    # The OAuth Lambda carries the social-specific environment surface: the
    # Hosted UI domain, the OAuth callback URL, and the HMAC state secret.
    dev_template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "api.socialLogin.oauthHandler.handler",
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "COGNITO_HOSTED_UI_DOMAIN": Match.any_value(),
                        "COGNITO_CALLBACK_URL": Match.any_value(),
                        "SOCIAL_STATE_SECRET": Match.any_value(),
                    }
                )
            },
        },
    )


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_social_api_routes_present(dev_template: Template) -> None:
    # The /auth/social/{proxy+} routes are registered on the API. The greedy
    # proxy resource lets the single OAuth Lambda route every social sub-path
    # (authorize, callback, select-tenant) internally.
    for path_part in ("social", "{proxy+}"):
        dev_template.has_resource_properties(
            "AWS::ApiGateway::Resource", {"PathPart": path_part}
        )


def test_waf_association_covers_social_routes(dev_template: Template) -> None:
    # WAF is associated at the API *stage* level (a single WebACLAssociation),
    # so the /auth/social/* routes are protected by the same WAF as every other
    # endpoint via this one association (Requirement 8.3). The single-association
    # assertion holds regardless of the social flag; the social path-part
    # assertions only apply when social login is enabled.
    dev_template.resource_count_is("AWS::WAFv2::WebACLAssociation", 1)
    if _SOCIAL_ENABLED:
        dev_template.has_resource_properties(
            "AWS::ApiGateway::Resource", {"PathPart": "social"}
        )
        dev_template.has_resource_properties(
            "AWS::ApiGateway::Resource", {"PathPart": "{proxy+}"}
        )


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_no_plaintext_social_credentials_in_template(dev_template: Template) -> None:
    # Requirement 8.7: no secret material may appear in the synthesized
    # template. The Google/Facebook client_secret and the SOCIAL_STATE_SECRET
    # must be rendered ONLY as Secrets Manager dynamic references
    # ("{{resolve:secretsmanager:...}}"), resolved by AWS at deploy time.
    template_json = str(dev_template.to_json())

    # The dynamic-reference marker must be present for the social secrets.
    assert "{{resolve:secretsmanager:" in template_json
    # Each social secret is referenced by its logical name + JSON key, never by
    # a plaintext value. (Names only — no secret material is hardcoded here.)
    assert "social/state:SecretString:state_secret" in template_json
    assert "social/google:SecretString:client_secret" in template_json
    assert "social/facebook:SecretString:client_secret" in template_json


@pytest.mark.skipif(not _SOCIAL_ENABLED, reason="social login disabled")
def test_oauth_state_secret_is_dynamic_reference(dev_template: Template) -> None:
    # The OAuthHandlerFn SOCIAL_STATE_SECRET env value must resolve from Secrets
    # Manager at runtime, not be a plaintext literal in the template. The value
    # is rendered as an Fn::Join around a {{resolve:secretsmanager:...}} token,
    # so we locate the OAuth function and assert its env value carries the
    # dynamic-reference marker rather than any inline secret string.
    functions = dev_template.find_resources("AWS::Lambda::Function")
    oauth_env_values = [
        props["Properties"]["Environment"]["Variables"]["SOCIAL_STATE_SECRET"]
        for props in functions.values()
        if props["Properties"].get("Handler")
        == "api.socialLogin.oauthHandler.handler"
    ]
    assert len(oauth_env_values) == 1
    assert "resolve:secretsmanager" in str(oauth_env_values[0])
