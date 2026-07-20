from typing import Any

from nld.connector.base.data_profiler import (
    DEFAULT_NUMERIC_TYPE_TOKENS,
    SQLConnectorDataProfiler,
)


class SnowflakeDataProfiler(SQLConnectorDataProfiler[Any]):
    """Data profiler for Snowflake.

    Builds its audit aggregates through the Snowflake sqlglot DML builder
    (``snowflake`` dialect). Snowflake stores all fixed/exact numerics under the
    ``NUMBER`` type (and floats under ``FLOAT``/``DOUBLE``), so the numeric token
    set is extended with ``NUMBER`` to ensure those columns receive a min/max
    range measure.
    """

    numeric_type_tokens = DEFAULT_NUMERIC_TYPE_TOKENS + ("NUMBER",)
