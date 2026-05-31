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
