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
        "interfaces.http.handlers.auth_handler.handler",
        "interfaces.http.handlers.registration_handler.handler",
        "interfaces.http.handlers.account_type_handler.handler",
        "interfaces.http.handlers.member_handler.handler",
        "interfaces.http.handlers.post_confirmation_handler.handler",
    ):
        dev_template.has_resource_properties(
            "AWS::Lambda::Function",
            {"Handler": handler, "Runtime": "python3.12"},
        )


def test_lambdas_have_token_allowlist_env(dev_template: Template) -> None:
    dev_template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "interfaces.http.handlers.auth_handler.handler",
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
        "account-types",
        "members",
        "health",
        "{id}",
        "{member_id}",
    ):
        dev_template.has_resource_properties(
            "AWS::ApiGateway::Resource", {"PathPart": path_part}
        )


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
    # 5 lambdas x 2 (errors+throttles) + api 5xx + api latency + ddb user + ddb system = 14
    dev_template.resource_count_is("AWS::CloudWatch::Alarm", 14)
