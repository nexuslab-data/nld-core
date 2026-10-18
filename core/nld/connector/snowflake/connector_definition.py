from nld.connector.base import ConnectorDefinition
from nld.utils import NldStrEnum


class SnowflakeDataTypes(NldStrEnum):
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    REAL = "REAL"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    VARIANT = "VARIANT"
    TIMESTAMP_LTZ = "TIMESTAMPLTZ"
    TIMESTAMP_TZ = "TIMESTAMPTZ"
    TIMESTAMP_NTZ = "TIMESTAMPNTZ"
    OBJECT = "OBJECT"
    ARRAY = "ARRAY"
    BINARY = "BINARY"
    TIME = "TIME"
    BOOLEAN = "BOOLEAN"


class SnowflakeConnectorDefinition(ConnectorDefinition):
    """Static engine facts of the Snowflake connector."""

    accepted_data_types: list[str] = [
        data_type.value for data_type in SnowflakeDataTypes
    ]
    # Snowflake has a single fixed-point numeric type — every integer
    # spelling is a synonym of NUMBER(38,0) — and spells timestamps
    # TIMESTAMP_NTZ / TIMESTAMP_TZ. Every character type is a synonym
    # of VARCHAR and INFORMATION_SCHEMA reads them all back as TEXT,
    # so an asset spelled VARCHAR would otherwise read as permanent
    # drift against its own live column.
    comparable_data_type_aliases: dict[str, str] = {
        "BIGINT": "NUMERIC",
        "BYTEINT": "NUMERIC",
        "INT2": "NUMERIC",
        "INT4": "NUMERIC",
        "INT8": "NUMERIC",
        "INTEGER": "NUMERIC",
        "NUMBER": "NUMERIC",
        "SMALLINT": "NUMERIC",
        "TINYINT": "NUMERIC",
        "TIMESTAMP": "TIMESTAMP_NTZ",
        "TIMESTAMP WITH TIME ZONE": "TIMESTAMP_TZ",
        "TIMESTAMPTZ": "TIMESTAMP_TZ",
        "CHAR": "VARCHAR",
        "CHARACTER": "VARCHAR",
        "NCHAR": "VARCHAR",
        "NVARCHAR": "VARCHAR",
        "NVARCHAR2": "VARCHAR",
        "STRING": "VARCHAR",
        "TEXT": "VARCHAR",
    }
    # INFORMATION_SCHEMA reports the applied size of a bare declaration
    # (VARCHAR reads back as 16777216 characters, INTEGER as NUMBER(38,0)),
    # so a bare and a sized spelling of one column must compare equal.
    # CHAR is listed apart from its VARCHAR alias: it defaults to 1.
    default_data_type_sizes: dict[str, tuple[int, int]] = {
        "CHAR": (1, 0),
        "CHARACTER": (1, 0),
        "NCHAR": (1, 0),
        "NUMERIC": (38, 0),
        "TIME": (9, 0),
        "TIMESTAMP_LTZ": (9, 0),
        "TIMESTAMP_NTZ": (9, 0),
        "TIMESTAMP_TZ": (9, 0),
        "VARCHAR": (16777216, 0),
    }
    name: str = "snowflake"


SNOWFLAKE_CONNECTOR_DEFINITION = SnowflakeConnectorDefinition()
