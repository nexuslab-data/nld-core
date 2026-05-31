from nld.connector.base import ConnectorPlugin

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
from .postgresql_data_type import (
    PostgreSQLDataTypes,
)
from .postgresql_structure import (
    PostgreSQLStructure,
)
from .service import (
    PostgreSQLStructureDiffDDLGenerator,
    PostgreSQLStructureReader,
)

Plugin = ConnectorPlugin(
    connector_class=Psycopg2SQLConnector,
    connection_wrapper_class=Psycopg2SQLConnectionWrapper,
    credentials_class=PostgreSQLCredential,
    structure_class_path="nld.connector.postgresql.postgresql_structure.PostgreSQLStructure",
)

__all__ = [
    "PostgreSQLCredential",
    "PostgreSQLDataTypes",
    "PostgreSQLStructure",
    "PostgreSQLStructureDiffDDLGenerator",
    "PostgreSQLStructureReader",
    "Psycopg2QueryWrapper",
    "Psycopg2SQLConnectionWrapper",
    "Psycopg2SQLConnector",
]
