from nld.connector.bigquery.bigquery_connector import BigQueryConnector
from nld.flow.backend.bigquery.backend_mixin import BigQueryBackendMixin
from nld.flow.backend.bigquery.utils import BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX
from nld.flow.incremental.impl.by_target_period.backend.sql_model_base import (
    PERIOD_STATE_TABLE_SUFFIX,
    PLANNED_PROCESSING_STATE_TABLE_SUFFIX,
    PROCESSING_STATE_TABLE_SUFFIX,
    STATE_TABLE_SUFFIX,
    SQLModelByTargetPeriodStateBackendManager,
)

BIGQUERY_BY_TARGET_PERIOD_STATE_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX}{STATE_TABLE_SUFFIX}"
)
BIGQUERY_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX}{PERIOD_STATE_TABLE_SUFFIX}"
)
BIGQUERY_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX}{PROCESSING_STATE_TABLE_SUFFIX}"
)
BIGQUERY_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX}"
    f"{PLANNED_PROCESSING_STATE_TABLE_SUFFIX}"
)


class BigQueryByTargetPeriodStateBackendManager(
    BigQueryBackendMixin,
    SQLModelByTargetPeriodStateBackendManager[BigQueryConnector],
):
    """
    Incremental - By Target Period - BigQuery - Backend State Manager

    Persists the by_target_period state in BigQuery through the shared
    model-manager layout of ``SQLModelByTargetPeriodStateBackendManager``.
    This connector has no planned-state mixin, so plans are not
    supported (``compute --persist`` reports ``persisted=False``).
    """

    param_definitions = []

    state_table_name = BIGQUERY_BY_TARGET_PERIOD_STATE_TABLE_NAME
    period_state_table_name = BIGQUERY_BY_TARGET_PERIOD_PERIOD_STATE_TABLE_NAME
    processing_state_table_name = BIGQUERY_BY_TARGET_PERIOD_PROCESSING_STATE_TABLE_NAME
    planned_processing_state_table_name = (
        BIGQUERY_BY_TARGET_PERIOD_PLANNED_PROCESSING_STATE_TABLE_NAME
    )
