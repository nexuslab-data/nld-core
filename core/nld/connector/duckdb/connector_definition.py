from nld.connector.base import ConnectorDefinition
from nld.utils import NldStrEnum


class DuckDBDataTypes(NldStrEnum):
    """Enum class for DuckDB data types.

    This class provides a set of constants representing the various data types
    supported by DuckDB, grouped by category.
    """

    # Integer
    TINYINT = "TINYINT"
    SMALLINT = "SMALLINT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    HUGEINT = "HUGEINT"

    # Unsigned integer
    UTINYINT = "UTINYINT"
    USMALLINT = "USMALLINT"
    UINTEGER = "UINTEGER"
    UBIGINT = "UBIGINT"
    UHUGEINT = "UHUGEINT"

    # Floating-point / numeric
    FLOAT = "FLOAT"
    DOUBLE = "DOUBLE"
    DECIMAL = "DECIMAL"

    # Boolean
    BOOLEAN = "BOOLEAN"

    # String
    VARCHAR = "VARCHAR"
    CHARACTER_VARYING = "CHARACTER VARYING"
    TEXT = "TEXT"

    # Date / time
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMPTZ = "TIMESTAMP WITH TIME ZONE"
    INTERVAL = "INTERVAL"

    # Binary / bit
    BLOB = "BLOB"
    BIT = "BIT"

    # Semi-structured
    JSON = "JSON"

    # UUID
    UUID = "UUID"


class DuckDBConnectorDefinition(ConnectorDefinition):
    """Static engine facts of the DuckDB connector."""

    accepted_data_types: list[str] = [data_type.value for data_type in DuckDBDataTypes]
    # DuckDB accepts the PostgreSQL-family spellings, mapped to the same
    # canonical comparable forms.
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
        "DOUBLE",
        "FLOAT",
        "HUGEINT",
        "INTEGER",
        "SMALLINT",
        "TINYINT",
        "VARCHAR",
    ]
    name: str = "duckdb"


DUCKDB_CONNECTOR_DEFINITION = DuckDBConnectorDefinition()
