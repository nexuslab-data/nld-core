from nld.utils import NldStrEnum


class BigQueryDataTypes(NldStrEnum):
    ARRAY = "ARRAY"
    BIGNUMERIC = "BIGNUMERIC"
    BOOL = "BOOL"
    BYTES = "BYTES"
    DATE = "DATE"
    DATETIME = "DATETIME"
    FLOAT64 = "FLOAT64"
    GEOGRAPHY = "GEOGRAPHY"
    INT64 = "INT64"
    JSON = "JSON"
    NUMERIC = "NUMERIC"
    RECORD = "RECORD"
    STRING = "STRING"
    STRUCT = "STRUCT"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
