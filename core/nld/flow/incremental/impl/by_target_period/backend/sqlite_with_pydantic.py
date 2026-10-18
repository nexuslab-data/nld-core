from nld.connector.sqlite.engine.sqlite_native.connector import (
    SQLiteSQLConnector,
)
from nld.flow.backend.sqlite.utils import SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX
from nld.flow.incremental.backend.sqlite import SQLiteIncrementalBackendMixin
from nld.flow.incremental.impl.by_target_period.backend.sql_model_base import (
    PERIOD_STATE_TABLE_SUFFIX,
    PLANNED_PROCESSING_STATE_TABLE_SUFFIX,
    PROCESSING_STATE_TABLE_SUFFIX,
    STATE_TABLE_SUFFIX,
    SQLModelByTargetPeriodStateBackendManager,
)

SQLITE_BY_TARGET_PERIOD_STATE_TABLE_NAME = (
    f"{SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX}{STATE_TABLE_SUFFIX}"
)
SQLITE_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME = (
    f"{SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX}{PERIOD_STATE_TABLE_SUFFIX}"
)
SQLITE_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME = (
    f"{SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX}{PROCESSING_STATE_TABLE_SUFFIX}"
)
SQLITE_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME = (
    f"{SQLITE_BACKEND_INCREMENTAL_TABLE_PREFIX}{PLANNED_PROCESSING_STATE_TABLE_SUFFIX}"
)


class SQLiteByTargetPeriodStateBackendManager(
    SQLiteIncrementalBackendMixin,
    SQLModelByTargetPeriodStateBackendManager[SQLiteSQLConnector],
):
    """
    Incremental - By Target Period - SQLite - Backend State Manager

    Persists the by_target_period state in SQLite through the shared
    model-manager layout of ``SQLModelByTargetPeriodStateBackendManager``.
    Holds PLANNED plans through ``SQLiteIncrementalBackendMixin`` (state-plan table
    ``_nld_incremental_plans``).
    """

    param_definitions = []

    state_table_name = SQLITE_BY_TARGET_PERIOD_STATE_TABLE_NAME
    period_state_table_name = SQLITE_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME
    processing_state_table_name = SQLITE_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME
    planned_processing_state_table_name = (
        SQLITE_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME
    )

    def _ensure_planned_processing_state_table_exists(self) -> None:
        """Create the by_target_period planned processing-state table if absent."""
        self._create_planned_processing_state_table()
