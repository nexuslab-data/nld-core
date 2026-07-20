from typing import Any

from nld.connector.base.data_profiler import (
    DEFAULT_NUMERIC_TYPE_TOKENS,
    DEFAULT_TEMPORAL_TYPE_TOKENS,
    SQLConnectorDataProfiler,
)


class BigQueryDataProfiler(SQLConnectorDataProfiler[Any]):
    """Data profiler for BigQuery.

    Builds its audit aggregates through the BigQuery sqlglot DML builder
    (``bigquery`` dialect, which renders the random-sampling clause as
    ``RAND()``). BigQuery's scalar numeric types are ``INT64`` / ``FLOAT64`` /
    ``NUMERIC`` / ``BIGNUMERIC`` — all matched by the default tokens — and its
    temporal types add ``DATETIME``; the token sets are stated explicitly here
    so the BigQuery type vocabulary is documented at the engine boundary.
    """

    numeric_type_tokens = DEFAULT_NUMERIC_TYPE_TOKENS
    temporal_type_tokens = DEFAULT_TEMPORAL_TYPE_TOKENS + ("DATETIME",)
