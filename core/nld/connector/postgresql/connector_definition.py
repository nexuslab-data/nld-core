from nld.connector.base import ConnectorDefinition
from nld.utils import NldStrEnum


class PostgreSQLDataTypes(NldStrEnum):
    """Enum class for PostgreSQL data types.

    This class provides a set of constants representing the various data types
    supported by PostgreSQL. It can be used to define the types of fields in a
    PostgreSQL database schema.
    """

    BIGINT = "BIGINT"
    BIGSERIAL = "BIGSERIAL"
    BIT = "BIT"
    VARBIT = "BIT VARYING"
    BOOL = "BOOLEAN"
    BOX = "BOX"
    BYTEA = "BYTEA"
    CHARACTER = "CHARACTER"
    CHARACTER_VARYING = "CHARACTER VARYING"
    VARCHAR = "VARCHAR"
    CIDR = "CIDR"
    CIRCLE = "CIRCLE"
    DATE = "DATE"
    DOUBLE_PRECISION = "DOUBLE PRECISION"
    INET = "INET"
    INTEGER = "INTEGER"
    INTERVAL = "INTERVAL"
    JSON = "JSON"
    JSONB = "JSONB"
    LINE = "LINE"
    LSEG = "LSEG"
    MACADDR = "MACADDR"
    MACADDR8 = "MACADDR8"
    MONEY = "MONEY"
    NUMERIC = "NUMERIC"
    PATH = "PATH"
    POINT = "POINT"
    POLYGON = "POLYGON"
    REAL = "REAL"
    SMALLINT = "SMALLINT"
    SERIAL = "SERIAL"
    TEXT = "TEXT"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMPTZ = "TIMESTAMP WITH TIME ZONE"
    TSQUERY = "TSQUERY"
    TSVECTOR = "TSVECTOR"
    TXID_SNAPSHOT = "TXID_SNAPSHOT"
    UUID = "UUID"
    XML = "XML"


class PostgreSQLConnectorDefinition(ConnectorDefinition):
    """Static engine facts of the PostgreSQL connector."""

    accepted_data_types: list[str] = [
        data_type.value for data_type in PostgreSQLDataTypes
    ]
    # The PostgreSQL-family spellings the reader and asset authors use,
    # mapped to their canonical comparable form.
    comparable_data_type_aliases: dict[str, str] = {
        "BOOL": "BOOLEAN",
        "FLOAT4": "REAL",
        "FLOAT8": "DOUBLE PRECISION",
        "INT2": "SMALLINT",
        "INT4": "INTEGER",
        "INT8": "BIGINT",
        "TIMESTAMPTZ": "TIMESTAMP WITH TIME ZONE",
    }
    # Types whose precision is fixed by the engine and never reported.
    fixed_precision_data_types: list[str] = [
        "BIGINT",
        "BOOLEAN",
        "DATE",
        "DOUBLE PRECISION",
        "INT",
        "INTEGER",
        "REAL",
        "SMALLINT",
        "TEXT",
    ]
    name: str = "postgresql"


POSTGRESQL_CONNECTOR_DEFINITION = PostgreSQLConnectorDefinition()
