"""AWS WAF edge protection for the REST API (regional Web ACL).

Provides a first line of defense at the edge for the API Gateway stage:
- AWS managed rule groups (common rule set + known bad inputs).
- A rate-based rule limiting requests per source IP.

The Web ACL is REGIONAL (required for API Gateway) and is associated with the
deployed stage. This is the single-region subset of the WAF design captured in
the `aws-multiregion-infrastructure` spec; the full multi-region rollout is
tracked there.
"""

from __future__ import annotations

from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct


class ApiWaf(Construct):
    """A regional WAF Web ACL associated with an API Gateway stage."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        api: apigw.RestApi,
        rate_limit_per_5min: int,
    ) -> None:
        """Build the Web ACL and associate it with the API's deployed stage.

        Args:
            scope: Parent construct (the stack).
            construct_id: Unique construct id.
            env_name: Environment name ("dev"/"prod"), used in resource names.
            api: The REST API whose stage will be protected.
            rate_limit_per_5min: Max allowed requests per source IP over a
                5-minute sliding window before the IP is temporarily blocked.
        """
        super().__init__(scope, construct_id)

        rules = [
            # 1. AWS managed common rule set (OWASP-style common protections).
            wafv2.CfnWebACL.RuleProperty(
                name="AWSManagedCommon",
                priority=1,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name="AWSManagedRulesCommonRuleSet",
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=True,
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"{env_name}-common",
                ),
            ),
            # 2. AWS managed known-bad-inputs rule set.
            wafv2.CfnWebACL.RuleProperty(
                name="AWSManagedKnownBadInputs",
                priority=2,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name="AWSManagedRulesKnownBadInputsRuleSet",
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=True,
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"{env_name}-known-bad-inputs",
                ),
            ),
            # 3. Rate-based rule: block a source IP that exceeds the limit.
            wafv2.CfnWebACL.RuleProperty(
                name="RateLimitPerIp",
                priority=3,
                action=wafv2.CfnWebACL.RuleActionProperty(
                    block=wafv2.CfnWebACL.BlockActionProperty()
                ),
                statement=wafv2.CfnWebACL.StatementProperty(
                    rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                        limit=rate_limit_per_5min,
                        aggregate_key_type="IP",
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=True,
                    cloud_watch_metrics_enabled=True,
                    metric_name=f"{env_name}-rate-limit",
                ),
            ),
        ]

        self.web_acl = wafv2.CfnWebACL(
            self,
            "WebAcl",
            name=f"account-management-{env_name}",
            scope="REGIONAL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(
                allow=wafv2.CfnWebACL.AllowActionProperty()
            ),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name=f"account-management-{env_name}-webacl",
            ),
            rules=rules,
        )

        # Associate the Web ACL with the API's deployed stage. The regional
        # API Gateway stage ARN format is:
        #   arn:aws:apigateway:{region}::/restapis/{apiId}/stages/{stage}
        stage_arn = (
            f"arn:aws:apigateway:{api.env.region}::/restapis/"
            f"{api.rest_api_id}/stages/{api.deployment_stage.stage_name}"
        )

        wafv2.CfnWebACLAssociation(
            self,
            "WebAclAssociation",
            resource_arn=stage_arn,
            web_acl_arn=self.web_acl.attr_arn,
        )

