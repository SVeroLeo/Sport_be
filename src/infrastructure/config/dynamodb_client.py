"""DynamoDB client configuration — singleton client setup using boto3."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table


# Module-level singletons — created once on Lambda cold start, reused on warm invocations.
_dynamodb_resource: "DynamoDBServiceResource | None" = None
_table: "Table | None" = None


def get_dynamodb_resource() -> "DynamoDBServiceResource":
    """Get the singleton DynamoDB resource.

    Reads REGION directly from the environment to avoid requiring the full
    EnvironmentConfig (which validates Cognito vars not needed here).

    Returns:
        The boto3 DynamoDB service resource.
    """
    global _dynamodb_resource  # noqa: PLW0603
    if _dynamodb_resource is None:
        region = os.environ.get("REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        _dynamodb_resource = boto3.resource("dynamodb", region_name=region)
    return _dynamodb_resource


def get_dynamodb_table() -> "Table":
    """Get the singleton DynamoDB Table resource for the application table.

    Reads TABLE_NAME and REGION directly from the environment to avoid
    requiring the full EnvironmentConfig (which validates Cognito vars not
    needed here, e.g. in the PostConfirmation Lambda trigger).

    Returns:
        The boto3 DynamoDB Table resource for TABLE_NAME.

    Raises:
        EnvironmentError: If TABLE_NAME is not set.
    """
    global _table  # noqa: PLW0603
    if _table is None:
        table_name = os.environ.get("TABLE_NAME", "")
        if not table_name:
            raise EnvironmentError("TABLE_NAME environment variable is required")
        resource = get_dynamodb_resource()
        _table = resource.Table(table_name)
    return _table
