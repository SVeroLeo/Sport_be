"""Infrastructure configuration — environment and DynamoDB client setup."""

from infrastructure.config.dynamodb_client import get_dynamodb_resource, get_dynamodb_table
from infrastructure.config.environment import EnvironmentConfig, get_environment_config

__all__ = [
    "EnvironmentConfig",
    "get_dynamodb_resource",
    "get_dynamodb_table",
    "get_environment_config",
]
