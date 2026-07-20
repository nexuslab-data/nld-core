from nld.connector.base import ConnectorPlugin

from .connector_definition import (
    SNOWFLAKE_CONNECTOR_DEFINITION,
    SnowflakeConnectorDefinition,
    SnowflakeDataTypes,
)
from .query_wrapper import SnowflakeQueryWrapper
from .service import SNOWFLAKE_DEPLOY_CAPABILITIES
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
from .snowflake_structure import SnowflakeStructure
from .snowflake_utils import SnowflakeUtil

Plugin = ConnectorPlugin(
    connector_class=SnowflakeConnector,
    connection_wrapper_class=SnowflakeConnectionWrapper,
    credentials_class=SnowflakeCredential,
    structure_class_path="nld.connector.snowflake.snowflake_structure.SnowflakeStructure",
)

__all__ = [
    "SNOWFLAKE_CONNECTOR_DEFINITION",
    "SNOWFLAKE_DEPLOY_CAPABILITIES",
    "SnowflakeAuthenticator",
    "SnowflakeConnectionWrapper",
    "SnowflakeConnector",
    "SnowflakeConnectorDefinition",
    "SnowflakeCredential",
    "SnowflakeDataTypes",
    "SnowflakeQueryWrapper",
    "SnowflakeStructure",
    "SnowflakeUtil",
]
