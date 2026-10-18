from nld.connector.snowflake.snowflake_connector import SnowflakeConnector
from nld.flow.backend.snowflake.utils import SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX
from nld.flow.incremental.backend.snowflake import SnowflakeIncrementalBackendMixin
from nld.flow.incremental.impl.by_target_period.backend.sql_model_base import (
    PERIOD_STATE_TABLE_SUFFIX,
    PLANNED_PROCESSING_STATE_TABLE_SUFFIX,
    PROCESSING_STATE_TABLE_SUFFIX,
    STATE_TABLE_SUFFIX,
    SQLModelByTargetPeriodStateBackendManager,
)

SNOWFLAKE_BY_TARGET_PERIOD_STATE_TABLE_NAME = (
    f"{SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX}{STATE_TABLE_SUFFIX}"
)
SNOWFLAKE_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME = (
    f"{SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX}{PERIOD_STATE_TABLE_SUFFIX}"
)
SNOWFLAKE_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME = (
    f"{SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX}{PROCESSING_STATE_TABLE_SUFFIX}"
)
SNOWFLAKE_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME = (
    f"{SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX}"
    f"{PLANNED_PROCESSING_STATE_TABLE_SUFFIX}"
)


class SnowflakeByTargetPeriodStateBackendManager(
    SnowflakeIncrementalBackendMixin,
    SQLModelByTargetPeriodStateBackendManager[SnowflakeConnector],
):
    """
    Incremental - By Target Period - Snowflake - Backend State Manager

    Persists the by_target_period state in Snowflake through the shared
    model-manager layout of ``SQLModelByTargetPeriodStateBackendManager``.
    Holds PLANNED plans through ``SnowflakeIncrementalBackendMixin`` (state-plan table
    ``_nld_incremental_plans``).
    """

    param_definitions = []

    state_table_name = SNOWFLAKE_BY_TARGET_PERIOD_STATE_TABLE_NAME
    period_state_table_name = SNOWFLAKE_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME
    processing_state_table_name = SNOWFLAKE_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME
    planned_processing_state_table_name = (
        SNOWFLAKE_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME
    )

    def _ensure_planned_processing_state_table_exists(self) -> None:
        """Create the by_target_period planned processing-state table if absent."""
        self._create_planned_processing_state_table()
