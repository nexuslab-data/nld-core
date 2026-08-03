import datetime
from typing import Any, cast

from pydantic import ConfigDict, Field, field_validator

from nld.connector.snowflake.snowflake_connector import (
    SnowflakeConnector,
)
from nld.flow.backend.snowflake.utils import SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX
from nld.flow.incremental.backend.snowflake import SnowflakeIncrementalBackendMixin
from nld.flow.incremental.impl.by_key.backend.base_with_pydantic import (
    ByKeyStateBackendManager,
)
from nld.flow.incremental.impl.by_key.state import (
    ByKeyPlannedProcessingDetailedState,
    ByKeyProcessingState,
    ByKeySingleKeyPlannedProcessingDetailedState,
    ByKeySingleKeyProcessingState,
    ByKeySingleKeyState,
    ByKeyState,
)
from nld.flow.incremental.models import (
    IncrementalProcessingStatus,
    IncrementalStateStatus,
)
from nld.flow.incremental.models.events import (
    IncrementalBackendEngineInitialized,
)
from nld.pydantic import NldBaseModel
from nld.utils.datetime_util import normalize_to_utc

SNOWFLAKE_BY_KEY_STATE_TABLE_NAME = (
    f"{SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX}_by_key_state"
)
SNOWFLAKE_BY_KEY_PROCESSING_STATE_TABLE_NAME = (
    f"{SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX}_by_key_processing_state"
)
SNOWFLAKE_BY_KEY_PLANNED_PROCESSING_STATE_TABLE_NAME = (
    f"{SNOWFLAKE_BACKEND_INCREMENTAL_TABLE_PREFIX}"
    "_plans_by_key_planned_processing_state"
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


class ByKeyPlannedProcessingStateRow(NldBaseModel):
    """Detail row for the by_key planned-state slot.

    One row per (plan, key). Mirrors ``ByKeyProcessingStateRow`` but
    is keyed on ``plan_state_uid`` only — a plan is a precomputed
    proposal and has no live execution UID; the consumer
    (``execute --use-precomputed``) assigns the real ``flow_uid`` at
    hydration time.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "functional_key": {
                "fields": ["plan_state_uid", "key_name"],
                "name": "fk_by_key_planned_processing_state",
            },
        },
    )

    plan_state_uid: str = Field(json_schema_extra={"primary_key": True})
    key_name: str = Field(json_schema_extra={"primary_key": True})
    flow_namespace: str
    flow_name: str
    strategy: str | None = None
    planned_processing_status: str | None = None
    parameters: dict[str, Any] | None = None


class SnowflakeByKeyStateBackendManager(
    SnowflakeIncrementalBackendMixin,
    ByKeyStateBackendManager[SnowflakeConnector],
):
    """
    Incremental - By Key - Snowflake - Backend State Manager

    Manages all read and write methods for by_key incremental state
    using Snowflake.
    """

    param_definitions = []

    def __init__(
        self,
        backend_connector: SnowflakeConnector,
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
        self._ensure_planned_state_table_exists()

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
            table_name=SNOWFLAKE_BY_KEY_STATE_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=True,
        )

        self.pydantic_manager.create_table(
            model_class=ByKeyProcessingStateRow,
            schema_name=schema_name,
            table_name=SNOWFLAKE_BY_KEY_PROCESSING_STATE_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=False,
        )

    def read_processing_state(self) -> ByKeyProcessingState | None:
        """Read the current persisted processing state for this flow.

        Returns ``None`` when no processing-state rows exist; otherwise
        the latest run's keys (grouped by ``flow_uid`` of the most recent
        ``processing_completed_at``).
        """
        rows = cast(
            list[ByKeyProcessingStateRow],
            self.pydantic_manager.read_models(
                model_class=ByKeyProcessingStateRow,
                schema_name=self.backend_schema_name,
                table_name=SNOWFLAKE_BY_KEY_PROCESSING_STATE_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
                order_by=["-processing_completed_at"],
            ),
        )
        if not rows:
            return None

        latest_flow_uid = rows[0].flow_uid
        latest_strategy = rows[0].strategy or ""
        keys: dict[str, ByKeySingleKeyProcessingState] = {}
        for row in rows:
            if row.flow_uid != latest_flow_uid:
                continue
            keys[row.key_name] = ByKeySingleKeyProcessingState(
                name=row.key_name,
                processing_status=row.processing_status
                or IncrementalProcessingStatus.TO_BE_PROCESSED,
                process_error_message=row.process_error_message,
                processing_completed_at=row.processing_completed_at,
                parameters=row.parameters,
            )
        return ByKeyProcessingState(
            flow_uid=latest_flow_uid,
            strategy=latest_strategy,
            keys=keys,
        )

    def read_post_processing_state(self) -> ByKeyState | None:
        """Read the current persisted post-processing state for this flow.

        Returns the same data as ``read_current_state`` but returns
        ``None`` when no row exists instead of an empty default state.
        """
        rows = cast(
            list[ByKeyStateRow],
            self.pydantic_manager.read_models(
                model_class=ByKeyStateRow,
                schema_name=self.backend_schema_name,
                table_name=SNOWFLAKE_BY_KEY_STATE_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
            ),
        )
        if not rows:
            return None
        return ByKeyState(keys=self._rows_to_single_key_states(rows=rows))

    def read_current_state(self) -> ByKeyState:
        """Retrieve the current by_key state from Snowflake."""
        rows = cast(
            list[ByKeyStateRow],
            self.pydantic_manager.read_models(
                model_class=ByKeyStateRow,
                schema_name=self.backend_schema_name,
                table_name=SNOWFLAKE_BY_KEY_STATE_TABLE_NAME,
                where_conditions={
                    "flow_namespace": self.flow_namespace,
                    "flow_name": self.flow_name,
                },
            ),
        )

        if not rows:
            return ByKeyState()

        return ByKeyState(keys=self._rows_to_single_key_states(rows=rows))

    @staticmethod
    def _rows_to_single_key_states(
        rows: list[ByKeyStateRow],
    ) -> dict[str, ByKeySingleKeyState]:
        """Hydrate the per-key states from their state-table rows."""
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
        return keys

    def _build_processing_state_row(
        self,
        processing_flow_state: ByKeyProcessingState,
        key_state: ByKeySingleKeyProcessingState,
    ) -> ByKeyProcessingStateRow:
        """Project a single key's processing state onto its row form."""
        return ByKeyProcessingStateRow(
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

    def _build_state_row(
        self,
        key_state: ByKeySingleKeyState,
    ) -> ByKeyStateRow:
        """Project a single key's post-processing state onto its row form."""
        return ByKeyStateRow(
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

    def write_processing_state(
        self,
        processing_flow_state: ByKeyProcessingState,
    ) -> None:
        """Write the processing state for each key to Snowflake.

        Snowflake's pydantic manager has no bulk upsert, so each key
        row goes through its own MERGE statement.
        """
        for key_state in processing_flow_state.keys.values():
            row = self._build_processing_state_row(
                processing_flow_state=processing_flow_state,
                key_state=key_state,
            )

            self.pydantic_manager.upsert_model(
                model=row,
                schema_name=self.backend_schema_name,
                table_name=SNOWFLAKE_BY_KEY_PROCESSING_STATE_TABLE_NAME,
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
        row = self._build_processing_state_row(
            processing_flow_state=processing_flow_state,
            key_state=processing_flow_state.keys[identifier],
        )

        self.pydantic_manager.upsert_model(
            model=row,
            schema_name=self.backend_schema_name,
            table_name=SNOWFLAKE_BY_KEY_PROCESSING_STATE_TABLE_NAME,
            conflict_fields=["flow_uid", "key_name"],
            commit=True,
            track_timestamps=True,
        )

    def write_post_processing_state(
        self, post_processing_flow_state: ByKeyState
    ) -> None:
        """Write the post-processing state for each key to Snowflake."""
        for key_state in post_processing_flow_state.keys.values():
            row = self._build_state_row(key_state=key_state)

            self.pydantic_manager.upsert_model(
                model=row,
                schema_name=self.backend_schema_name,
                table_name=SNOWFLAKE_BY_KEY_STATE_TABLE_NAME,
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
        row = self._build_state_row(
            key_state=post_processing_flow_state.keys[identifier],
        )

        self.pydantic_manager.upsert_model(
            model=row,
            schema_name=self.backend_schema_name,
            table_name=SNOWFLAKE_BY_KEY_STATE_TABLE_NAME,
            conflict_fields=["flow_namespace", "flow_name", "key_name"],
            commit=True,
            track_timestamps=True,
        )

    # ---- SnowflakeIncrementalBackendMixin hooks. ----

    def _ensure_planned_processing_state_table_exists(self) -> None:
        """Create the by_key planned processing-state table if absent."""
        self.pydantic_manager.create_table(
            model_class=ByKeyPlannedProcessingStateRow,
            schema_name=self.backend_schema_name,
            table_name=SNOWFLAKE_BY_KEY_PLANNED_PROCESSING_STATE_TABLE_NAME,
            table_exists="skip",
            track_timestamps=True,
            use_functional_key_as_primary=True,
        )

    def write_planned_processing_state(
        self,
        plan_state_uid: str,
        detailed_state: ByKeyPlannedProcessingDetailedState,
    ) -> None:
        """Persist the per-key planned-state rows for a new PLANNED plan."""
        for key_detail in detailed_state.keys.values():
            row = ByKeyPlannedProcessingStateRow(
                plan_state_uid=plan_state_uid,
                key_name=key_detail.name,
                flow_namespace=self.flow_namespace,
                flow_name=self.flow_name,
                strategy=detailed_state.strategy,
                planned_processing_status=key_detail.planned_processing_status,
                parameters=key_detail.parameters,
            )
            self.pydantic_manager.upsert_model(
                model=row,
                schema_name=self.backend_schema_name,
                table_name=SNOWFLAKE_BY_KEY_PLANNED_PROCESSING_STATE_TABLE_NAME,
                conflict_fields=["plan_state_uid", "key_name"],
                commit=True,
                track_timestamps=True,
            )

    def read_planned_processing_state(
        self,
        plan_state_uid: str,
    ) -> ByKeyPlannedProcessingDetailedState | None:
        """Reconstruct the by_key planned detail from its rows."""
        rows = cast(
            list[ByKeyPlannedProcessingStateRow],
            self.pydantic_manager.read_models(
                model_class=ByKeyPlannedProcessingStateRow,
                schema_name=self.backend_schema_name,
                table_name=SNOWFLAKE_BY_KEY_PLANNED_PROCESSING_STATE_TABLE_NAME,
                where_conditions={"plan_state_uid": plan_state_uid},
            ),
        )
        if not rows:
            return None
        keys: dict[str, ByKeySingleKeyPlannedProcessingDetailedState] = {}
        for row in rows:
            keys[row.key_name] = ByKeySingleKeyPlannedProcessingDetailedState(
                name=row.key_name,
                planned_processing_status=(
                    row.planned_processing_status
                    or IncrementalProcessingStatus.TO_BE_PROCESSED
                ),
                parameters=row.parameters,
            )
        return ByKeyPlannedProcessingDetailedState(
            plan_state_uid=plan_state_uid,
            strategy=rows[0].strategy or "",
            keys=keys,
        )
