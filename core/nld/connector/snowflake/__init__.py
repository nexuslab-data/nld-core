from nld.connector.base import ConnectorPlugin

from .query_wrapper import SnowflakeQueryWrapper
from .snowflake_connection import (
    SnowflakeConnectionWrapper,
)
from .snowflake_connector import (
    SnowflakeConnector,
)
from .snowflake_credential import (
    SnowflakeAuthenticator,
    SnowflakeCredential,
)
from .snowflake_utils import SnowflakeUtil

Plugin = ConnectorPlugin(
    connector_class=SnowflakeConnector,
    connection_wrapper_class=SnowflakeConnectionWrapper,
    credentials_class=SnowflakeCredential,
)

__all__ = [
    "SnowflakeAuthenticator",
    "SnowflakeConnectionWrapper",
    "SnowflakeConnector",
    "SnowflakeCredential",
    "SnowflakeQueryWrapper",
    "SnowflakeUtil",
]
