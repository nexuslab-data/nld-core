from nld.connector.base import ConnectorDefinition
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


class BigQueryConnectorDefinition(ConnectorDefinition):
    """Static engine facts of the BigQuery connector."""

    accepted_data_types: list[str] = [
        data_type.value for data_type in BigQueryDataTypes
    ]
    # BOOL is the canonical BigQuery spelling of the ANSI BOOLEAN type.
    comparable_data_type_aliases: dict[str, str] = {
        "BOOL": "BOOLEAN",
    }
    name: str = "bigquery"


BIGQUERY_CONNECTOR_DEFINITION = BigQueryConnectorDefinition()
