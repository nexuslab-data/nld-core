from nld.connector.base import ConnectorPlugin

from .connector_definition import (
    POSTGRESQL_CONNECTOR_DEFINITION,
    PostgreSQLConnectorDefinition,
    PostgreSQLDataTypes,
)
from .engine.psycopg2.connection import (
    Psycopg2SQLConnectionWrapper,
)
from .engine.psycopg2.connector import (
    Psycopg2SQLConnector,
)
from .engine.psycopg2.query_wrapper import (
    Psycopg2QueryWrapper,
)
from .postgresql_credential import (
    PostgreSQLCredential,
)
from .postgresql_structure import (
    PostgreSQLStructure,
)
from .service import (
    POSTGRESQL_DEPLOY_CAPABILITIES,
    PostgreSQLStructureDiffDDLStatementBuilder,
    PostgreSQLStructureReader,
)

Plugin = ConnectorPlugin(
    connector_class=Psycopg2SQLConnector,
    connection_wrapper_class=Psycopg2SQLConnectionWrapper,
    credentials_class=PostgreSQLCredential,
    structure_class_path="nld.connector.postgresql.postgresql_structure.PostgreSQLStructure",
)

__all__ = [
    "POSTGRESQL_CONNECTOR_DEFINITION",
    "POSTGRESQL_DEPLOY_CAPABILITIES",
    "PostgreSQLConnectorDefinition",
    "PostgreSQLCredential",
    "PostgreSQLDataTypes",
    "PostgreSQLStructure",
    "PostgreSQLStructureDiffDDLStatementBuilder",
    "PostgreSQLStructureReader",
    "Psycopg2QueryWrapper",
    "Psycopg2SQLConnectionWrapper",
    "Psycopg2SQLConnector",
]
