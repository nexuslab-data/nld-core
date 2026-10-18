from nld.connector.duckdb.engine.duckdb_native.connector import (
    DuckDBSQLConnector,
)
from nld.flow.backend.duckdb.backend_mixin import DuckDBBackendMixin
from nld.flow.backend.duckdb.utils import DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX
from nld.flow.incremental.impl.by_target_period.backend.sql_model_base import (
    PERIOD_STATE_TABLE_SUFFIX,
    PLANNED_PROCESSING_STATE_TABLE_SUFFIX,
    PROCESSING_STATE_TABLE_SUFFIX,
    STATE_TABLE_SUFFIX,
    SQLModelByTargetPeriodStateBackendManager,
)

DUCKDB_BY_TARGET_PERIOD_STATE_TABLE_NAME = (
    f"{DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX}{STATE_TABLE_SUFFIX}"
)
DUCKDB_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME = (
    f"{DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX}{PERIOD_STATE_TABLE_SUFFIX}"
)
DUCKDB_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME = (
    f"{DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX}{PROCESSING_STATE_TABLE_SUFFIX}"
)
DUCKDB_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME = (
    f"{DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX}{PLANNED_PROCESSING_STATE_TABLE_SUFFIX}"
)


class DuckDBByTargetPeriodStateBackendManager(
    DuckDBBackendMixin,
    SQLModelByTargetPeriodStateBackendManager[DuckDBSQLConnector],
):
    """
    Incremental - By Target Period - DuckDB - Backend State Manager

    Persists the by_target_period state in DuckDB through the shared
    model-manager layout of ``SQLModelByTargetPeriodStateBackendManager``.
    This connector has no planned-state mixin, so plans are not
    supported (``compute --persist`` reports ``persisted=False``).
    """

    param_definitions = []

    state_table_name = DUCKDB_BY_TARGET_PERIOD_STATE_TABLE_NAME
    period_state_table_name = DUCKDB_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME
    processing_state_table_name = DUCKDB_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME
    planned_processing_state_table_name = (
        DUCKDB_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME
    )
