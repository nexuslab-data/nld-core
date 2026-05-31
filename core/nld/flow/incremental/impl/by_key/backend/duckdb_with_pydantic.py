import datetime
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator

from nld.connector.duckdb.engine.duckdb_native.connector import (
    DuckDBSQLConnector,
)
from nld.flow.backend.duckdb.backend_mixin import DuckDBBackendMixin
from nld.flow.backend.duckdb.utils import DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyProcessingState,
    ByKeySingleKeyState,
    ByKeyState,
)
from nld.flow.incremental.models import IncrementalStateStatus
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import normalize_to_utc

DUCKDB_BY_KEY_STATE_TABLE_NAME = (
    f"{DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX}_by_key_state"
)
DUCKDB_BY_KEY_PROCESSING_STATE_TABLE_NAME = (
    f"{DUCKDB_BACKEND_INCREMENTAL_TABLE_PREFIX}_by_key_processing_state"
)


class ByKeyStateRow(NldBaseModel):
    """Database row model for by_key incremental state."""

    model_config = ConfigDict(
        json_schema_extra={
            "functional_key": {
                "fields": ["flow_namespace", "flow_name", "key_name"],
                "name": "fk_by_key_state",
            }
        }
    )

    flow_namespace: str
    flow_name: str
    key_name: str
    status: str | None = None
    last_successfully_processed_at: datetime.datetime | None = None
    last_processed_at: datetime.datetime | None = None
    last_process_status: str | None = None
    last_process_error_message: str | None = None
    first_processed_at: datetime.datetime | None = None
    source_deleted_at: datetime.datetime | None = None
    parameters: dict[str, Any] | None = None

    @field_validator(
        "last_successfully_processed_at",
        "last_processed_at",
        "first_processed_at",
        "source_deleted_at",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)


