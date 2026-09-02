"""CloudWatch observability construct: alarms + SNS notifications.

Creates a single SNS topic per environment and a set of alarms covering the
Lambda functions, the REST API, and the DynamoDB table. All alarms notify the
topic. This is intentionally infrastructure-only; wiring email/Slack
subscriptions to the topic is left to operators (or a later TODO).
"""

from __future__ import annotations

from aws_cdk import Duration
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from constructs import Construct


class Observability(Construct):
    """Alarms and an SNS alarm topic for the Account Management stack."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        functions: dict[str, lambda_.Function],
        api: apigw.RestApi,
        table: dynamodb.Table,
    ) -> None:
        """Build the observability resources.

        Args:
            scope: Parent construct (the stack).
            construct_id: Unique construct id.
            env_name: Environment name ("dev"/"prod"), used in resource names.
            functions: Mapping of label -> Lambda function to alarm on.
            api: The REST API to alarm on (5XX + latency).
            table: The DynamoDB table to alarm on (throttled/system errors).
        """
        super().__init__(scope, construct_id)

        self.topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"account-management-alarms-{env_name}",
            display_name=f"Account Management alarms ({env_name})",
        )
        action = cw_actions.SnsAction(self.topic)

        # ── Lambda alarms: errors and throttles per function ──────────────
        for label, fn in functions.items():
            errors = fn.metric_errors(period=Duration.minutes(5), statistic="Sum")
            error_alarm = cw.Alarm(
                self,
                f"{label}ErrorsAlarm",
                alarm_name=f"account-management-{env_name}-{label}-errors",
                metric=errors,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description=f"{label} Lambda reported errors ({env_name})",
            )
            error_alarm.add_alarm_action(action)

            throttles = fn.metric_throttles(period=Duration.minutes(5), statistic="Sum")
            throttle_alarm = cw.Alarm(
                self,
                f"{label}ThrottlesAlarm",
                alarm_name=f"account-management-{env_name}-{label}-throttles",
                metric=throttles,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description=f"{label} Lambda is being throttled ({env_name})",
            )
            throttle_alarm.add_alarm_action(action)

        # ── API Gateway alarms: server errors and p99 latency ─────────────
        api_5xx = api.metric_server_error(
            period=Duration.minutes(5), statistic="Sum"
        )
        api_5xx_alarm = cw.Alarm(
            self,
            "Api5xxAlarm",
            alarm_name=f"account-management-{env_name}-api-5xx",
            metric=api_5xx,
            threshold=5,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"API Gateway 5XX errors ({env_name})",
        )
        api_5xx_alarm.add_alarm_action(action)

        api_latency = api.metric_latency(
            period=Duration.minutes(5), statistic="p99"
        )
        api_latency_alarm = cw.Alarm(
            self,
            "ApiLatencyAlarm",
            alarm_name=f"account-management-{env_name}-api-latency-p99",
            metric=api_latency,
            threshold=3000,  # ms
            evaluation_periods=3,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"API Gateway p99 latency high ({env_name})",
        )
        api_latency_alarm.add_alarm_action(action)

        # ── DynamoDB alarms: user + system errors ─────────────────────────
        ddb_user_errors = table.metric_user_errors(
            period=Duration.minutes(5), statistic="Sum"
        )
        ddb_user_alarm = cw.Alarm(
            self,
            "DdbUserErrorsAlarm",
            alarm_name=f"account-management-{env_name}-ddb-user-errors",
            metric=ddb_user_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"DynamoDB user errors ({env_name})",
        )
        ddb_user_alarm.add_alarm_action(action)

        # Scope system-error metrics to the operations the app actually uses.
        # Alarming on a math expression is capped at 10 individual metrics, so
        # we avoid the "all operations" default which exceeds that limit.
        ddb_system_errors = table.metric_system_errors_for_operations(
            operations=[
                dynamodb.Operation.GET_ITEM,
                dynamodb.Operation.BATCH_GET_ITEM,
                dynamodb.Operation.QUERY,
                dynamodb.Operation.PUT_ITEM,
                dynamodb.Operation.UPDATE_ITEM,
                dynamodb.Operation.DELETE_ITEM,
                dynamodb.Operation.TRANSACT_WRITE_ITEMS,
                dynamodb.Operation.TRANSACT_GET_ITEMS,
            ],
            period=Duration.minutes(5),
            statistic="Sum",
        )
        ddb_system_alarm = cw.Alarm(
            self,
            "DdbSystemErrorsAlarm",
            alarm_name=f"account-management-{env_name}-ddb-system-errors",
            metric=ddb_system_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"DynamoDB system errors ({env_name})",
        )
        ddb_system_alarm.add_alarm_action(action)

