from typing import Any

from nld.connector.base.data_profiler import SQLConnectorDataProfiler


class SQLiteDataProfiler(SQLConnectorDataProfiler[Any]):
    """Data profiler for SQLite.

    Builds its audit aggregates through the SQLite sqlglot DML builder
    (``sqlite`` dialect). The declared type names are the portable ones
    (``INTEGER``, ``REAL``, ``NUMERIC``, ``TEXT``, ``TIMESTAMP`` …) already
    covered by the default token sets.
    """
