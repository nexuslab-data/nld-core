import datetime
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator

from nld.connector.bigquery.bigquery_connector import (
    BigQueryConnector,
)
from nld.flow.backend.bigquery.backend_mixin import BigQueryBackendMixin
from nld.flow.backend.bigquery.utils import BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX
from nld.flow.incremental.impl.by_source_tst.backend.base_with_pydantic import (
    BySourceTstStateBackendManager,
)
from nld.flow.incremental.impl.by_source_tst.state import (
    BySourceTstProcessingState,
    BySourceTstState,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import normalize_to_utc

BIGQUERY_BY_SOURCE_TST_STATE_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX}_by_source_tst_state"
)
BIGQUERY_BY_SOURCE_TST_PROCESSING_STATE_TABLE_NAME = (
    f"{BIGQUERY_BACKEND_INCREMENTAL_TABLE_PREFIX}_by_source_tst_processing_state"
)


class BySourceTstStateRow(NldBaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "functional_key": {
                "fields": ["flow_namespace", "flow_name"],
                "name": "fk_by_source_tst_state",
            }
        }
    )

    flow_namespace: str
    flow_name: str
    last_pull_to_timestamp: datetime.datetime | None = None

    @field_validator(
        "last_pull_to_timestamp",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)


class BySourceTstProcessingStateRow(NldBaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "functional_key": {
                "fields": ["flow_namespace", "flow_name"],
                "name": "fk_by_source_tst_processing_state",
            }
        }
    )

    flow_uid: str = Field(json_schema_extra={"primary_key": True})
    flow_namespace: str
    flow_name: str
    pull_from_timestamp: datetime.datetime | None = None
    pull_to_timestamp: datetime.datetime | None = None
    processing_status: str | None = None
    process_error_message: str | None = None
    processing_completed_at: datetime.datetime | None = None
    strategy: str

    @field_validator(
        "processing_completed_at",
        "pull_from_timestamp",
        "pull_to_timestamp",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)


class BigQueryBySourceTstStateBackendManager(
    BigQueryBackendMixin,
    BySourceTstStateBackendManager[BigQueryConnector],
):
    """
    Incremental - By Source TST - BigQuery - Backend State Manager

    Manages all read and write methods for by_source_tst incremental state
    using BigQuery.
    """

    param_definitions = []

    def __init__(
        self,
        backend_connector: BigQueryConnector,
        flow_namespace: str,
        flow_name: str,
        parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            backend_connector=backend_connector,
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            parameters=parameters,
            **kwargs,
        )

        self.pydantic_manager = self.backend_connector.get_model_manager()

        self._ensure_tables_exist()

        self.log_event(
            IncrementalBackendEngineInitialized(
                backend_type=backend_connector.connection_wrapper.type,
                engine="pydantic",
                manager_class=type(self).__name__,
            ),
        )

    def _ensure_tables_exist(self) -> None:
        self.pydantic_manager.create_table(
            model_class=BySourceTstStateRow,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_BY_SOURCE_TST_STATE_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=True,
        )

        self.pydantic_manager.create_table(
            model_class=BySourceTstProcessingStateRow,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_BY_SOURCE_TST_PROCESSING_STATE_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=False,
        )

    def read_current_state(self) -> BySourceTstState:
        row = cast(
            BySourceTstStateRow | None,
            self.pydantic_manager.read_model(
                model_class=BySourceTstStateRow,
                schema_name=self.backend_schema_name,
                table_name=BIGQUERY_BY_SOURCE_TST_STATE_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
            ),
        )

        if row is None:
            return BySourceTstState()

        return BySourceTstState(
            last_pull_to_timestamp=row.last_pull_to_timestamp,
        )

    def write_processing_state(
        self,
        processing_flow_state: BySourceTstProcessingState,
    ) -> None:
        row = BySourceTstProcessingStateRow(
            flow_namespace=self.flow_namespace,
            flow_name=self.flow_name,
            flow_uid=processing_flow_state.flow_uid,
            process_error_message=processing_flow_state.process_error_message,
            processing_completed_at=processing_flow_state.processing_completed_at,
            processing_status=processing_flow_state.processing_status,
            pull_from_timestamp=processing_flow_state.pull_from_timestamp,
            pull_to_timestamp=processing_flow_state.pull_to_timestamp,
            strategy=processing_flow_state.strategy,
        )

        self.pydantic_manager.upsert_model(
            model=row,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_BY_SOURCE_TST_PROCESSING_STATE_TABLE_NAME,
            conflict_fields=["flow_uid"],
            commit=True,
            track_timestamps=True,
        )

    def write_post_processing_state(
        self, post_processing_flow_state: BySourceTstState
    ) -> None:
        row = BySourceTstStateRow(
            flow_namespace=self.flow_namespace,
            flow_name=self.flow_name,
            last_pull_to_timestamp=post_processing_flow_state.last_pull_to_timestamp,
        )

        self.pydantic_manager.upsert_model(
            model=row,
            schema_name=self.backend_schema_name,
            table_name=BIGQUERY_BY_SOURCE_TST_STATE_TABLE_NAME,
            conflict_fields=["flow_namespace", "flow_name"],
            commit=False,
            track_timestamps=True,
        )
