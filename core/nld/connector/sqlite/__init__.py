from nld.connector.base import ConnectorPlugin

from .connector_definition import (
    SQLITE_CONNECTOR_DEFINITION,
    SQLiteConnectorDefinition,
    SQLiteDataTypes,
    SQLiteStorageAffinities,
    resolve_storage_affinity,
)
from .constants import SQLITE_DIALECT, SQLITE_SCHEMA
from .engine.sqlite_native.connection import (
    SQLiteConnectionWrapper,
)
from .engine.sqlite_native.connector import (
    SQLiteSQLConnector,
)
from .engine.sqlite_native.query_wrapper import (
    SQLiteQueryWrapper,
)
from .service import (
    SQLITE_DEPLOY_CAPABILITIES,
    SQLiteStructureDiffDDLStatementBuilder,
    SQLiteStructureReader,
)
from .sqlite_credential import (
    SQLiteCredential,
)
from .sqlite_structure import (
    SQLiteStructure,
)

Plugin = ConnectorPlugin(
    connector_class=SQLiteSQLConnector,
    connection_wrapper_class=SQLiteConnectionWrapper,
    credentials_class=SQLiteCredential,
    structure_class_path="nld.connector.sqlite.sqlite_structure.SQLiteStructure",
)

__all__ = [
    "SQLITE_CONNECTOR_DEFINITION",
    "SQLITE_DEPLOY_CAPABILITIES",
    "SQLITE_DIALECT",
    "SQLITE_SCHEMA",
    "SQLiteConnectionWrapper",
    "SQLiteConnectorDefinition",
    "SQLiteCredential",
    "SQLiteDataTypes",
    "SQLiteQueryWrapper",
    "SQLiteSQLConnector",
    "SQLiteStorageAffinities",
    "SQLiteStructure",
    "SQLiteStructureDiffDDLStatementBuilder",
    "SQLiteStructureReader",
    "resolve_storage_affinity",
]