class ByKeyProcessingStateRow(NldBaseModel):
    """Database row model for by_key incremental processing state."""

    model_config = ConfigDict(
        json_schema_extra={
            "functional_key": {
                "fields": ["flow_namespace", "flow_name", "key_name"],
                "name": "fk_by_key_processing_state",
            }
        }
    )

    flow_uid: str = Field(json_schema_extra={"primary_key": True})
    key_name: str = Field(json_schema_extra={"primary_key": True})
    flow_namespace: str
    flow_name: str
    strategy: str | None = None
    processing_status: str | None = None
    process_error_message: str | None = None
    processing_completed_at: datetime.datetime | None = None
    parameters: dict[str, Any] | None = None

    @field_validator(
        "processing_completed_at",
        mode="before",
    )
    @classmethod
    def normalize_utc_timezone(
        cls,
        value: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Normalize naive or non-UTC datetimes from DB to UTC-aware."""
        return normalize_to_utc(value)


class DuckDBByKeyStateBackendManager(
    DuckDBBackendMixin,
    ByKeyStateBackendManager[DuckDBSQLConnector],
):
    """Incremental - By Key - DuckDB - Backend State Manager

    Manages all read and write methods for by_key incremental state
    using DuckDB.
    """

    param_definitions = []

    def __init__(
        self,
        backend_connector: DuckDBSQLConnector,
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
        """Create the state and processing state tables if they do not exist."""
        schema_name: str = self.backend_schema_name

        self.pydantic_manager.create_table(
            model_class=ByKeyStateRow,
            schema_name=schema_name,
            table_name=DUCKDB_BY_KEY_STATE_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=True,
        )

        self.pydantic_manager.create_table(
            model_class=ByKeyProcessingStateRow,
            schema_name=schema_name,
            table_name=DUCKDB_BY_KEY_PROCESSING_STATE_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=False,
        )

    def read_current_state(self) -> ByKeyState:
        """Retrieve the current by_key state from DuckDB."""
        schema_name: str = self.backend_schema_name

        rows = cast(
            list[ByKeyStateRow],
            self.pydantic_manager.read_models(
                model_class=ByKeyStateRow,
                schema_name=schema_name,
                table_name=DUCKDB_BY_KEY_STATE_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
            ),
        )

        if not rows:
            return ByKeyState()

        keys: dict[str, ByKeySingleKeyState] = {}
        for row in rows:
            keys[row.key_name] = ByKeySingleKeyState(
                name=row.key_name,
                status=row.status or IncrementalStateStatus.NOT_PROCESSED,
                last_successfully_processed_at=row.last_successfully_processed_at,
                last_processed_at=row.last_processed_at,
                last_process_status=row.last_process_status
                or IncrementalStateStatus.NOT_PROCESSED,
                last_process_error_message=row.last_process_error_message,
                first_processed_at=row.first_processed_at,
                source_deleted_at=row.source_deleted_at,
                parameters=row.parameters,
            )

        return ByKeyState(keys=keys)

    def write_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
    ) -> None:
        """Write the processing state for each key to DuckDB."""
        schema_name: str = self.backend_schema_name

        for key_state in processing_flow_state.keys.values():
            row = ByKeyProcessingStateRow(
                flow_namespace=self.flow_namespace,
                flow_name=self.flow_name,
                key_name=key_state.name,
                flow_uid=processing_flow_state.flow_uid,
                strategy=processing_flow_state.strategy,
                processing_status=key_state.processing_status,
                process_error_message=key_state.process_error_message,
                processing_completed_at=key_state.processing_completed_at,
                parameters=key_state.parameters,
            )

            self.pydantic_manager.upsert_model(
                model=row,
                schema_name=schema_name,
                table_name=DUCKDB_BY_KEY_PROCESSING_STATE_TABLE_NAME,
                conflict_fields=["flow_uid", "key_name"],
                commit=True,
                track_timestamps=True,
            )

    def write_partial_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
        identifier: Any,
    ) -> None:
        """Write the processing state for a single key with immediate commit."""
        key_state = processing_flow_state.keys[identifier]
        schema_name: str = self.backend_schema_name

        row = ByKeyProcessingStateRow(
            flow_namespace=self.flow_namespace,
            flow_name=self.flow_name,
            key_name=key_state.name,
            flow_uid=processing_flow_state.flow_uid,
            strategy=processing_flow_state.strategy,
            processing_status=key_state.processing_status,
            process_error_message=key_state.process_error_message,
            processing_completed_at=key_state.processing_completed_at,
            parameters=key_state.parameters,
        )

        self.pydantic_manager.upsert_model(
            model=row,
            schema_name=schema_name,
            table_name=DUCKDB_BY_KEY_PROCESSING_STATE_TABLE_NAME,
            conflict_fields=["flow_uid", "key_name"],
            commit=True,
            track_timestamps=True,
        )

    def write_post_processing_state(
        self, post_processing_flow_state: ByKeyState
    ) -> None:
        """Write the post-processing state for each key to DuckDB."""
        schema_name: str = self.backend_schema_name

        for key_state in post_processing_flow_state.keys.values():
            row = ByKeyStateRow(
                flow_namespace=self.flow_namespace,
                flow_name=self.flow_name,
                key_name=key_state.name,
                status=key_state.status,
                last_successfully_processed_at=key_state.last_successfully_processed_at,
                last_processed_at=key_state.last_processed_at,
                last_process_status=key_state.last_process_status,
                last_process_error_message=key_state.last_process_error_message,
                first_processed_at=key_state.first_processed_at,
                source_deleted_at=key_state.source_deleted_at,
                parameters=key_state.parameters,
            )

            self.pydantic_manager.upsert_model(
                model=row,
                schema_name=schema_name,
                table_name=DUCKDB_BY_KEY_STATE_TABLE_NAME,
                conflict_fields=["flow_namespace", "flow_name", "key_name"],
                commit=False,
                track_timestamps=True,
            )

    def write_partial_post_processing_state(
        self,
        post_processing_flow_state: ByKeyState,
        identifier: Any,
    ) -> None:
        """Write the post-processing state for a single key with immediate commit."""
        key_state = post_processing_flow_state.keys[identifier]
        schema_name: str = self.backend_schema_name

        row = ByKeyStateRow(
            flow_namespace=self.flow_namespace,
            flow_name=self.flow_name,
            key_name=key_state.name,
            status=key_state.status,
            last_successfully_processed_at=key_state.last_successfully_processed_at,
            last_processed_at=key_state.last_processed_at,
            last_process_status=key_state.last_process_status,
            last_process_error_message=key_state.last_process_error_message,
            first_processed_at=key_state.first_processed_at,
            source_deleted_at=key_state.source_deleted_at,
            parameters=key_state.parameters,
        )

        self.pydantic_manager.upsert_model(
            model=row,
            schema_name=schema_name,
            table_name=DUCKDB_BY_KEY_STATE_TABLE_NAME,
            conflict_fields=["flow_namespace", "flow_name", "key_name"],
            commit=True,
            track_timestamps=True,
        )
