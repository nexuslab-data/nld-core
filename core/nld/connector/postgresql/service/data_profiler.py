from typing import Any

from nld.connector.base.data_profiler import SQLConnectorDataProfiler


class PostgreSQLDataProfiler(SQLConnectorDataProfiler[Any]):
    """Data profiler for PostgreSQL.

    Builds its audit aggregates through the PostgreSQL sqlglot DML builder
    (``postgres`` dialect) and runs them with the connector. PostgreSQL's
    numeric/temporal type names (``INTEGER``, ``NUMERIC``, ``TIMESTAMP WITH TIME
    ZONE`` …) are all covered by the default token sets, so no override is
    needed.
    """
