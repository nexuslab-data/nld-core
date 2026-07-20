from typing import Any

from nld.connector.base.data_profiler import SQLConnectorDataProfiler


class DuckDBDataProfiler(SQLConnectorDataProfiler[Any]):
    """Data profiler for DuckDB.

    Builds its audit aggregates through the DuckDB sqlglot DML builder
    (``duckdb`` dialect). DuckDB's numeric/temporal type names (``INTEGER``,
    ``HUGEINT``, ``DOUBLE``, ``DECIMAL``, ``TIMESTAMP`` …) are covered by the
    default token sets.
    """
