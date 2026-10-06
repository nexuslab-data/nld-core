from nld.connector.base import ConnectorDefinition
from nld.utils import NldStrEnum


class SQLiteStorageAffinities(NldStrEnum):
    """The five storage classes every SQLite column resolves to."""

    BLOB = "BLOB"
    INTEGER = "INTEGER"
    NUMERIC = "NUMERIC"
    REAL = "REAL"
    TEXT = "TEXT"


class SQLiteDataTypes(NldStrEnum):
    """Data type spellings a structure may declare on a SQLite target.

    SQLite stores the declared type verbatim and derives a storage affinity
    from it, so the portable spellings of the other engines are all accepted
    and behave identically. The list exists to reject typos, not to restrict
    what SQLite can store.
    """

    # Integer
    INTEGER = "INTEGER"
    INT = "INT"
    SMALLINT = "SMALLINT"
    BIGINT = "BIGINT"

    # Floating-point / numeric
    REAL = "REAL"
    FLOAT = "FLOAT"
    DOUBLE = "DOUBLE"
    DOUBLE_PRECISION = "DOUBLE PRECISION"
    DECIMAL = "DECIMAL"
    NUMERIC = "NUMERIC"

    # Boolean
    BOOLEAN = "BOOLEAN"

    # String
    CHARACTER_VARYING = "CHARACTER VARYING"
    VARCHAR = "VARCHAR"
    CHARACTER = "CHARACTER"
    CHAR = "CHAR"
    TEXT = "TEXT"

    # Date / time
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMPTZ = "TIMESTAMP WITH TIME ZONE"

    # Binary
    BLOB = "BLOB"

    # Semi-structured (stored as text)
    JSON = "JSON"

    # UUID (stored as text)
    UUID = "UUID"


def resolve_storage_affinity(data_type: str) -> str:
    """Resolve a declared type name to its SQLite storage affinity.

    Implements the affinity rules of the SQLite documentation, in their
    declared precedence order. An empty type is BLOB, as it is for a column
    declared without a type at all.
    """
    upper_type = data_type.upper().strip() if data_type else ""
    if not upper_type:
        return SQLiteStorageAffinities.BLOB
    if "INT" in upper_type:
        return SQLiteStorageAffinities.INTEGER
    if any(token in upper_type for token in ("CHAR", "CLOB", "TEXT")):
        return SQLiteStorageAffinities.TEXT
    if "BLOB" in upper_type:
        return SQLiteStorageAffinities.BLOB
    if any(token in upper_type for token in ("REAL", "FLOA", "DOUB")):
        return SQLiteStorageAffinities.REAL
    return SQLiteStorageAffinities.NUMERIC


class SQLiteConnectorDefinition(ConnectorDefinition):
    """Static engine facts of the SQLite connector.

    ``comparable_data_type_aliases`` collapses every accepted spelling onto
    its storage affinity. SQLite enforces no type beyond that affinity, so
    two spellings sharing one affinity describe the same physical column:
    comparing the affinities is what keeps a hand-written ``varchar(200)``
    from reading as drift against a declared ``TEXT``.
    """

    accepted_data_types: list[str] = [data_type.value for data_type in SQLiteDataTypes]
    comparable_data_type_aliases: dict[str, str] = {
        data_type.value: resolve_storage_affinity(data_type.value)
        for data_type in SQLiteDataTypes
    }
    # Every type is stored by affinity, so no length or precision is ever
    # enforced or reported back by the catalogue.
    fixed_precision_data_types: list[str] = [
        data_type.value for data_type in SQLiteDataTypes
    ]
    name: str = "sqlite"


SQLITE_CONNECTOR_DEFINITION = SQLiteConnectorDefinition()
