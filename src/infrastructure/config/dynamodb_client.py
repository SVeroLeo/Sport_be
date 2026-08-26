"""DynamoDB client configuration — singleton client setup using boto3."""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3

from infrastructure.config.environment import get_environment_config

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table


# Module-level singletons — created once on Lambda cold start, reused on warm invocations.
_dynamodb_resource: "DynamoDBServiceResource | None" = None
_table: "Table | None" = None


def get_dynamodb_resource() -> "DynamoDBServiceResource":
    """Get the singleton DynamoDB resource.

    Creates the boto3 DynamoDB resource on the first call (cold start)
    and reuses it on subsequent calls (warm invocations).

    Returns:
        The boto3 DynamoDB service resource.
    """
    global _dynamodb_resource  # noqa: PLW0603
    if _dynamodb_resource is None:
        config = get_environment_config()
        _dynamodb_resource = boto3.resource("dynamodb", region_name=config.region)
    return _dynamodb_resource


def get_dynamodb_table() -> "Table":
    """Get the singleton DynamoDB Table resource for the application table.

    Creates the Table reference on the first call (cold start)
    and reuses it on subsequent calls (warm invocations).

    Returns:
        The boto3 DynamoDB Table resource for TABLE_NAME.
    """
    global _table  # noqa: PLW0603
    if _table is None:
        config = get_environment_config()
        resource = get_dynamodb_resource()
        _table = resource.Table(config.table_name)
    return _table
