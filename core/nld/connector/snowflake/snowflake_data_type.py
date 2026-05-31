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
