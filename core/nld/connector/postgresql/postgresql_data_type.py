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
