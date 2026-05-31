from nld.connector.base import ConnectorPlugin

from .constants import DUCKDB_DIALECT
from .duckdb_credential import (
    DuckDBCredential,
)
from .duckdb_data_type import (
    DuckDBDataTypes,
)
from .duckdb_engine import DuckDBEngine
from .duckdb_structure import (
    DuckDBStructure,
)
from .engine.duckdb_native.connection import (
    DuckDBConnectionWrapper,
)
from .engine.duckdb_native.connector import (
    DuckDBSQLConnector,
)
from .engine.duckdb_native.query_wrapper import (
    DuckDBQueryWrapper,
)
from .service import (
    DuckDBStructureDiffDDLGenerator,
    DuckDBStructureReader,
)

Plugin = ConnectorPlugin(
    connector_class=DuckDBSQLConnector,
    connection_wrapper_class=DuckDBConnectionWrapper,
    credentials_class=DuckDBCredential,
    structure_class_path="nld.connector.duckdb.duckdb_structure.DuckDBStructure",
)

__all__ = [
    "DuckDBConnectionWrapper",
    "DuckDBCredential",
    "DuckDBDataTypes",
    "DuckDBEngine",
    "DuckDBQueryWrapper",
    "DuckDBSQLConnector",
    "DuckDBStructure",
    "DuckDBStructureDiffDDLGenerator",
    "DuckDBStructureReader",
    "DUCKDB_DIALECT",
]
